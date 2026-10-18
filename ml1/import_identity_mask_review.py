"""Record human mask quality without treating tracking as identity verification."""
import argparse,datetime,hashlib,json
from pathlib import Path
from run_ollama_trial import ROOT,write_json

def main():
    p=argparse.ArgumentParser();p.add_argument('--review',type=Path,required=True);p.add_argument('--trial',type=Path,required=True);args=p.parse_args();trial=args.trial.resolve()
    if not trial.is_relative_to((ROOT/'local').resolve()):p.error('Local document tracking trial required')
    raw=args.review.read_bytes();review=json.loads(raw);protocol=json.loads((trial/'protocol.local.json').read_text())
    if review.get('schema_version')!=1 or review.get('review_kind')!='identity_mask_review' or review.get('review_session')!=trial.name:p.error('Wrong mask review/session')
    if any(review.get(k)!=protocol[k] for k in ('source_session','source_video_sha256')):p.error('Wrong source video')
    if review.get('confirmed') is not True or review.get('review_scope')!='user_reviewed_sampled_frames_only' or review.get('approved_for_rule_engine') is not False:p.error('Confirmed limited-scope human review required')
    label=review.get('human_mask_review')
    if label not in {'correct_on_reviewed_frames','incorrect_on_reviewed_frames','unclear'}:p.error('Unknown mask answer')
    (trial/'human-mask-review.original.local.json').write_bytes(raw)
    accepted={**review,'review_sha256':hashlib.sha256(raw).hexdigest(),'accepted_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'all_native_frames_verified':False,'document_absence_detection_validated':False,'identity_verification_established':False,'legal_violation_label':None}
    write_json(trial/'human-mask-review.accepted.local.json',accepted)
    print('IDENTITY_MASK_REVIEW_IMPORTED:',trial);print(json.dumps({'human_mask_review':label,'source_video_sha256':protocol['source_video_sha256'],'identity_verification_established':False}))

if __name__=='__main__':main()
