"""Bind human mask review to one completed cash-tracking run."""
import math


def validate(review,protocol):
    if review.get('schema_version')!='cash-tracking-mask-review/1' or review.get('tracking_session')!=protocol['tracking_session']:
        raise ValueError('Wrong mask review/run')
    if review.get('review_protocol_sha256')!=protocol['review_protocol_sha256']:raise ValueError('Review protocol changed')
    if review.get('confirmed') is not True or review.get('automatic_legal_verdict') is not False:raise ValueError('Confirmed visual mask review required')
    cases=review.get('cases',[]);expected={r['case_id']:r for r in protocol['cases']}
    if len(cases)!=len(expected) or {r['case_id'] for r in cases}!=set(expected):raise ValueError('Exactly one mask review per case required')
    for row in cases:
        source=expected[row['case_id']]
        for field in ['source_video_sha256','result_sha256']:
            if row.get(field)!=source[field]:raise ValueError('Mask review source mismatch')
        if row.get('human_mask_review') not in ['correct_on_reviewed_frames','incorrect_on_reviewed_frames','unclear']:raise ValueError('Mask answer required')
        times=row.get('visited_times_sec',[])
        if not isinstance(times,list) or not times or any(type(t) not in (int,float) or not math.isfinite(t) or not any(abs(t-s)<.001 for s in source['sample_times_sec']) for t in times):raise ValueError('Reviewed times must match actual samples')
        if row.get('review_scope')!='selected_viewed_sampled_frames_not_all_native_frames':raise ValueError('Limited review scope required')
    return review
