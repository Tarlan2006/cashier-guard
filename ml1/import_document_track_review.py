"""Archive sampled-clip mask feedback without promoting it to ID verification."""
import argparse,datetime,hashlib,json
from pathlib import Path
from run_ollama_trial import ROOT,write_json
ACTION_VALUES={'lifted_or_held_in_hand','passed_between_people','lying_on_desk','lying_on_desk_only','other','unclear'}


def validate_actions(actions):
    if not isinstance(actions,list) or any(not isinstance(a,str) or a not in ACTION_VALUES for a in actions) or len(set(actions))!=len(actions):
        raise ValueError('Unique action labels required')
    return list(actions)


def actions_from_review(review):
    if review.get('schema_version')==2:return validate_actions(review.get('human_observed_actions'))
    value=review.get('human_observed_motion')
    if value is not None and value not in ACTION_VALUES:raise ValueError('Unknown motion answer')
    return [value] if value is not None else []


def apply_clarification(accepted,clarification,original_sha):
    if clarification.get('original_review_sha256')!=original_sha or clarification.get('source_video_sha256')!=accepted['source_video_sha256']:
        raise ValueError('Clarification must bind to original review and video')
    evidence=clarification.get('evidence',{})
    if evidence.get('kind')!='explicit_user_chat_statement' or not isinstance(evidence.get('quote'),str) or not evidence['quote'].strip():
        raise ValueError('Explicit human clarification evidence required')
    actions=validate_actions(clarification.get('human_observed_actions'))
    if not set(accepted['human_observed_actions']).issubset(actions):raise ValueError('This clarification may add compatible actions, not erase the original answer')
    kind=clarification.get('human_claimed_object_kind')
    if kind not in {None,'document','identity_document'}:raise ValueError('Unknown human object claim')
    return {**accepted,'human_observed_actions':actions,'human_claimed_object_kind':kind,'human_chat_clarification':clarification,
            'action_label_scope':'whole_reviewed_clip_human_observation','frame_accurate_action_intervals':False,
            'transfer_direction':'unknown_not_annotated','automatic_identity_document_recognition_established':False}


def validate(review,protocol,trial_name,protocol_sha):
    if review.get('schema_version') not in {1,2} or review.get('review_kind')!='reviewed_document_track_review' or review.get('review_session')!=trial_name:
        raise ValueError('Wrong review/session')
    if review.get('protocol_sha256')!=protocol_sha or any(review.get(k)!=protocol[k] for k in ['source_session','source_video_sha256']):
        raise ValueError('Wrong source/protocol')
    if review.get('confirmed') is not True or review.get('approved_for_rule_engine') is not False or review.get('identity_verification_established') is not False:
        raise ValueError('Confirmed limited-scope mask review required')
    if review.get('review_scope')!='user_reviewed_sampled_clip_frames_only':raise ValueError('Wrong review scope')
    if review.get('human_mask_review') not in ['correct_on_reviewed_frames','incorrect_on_reviewed_frames','unclear']:raise ValueError('Unknown mask answer')
    actions_from_review(review)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--trial',type=Path,required=True);parser.add_argument('--review',type=Path,required=True)
    parser.add_argument('--clarification',type=Path)
    args=parser.parse_args();trial=args.trial.resolve()
    if not trial.is_relative_to((ROOT/'local').resolve()):parser.error('Local tracking trial required')
    raw=args.review.read_bytes();review=json.loads(raw);protocol_path=trial/'protocol.local.json';protocol=json.loads(protocol_path.read_text())
    try:validate(review,protocol,trial.name,hashlib.sha256(protocol_path.read_bytes()).hexdigest())
    except ValueError as error:parser.error(str(error))
    original_sha=hashlib.sha256(raw).hexdigest()
    accepted={**review,'review_sha256':hashlib.sha256(raw).hexdigest(),'accepted_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'all_native_frames_verified':False,'all_clip_masks_verified':False,'document_absence_validated':False,
        'physical_identity_document_type_established':False,'legal_violation_label':None,
        'human_observed_actions':actions_from_review(review),'action_label_scope':'whole_reviewed_clip_human_observation',
        'frame_accurate_action_intervals':False,'transfer_direction':'unknown_not_annotated',
        'automatic_identity_document_recognition_established':False}
    if args.clarification:
        clarification_raw=args.clarification.read_bytes()
        try:accepted=apply_clarification(accepted,json.loads(clarification_raw),original_sha)
        except ValueError as error:parser.error(str(error))
        (trial/'human-chat-clarification.original.local.json').write_bytes(clarification_raw)
    (trial/'human-track-review.original.local.json').write_bytes(raw)
    write_json(trial/'human-track-review.accepted.local.json',accepted)
    pointer=ROOT/'local/document-tracking-current.local.json';current=json.loads(pointer.read_text())
    if Path(current['trial']).resolve()==trial:write_json(pointer,{**current,'status':'human_clip_review_recorded','human_mask_review':review['human_mask_review'],
        'human_observed_actions':accepted['human_observed_actions'],'human_claimed_object_kind':accepted.get('human_claimed_object_kind'),
        'identity_verification_established':False})
    print('DOCUMENT_TRACK_REVIEW_IMPORTED:',trial)
    print(json.dumps({'human_mask_review':review['human_mask_review'],'human_observed_actions':accepted['human_observed_actions'],
                     'identity_verification_established':False}))


if __name__=='__main__':main()
