"""Separate local review channel: never relabel inference as human evidence."""
import hashlib,json,math
from pathlib import Path


def infer(session, source, profile, model_dir, weights_dir):
    import cv2,numpy as np
    from scene_mvp.neural_features import FrozenDoorFeatures
    from scene_mvp.door_model import score,classify,FEATURE_SPEC
    if not profile['confirmed'] or 'door_zone' not in profile['zones']:
        raise ValueError('Confirmed door zone required for experimental inference')
    model_dir=Path(model_dir).resolve()
    meta=json.loads((model_dir/'model-metadata.local.json').read_text())
    digest=hashlib.sha256((model_dir/'door-model.npz').read_bytes()).hexdigest()
    if digest!=meta['model_sha256']:raise ValueError('Door model digest mismatch')
    if meta['feature_spec']['score_cutoff']!=FEATURE_SPEC['score_cutoff']:raise ValueError('Threshold mismatch')
    extractor=FrozenDoorFeatures(weights_dir)
    if any(meta['feature_spec'].get(k)!=v for k,v in extractor.spec.items()):
        raise ValueError('Feature specification mismatch')
    model=dict(np.load(model_dir/'door-model.npz',allow_pickle=False))
    source=Path(source).resolve();features=[]
    for f in session['frames']:
        path=(source/f['file']).resolve()
        if not path.is_relative_to(source):raise ValueError('Frame outside session')
        image=cv2.imread(str(path))
        if image is None:raise ValueError('Missing cached frame')
        h,w=image.shape[:2];b=profile['zones']['door_zone']
        bounds=[math.floor(b[0]*w),math.floor(b[1]*h),math.ceil(b[2]*w),math.ceil(b[3]*h)]
        crop=image[bounds[1]:bounds[3],bounds[0]:bounds[2]]
        if min(crop.shape[:2])<8:raise ValueError('Door crop too small')
        features.append(extractor.feature(crop))
    scores=score(model,features)
    observations={round(f['timestamp_sec'],3):{'state':s,'source':'experimental_door_classifier',
                  'model_sha256':digest,'uncalibrated_open_score':float(v)}
                  for f,s,v in zip(session['frames'],classify(scores),scores)}
    return observations,{'model_sha256':digest,'feature_spec':meta['feature_spec'],
        'approved_for_rule_engine':False,'used_human_door_labels':False,
        'video_seen_in_training':session['source_video_sha256'] in {s['sha256'] for s in meta['source_profiles']}}


def attach_review(result, observations, stability=1., max_gap=1.):
    """Keep ordinary signals and human door channel intact; add experimental data."""
    if result['status']!='partial':raise ValueError('Confirmed partial scene required')
    for row in result['timeline']:
        d=observations.get(round(row['timestamp_sec'],3),{'state':'unknown','source':'not_observed'})
        if d['state'] not in ('open','closed','unknown'):raise ValueError('Invalid state')
        if d['state']!='unknown' and d.get('source')!='experimental_door_classifier':raise ValueError('Wrong experimental source')
        row['experimental_door']=dict(d)
    runs=[];active=[]
    for i,row in enumerate(result['timeline']):
        okay=row['cashier_presence']=='away_observed' and row['departure_supported'] and row['experimental_door']['state']=='open'
        if active and (not okay or row['timestamp_sec']-result['timeline'][active[-1]]['timestamp_sec']>max_gap):
            runs.append(active);active=[]
        if okay:active.append(i)
    if active:runs.append(active)
    signals=[]
    for run in runs:
        first,last=(result['timeline'][run[k]] for k in (0,-1))
        if last['timestamp_sec']-first['timestamp_sec']<stability:continue
        signals.append({'type':'door_open_while_cashier_away','start_sec':first['timestamp_sec'],'end_sec':last['timestamp_sec'],
            'evidence_times_sec':list(dict.fromkeys([result['timeline'][max(0,run[0]-1)]['timestamp_sec'],first['timestamp_sec'],last['timestamp_sec']])),
            'participant_ids':sorted({actor for i in run for actor in result['timeline'][i]['cashier_ids']}),
            'status':'experimental_review_candidate','source':'experimental_door_classifier',
            'rule_id':None,'legal_violation_established':False,'approved_for_rule_engine':False,
            'explanation':'Модель предполагает открытую дверь одновременно с наблюдаемым отходом кассира. Проверь кадры: возможны ошибки двери и трекинга.'})
    result['experimental_signals']=signals
    result['coverage']['experimental_door_observed_frames']=sum(r['experimental_door']['state']!='unknown' for r in result['timeline'])
    return result
