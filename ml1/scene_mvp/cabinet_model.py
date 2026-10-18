"""Strict binding of user-labeled cabinet states, separate from entrance-door data."""
from scene_mvp.engine import validate_profile

TARGET='cash_storage_cabinet'

def validate_fixture_data(profile,session):
    validate_profile(profile)
    if profile.get('profile_kind')!='fixture_only' or profile.get('fixture_kind')!=TARGET or not profile['confirmed']:
        raise ValueError('Confirmed cabinet-only profile required')
    if session.get('target_kind')!=TARGET or session['source_video_sha256']!=profile['source_video_sha256'] or session['session_id']!=profile['source_session']:
        raise ValueError('Cabinet calibration/session mismatch')
    frames={round(f['timestamp_sec'],3) for f in session['frames']}
    if len(frames)!=len(session['frames']):raise ValueError('Duplicate sampled timestamps')
    labels={}
    for row in profile.get('fixture_frame_labels',[]):
        t=round(row['timestamp_sec'],3)
        if t in labels or t not in frames or row.get('source')!='human_frame_label' or row['state'] not in ('open','closed','unknown'):
            raise ValueError('Invalid cabinet label')
        labels[t]=row['state']
    if set(labels)!=frames:raise ValueError('All sampled cabinet frames must be labeled, including unknown')
    return labels
