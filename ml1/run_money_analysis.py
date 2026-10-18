"""Run local money tracking, then continue after a human mask review."""
import argparse,datetime,json,subprocess,sys
from pathlib import Path
from run_ollama_trial import ROOT,write_json
from scene_mvp.transfer_events import validate,require_two_party_context
from scene_mvp.money_pipeline import frozen_check,check_mask_review,sha
from build_money_review import build

def run(script,args,prefix):
    found=None
    process=subprocess.Popen([sys.executable,str(ROOT/script),*map(str,args)],stdout=subprocess.PIPE,stderr=None,text=True,cwd=ROOT.parent)
    for line in process.stdout:
        print(line,end='',flush=True)
        if line.startswith(prefix):found=Path(line.split(':',1)[1].strip()).resolve()
    if process.wait()!=0:raise RuntimeError('Local subprocess failed: '+script)
    if found is None or not found.is_relative_to((ROOT/'local').resolve()):raise ValueError('Invalid local subprocess output')
    return found

def main():
    p=argparse.ArgumentParser(description=__doc__);group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--calibration',type=Path);group.add_argument('--trial',type=Path)
    p.add_argument('--mask-review',type=Path);args=p.parse_args()
    if args.mask_review and not args.trial:p.error('--mask-review requires --trial')
    if args.calibration:profile=json.loads(args.calibration.read_text())
    else:
        trial=args.trial.resolve()
        if not trial.is_relative_to((ROOT/'local').resolve()):p.error('Local SAM trial required')
        profile=json.loads((trial/'calibration.local.json').read_text())
    source=(ROOT/'local'/profile['source_session']).resolve()
    if not source.is_relative_to((ROOT/'local').resolve()):p.error('Local source session required')
    session=json.loads((source/'session.local.json').read_text());validate(profile,session)
    context=source/'human-scene-context.accepted.local.json'
    require_two_party_context(json.loads(context.read_text()) if context.exists() else None,session)
    check=frozen_check(ROOT,profile)
    out=ROOT/'local'/('money-run-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir()
    write_json(out/'protocol.local.json',check);write_json(out/'calibration.local.json',profile)
    write_json(out/'status.json',{'status':'running','phase':'mask_review' if args.trial else 'tracking'})
    try:
        if args.calibration:
            (source/'transfer-calibration.accepted.local.json').write_text(json.dumps(profile,ensure_ascii=False,indent=2))
            trial=run('run_sam2_transfer_trial.py',['--calibration',args.calibration],'SAM2_TRANSFER_TRIAL:')
        sam_status=json.loads((trial/'status.json').read_text())
        if sam_status['status'] not in ('completed','needs_seed_review'):raise ValueError('SAM tracking has not completed')
        observations=json.loads((trial/'observations.local.json').read_text())
        summary=json.loads((trial/'summary.local.json').read_text())
        motion=None;state='needs_mask_review'
        if args.mask_review:
            raw=args.mask_review.read_bytes();review=json.loads(raw)
            usable=check_mask_review(review,trial.name,profile,observations)
            (trial/'human-transfer-review.original.local.json').write_bytes(raw)
            write_json(trial/'human-transfer-review.accepted.local.json',{**review,'accepted_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'review_sha256':sha(args.mask_review),'whole_video_accuracy_established':False,'approved_for_rule_engine':False})
            if usable and not summary['seed_identity_collision']:
                motion_report=run('run_transfer_motion.py',['--trial',trial],'TRANSFER_MOTION_REPORT:');motion=motion_report.parent;state='needs_direction_review'
            else:state='needs_target_correction'
        page=build(trial,motion)
        result={'status':state,'sam_trial':str(trial),'motion_trial':str(motion) if motion else None,'report':str(page),
                'frozen_check':check,'cash_type_source':'human_seed_not_automatic_classification',
                'legal_violation_label':None,'approved_for_rule_engine':False}
        write_json(out/'result.local.json',result);write_json(out/'status.json',{'status':state})
        write_json(ROOT/'local/money-current.local.json',{'run':str(out),**result})
        print('MONEY_REVIEW_READY:',page);print(json.dumps(result,ensure_ascii=False))
    except Exception as e:
        write_json(out/'status.json',{'status':'failed','error_type':type(e).__name__,'error':str(e)[:1000]});raise

if __name__=='__main__':main()
