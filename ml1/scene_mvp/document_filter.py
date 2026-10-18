"""Tiny supervised candidate-quality head; never an identity/absence classifier."""
import math
import numpy as np
from scipy.optimize import minimize
from scipy.special import expit

SPEC = {
    'version': 'reviewed-document-candidate-filter/1',
    'regularization': .01,
    'accepted_cutoff': .65,
    'rejected_cutoff': .35,
    'crop_context_scale': 1.5,
    'trained_target': 'human_acceptance_of_a_localized_document_candidate',
    'negative_label_scope': 'rejected_displayed_box_not_whole_frame_document_absence',
    'score_is_calibrated_probability': False,
    'absence_decision_allowed': False,
    'identity_verification_established': False,
}


def candidate_examples(review):
    if review.get('confirmed') is not True or review.get('approved_for_rule_engine') is not False:
        raise ValueError('Confirmed limited-scope review required')
    examples = []
    for row in review['reviews']:
        selected = row['human_selection']
        if selected == 'unclear': continue
        if selected not in {'A','B','C','none'}: raise ValueError('Unknown answer')
        for index, proposal in enumerate(row['proposals']):
            # Other boxes beside a positive selection were not explicitly rejected.
            if selected != 'none' and index != ord(selected)-65: continue
            examples.append({'source_session': row['source_session'], 'source_video_sha256': row['source_video_sha256'],
                'frame_sha256': row['frame_sha256'], 'timestamp_sec': row['timestamp_sec'], 'bbox': proposal['bbox'],
                'label': int(selected != 'none'), 'label_kind': 'accepted_document_box' if selected != 'none' else 'rejected_document_candidate_box',
                'label_source': 'human_candidate_review', 'source_review_key': row['key'],
                'frame_group': row['source_video_sha256']+':'+row['frame_sha256'], 'split_group': row['source_video_sha256']})
    return examples


def sample_weights(rows):
    """Equal classes, then videos within class, frames within video, views within frame."""
    labels = {r['label'] for r in rows}
    if labels != {0,1}: raise ValueError('Both reviewed classes required')
    weights = []
    for row in rows:
        same_label = [r for r in rows if r['label'] == row['label']]
        videos = {r['split_group'] for r in same_label}
        same_video = [r for r in same_label if r['split_group'] == row['split_group']]
        frames = {r['frame_group'] for r in same_video}
        views = sum(r['frame_group'] == row['frame_group'] for r in same_video)
        weights.append(1/(2*len(videos)*len(frames)*views))
    weights = np.asarray(weights, np.float64)
    return weights/weights.sum()


def grouped_folds(rows):
    for group in sorted({r['split_group'] for r in rows}):
        train = [i for i,r in enumerate(rows) if r['split_group'] != group]
        test = [i for i,r in enumerate(rows) if r['split_group'] == group]
        if {rows[i]['label'] for i in train} != {0,1}: raise ValueError('Held-out fold lacks a training class')
        yield group, train, test


def fit(x, rows, spec=SPEC):
    x = np.asarray(x, np.float64)
    if x.ndim != 2 or len(x) != len(rows) or not np.isfinite(x).all(): raise ValueError('Finite matching features required')
    y = np.array([r['label'] for r in rows],np.float64)
    weights = sample_weights(rows)
    mean = x.mean(axis=0)  # Only training rows are passed here.
    z = x-mean
    def objective(theta):
        logits = z@theta[:-1]+theta[-1]
        loss = np.dot(weights,np.logaddexp(0,logits)-y*logits)+.5*spec['regularization']*np.dot(theta[:-1],theta[:-1])
        residual = weights*(expit(logits)-y)
        return loss,np.r_[z.T@residual+spec['regularization']*theta[:-1],residual.sum()]
    result = minimize(objective,np.zeros(x.shape[1]+1),jac=True,method='L-BFGS-B',options={'maxiter':250,'ftol':1e-10})
    if not result.success: raise RuntimeError('Candidate head did not converge')
    return {'mean':mean,'weight':result.x[:-1],'bias':np.asarray(result.x[-1]),'iterations':int(result.nit)}


def scores(model,x):
    x = np.asarray(x,np.float64)
    if not np.isfinite(x).all(): raise ValueError('Finite features required')
    return expit((x-model['mean'])@model['weight']+model['bias'])


def decision(score,spec=SPEC):
    if not math.isfinite(float(score)): raise ValueError('Finite score required')
    return 'accept_candidate' if score >= spec['accepted_cutoff'] else 'reject_candidate' if score <= spec['rejected_cutoff'] else 'unknown'


def metrics(rows, values):
    if len(rows) != len(values): raise ValueError('Matching predictions required')
    positive = [(r,float(s)) for r,s in zip(rows,values) if r['label'] == 1]
    negative = [(r,float(s)) for r,s in zip(rows,values) if r['label'] == 0]
    negative_frames = {r['frame_group'] for r,s in negative}
    return {'accepted_positive_boxes':sum(decision(s)=='accept_candidate' for r,s in positive),
            'rejected_positive_boxes':sum(decision(s)=='reject_candidate' for r,s in positive),
            'unclear_positive_boxes':sum(decision(s)=='unknown' for r,s in positive), 'positive_boxes':len(positive),
            'false_accepted_rejected_boxes':sum(decision(s)=='accept_candidate' for r,s in negative),
            'rejected_negative_boxes':sum(decision(s)=='reject_candidate' for r,s in negative),
            'unclear_negative_boxes':sum(decision(s)=='unknown' for r,s in negative), 'negative_boxes':len(negative),
            'negative_reviewed_frames':len(negative_frames),
            'negative_frames_with_any_false_accept':sum(any(r['frame_group']==f and decision(s)=='accept_candidate' for r,s in negative) for f in negative_frames),
            'scope':'reviewed_candidate_boxes_only_not_document_presentation_or_whole_video_accuracy'}
