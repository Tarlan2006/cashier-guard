"""Prepare local cash-only correction; keep human-reviewed hand prompts."""
import argparse,base64,hashlib,json
from pathlib import Path
from run_ollama_trial import ROOT,write_json
from scene_mvp.transfer_events import validate

def main():
    p=argparse.ArgumentParser();p.add_argument('--trial',type=Path,required=True);args=p.parse_args();trial=args.trial.resolve()
    if not trial.is_relative_to((ROOT/'local').resolve()):p.error('Local trial required')
    base=json.loads((trial/'calibration.local.json').read_text());review_path=trial/'human-transfer-review.accepted.local.json';review=json.loads(review_path.read_text());source=ROOT/'local'/base['source_session'];session=json.loads((source/'session.local.json').read_text());validate(base,session)
    if review['review_session']!=trial.name or review['source_video_sha256']!=base['source_video_sha256'] or review['source_session']!=base['source_session']:p.error('Review source mismatch')
    if any(review['human_target_reviews'].get(k)!='correct_on_reviewed_frames' for k in ('cashier_hand','client_hand')):p.error('Hand prompts need review')
    frames=[]
    for f in session['frames']:
        path=(source/f['file']).resolve()
        if not path.is_relative_to(source.resolve()):p.error('Frame outside source')
        frames.append({k:f[k] for k in ('timestamp_sec','width','height')}|{'image':'data:image/jpeg;base64,'+base64.b64encode(path.read_bytes()).decode()})
    payload={'base':base,'frames':frames,'source_session':base['source_session'],'source_name':session['source_name'],'review_binding':{'review_session':trial.name,'accepted_review_sha256':hashlib.sha256(review_path.read_bytes()).hexdigest(),'scope':'user_reviewed_frames_only'}}
    output=trial/'correct-cash-two-click.html';output.write_text((ROOT/'scene_mvp/cash_correction.html').read_text().replace('__PAYLOAD__',json.dumps(payload,ensure_ascii=False).replace('<','\\u003c')))
    write_json(trial/'cash-correction-plan.local.json',{'source_session':base['source_session'],'review_binding':payload['review_binding'],'expected_direction_used':False,'hand_prompts_reused':True,'required_cash_frames':2,'point_prompts':'human_positive_and_negative','independent_evaluation':False})
    print('CASH_CORRECTION_READY:',output)

if __name__=='__main__':main()
