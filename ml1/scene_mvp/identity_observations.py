"""Validate human visual observations without converting absence into ID failure."""
import math
from scene_mvp.engine import valid_box

def validate_identity_review(review,protocol,protocol_sha256,session_frames):
    if review.get('schema_version')!='identity-observation-review/1' or review.get('review_session')!=protocol['review_session']:
        raise ValueError('Wrong identity review/session')
    if review.get('protocol_sha256')!=protocol_sha256 or review.get('confirmed') is not True:
        raise ValueError('Wrong protocol or unconfirmed draft')
    if review.get('automatic_legal_verdict') is not False or review.get('face_recognition_used') is not False:
        raise ValueError('Visual review cannot establish identity or legal verdict')
    expected={c['session_id']:c for c in protocol['cases']};seen=set();result=[]
    if len(review.get('cases',[]))!=len(expected):raise ValueError('Wrong case count')
    for case in review['cases']:
        sid=case.get('source_session');source=expected.get(sid)
        if source is None or sid in seen or case.get('source_video_sha256')!=source['sha256']:raise ValueError('Wrong/duplicate video binding')
        seen.add(sid)
        if case.get('confirmed') is not True or case.get('complete_operation_visible') not in {'yes','no','unclear'}:
            raise ValueError('Human procedure scope required')
        observation=case.get('physical_document_observation')
        if observation not in {'presentation_seen','already_present','not_observed','unclear'}:raise ValueError('Unknown physical-document observation')
        if case.get('possible_device_use') not in {'possible_device_use','not_observed','unknown'}:raise ValueError('Unknown device observation')
        if case.get('identity_verification_status')!='unknown_no_bank_record' or case.get('legal_violation_label') is not None:
            raise ValueError('No identity-verification or violation verdict from video alone')
        if case.get('frame_accurate_boundaries') is not False or case.get('review_scope')!='human_review_of_native_video_and_optional_sampled_frame_box':
            raise ValueError('Wrong temporal review scope')
        span=case.get('presentation_window_sec')
        if observation=='presentation_seen':
            if not isinstance(span,list) or len(span)!=2 or any(type(t) not in (int,float) or not math.isfinite(t) for t in span) or not 0<=span[0]<=span[1]<=source['duration_sec']:
                raise ValueError('Presentation window outside video')
        elif span is not None:raise ValueError('Presentation interval supplied without observed presentation')
        seed=case.get('document_seed')
        if seed:
            valid_box(seed['bbox'])
            if seed.get('object_kind') not in {'human_confirmed_identity_document','card_like_unknown','other_document'} or seed.get('source')!='human_box_on_visible_object':
                raise ValueError('Human object-type provenance required')
            t=seed.get('timestamp_sec')
            if type(t) not in (int,float) or not math.isfinite(t) or not any(abs(t-f['timestamp_sec'])<.001 for f in session_frames[sid]):
                raise ValueError('Document seed must match a cached source frame')
        result.append({**case,'operation_context':source['operation_context'],'label_source':'human_visual_review',
                       'split_group':source['sha256'],'automatic_identity_failure_detected':False,
                       'legal_violation_label':None,'identity_verification_status':'unknown_no_bank_record',
                       'external_verification_record_required':True,'approved_for_rule_engine':False})
    return result
