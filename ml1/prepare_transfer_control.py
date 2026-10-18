"""Freeze the transfer experiment before collecting visual prompts on another clip."""
import argparse,base64,datetime,hashlib,json,shutil
from pathlib import Path
from run_ollama_trial import ROOT,write_json
from run_transfer_motion import PROTOCOL
from scene_mvp.transfer_events import require_two_party_context

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--session',type=Path,required=True);p.add_argument('--development-review',type=Path,required=True);p.add_argument('--initial-sec',type=float,default=0);args=p.parse_args();source=args.session.resolve()
    if not source.is_relative_to((ROOT/'local').resolve()):p.error('Local source required')
    session=json.loads((source/'session.local.json').read_text());development=json.loads(args.development_review.read_text())
    context_path=source/'human-scene-context.accepted.local.json'
    require_two_party_context(json.loads(context_path.read_text()) if context_path.exists() else None,session)
    if session['source_video_sha256']==development['source_video_sha256']:p.error('Different video SHA required')
    facts_path=Path(session['tracks_folder'])/'facts.local.json';facts=json.loads(facts_path.read_text());reflections={r['id'] for r in facts.get('reflection_tracks',[]) if r.get('is_reflection')}
    ids=sorted({p['id'] for f in facts['frames'] for p in f['persons'] if p['id'] not in reflections and not p.get('is_reflection',False)})
    if len(ids)<2:p.error('Two real participant tracks required for this trial')
    out=ROOT/'local'/('transfer-control-plan-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir()
    files=['run_sam2_transfer_trial.py','scene_mvp/segmentation_prompts.py','scene_mvp/transfer_events.py','build_transfer_review.py','run_transfer_motion.py','scene_mvp/transfer_motion.py']
    hashes={name:sha(ROOT/name) for name in files}
    for name in files:
        target=out/'frozen-code'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,target)
    runtime=json.loads((ROOT/'local/runtime/sam2-runtime.local.json').read_text())
    plan={'schema_version':1,'plan_id':out.name,'source_session':session['session_id'],'source_video_sha256':session['source_video_sha256'],'development_video_sha256':development['source_video_sha256'],'source_is_different_video':True,'scope':'transfer_method_check_on_different_video_same_camera','prior_use':'previous_object_tracking_control_not_globally_unseen','motion_parameters':PROTOCOL,'code_sha256':hashes,'sam_source_revision':runtime['source_revision'],'sam_weights_sha256':runtime['weights_sha256'],'visual_prompts_collected_after_freeze':True,'expected_direction_supplied':False,'direction_labels_used':False,'automatic_roles_confirmed':False,'blinded_ground_truth_required_for_accuracy_claim':True,'approved_for_rule_engine':False}
    write_json(out/'plan.local.json',plan);binding={'plan_id':out.name,'sha256':sha(out/'plan.local.json')}
    frames=[]
    for f in session['frames']:
        path=(source/f['file']).resolve()
        if not path.is_relative_to(source):p.error('Frame outside source')
        nearest=min(facts['frames'],key=lambda x:abs(x.get('actual_timestamp_sec',x['timestamp_sec'])-f['timestamp_sec']))
        # Cached JPEG extraction can differ from detector samples by two native frames.
        # This tolerance is only for displaying ID boxes; inference thresholds stay frozen.
        offset=nearest.get('actual_timestamp_sec',nearest['timestamp_sec'])-f['timestamp_sec']
        if abs(offset)>.1:p.error('Facts timestamps differ')
        persons=[{k:p.get(k) for k in ('id','bbox','observed','is_reflection')} for p in nearest['persons'] if p['id'] not in reflections]
        frames.append({k:f[k] for k in ('timestamp_sec','width','height')}|{'persons':persons,'id_box_timestamp_offset_sec':offset,'image':'data:image/jpeg;base64,'+base64.b64encode(path.read_bytes()).decode()})
    payload={'frames':frames,'source_name':session['source_name'],'session_id':session['session_id'],'source_video_sha256':session['source_video_sha256'],'candidate_ids':ids,'initial_frame_index':min(range(len(frames)),key=lambda i:abs(frames[i]['timestamp_sec']-args.initial_sec)),'validation_plan':binding}
    output=source/'transfer-control-two-click.html';output.write_text((ROOT/'scene_mvp/transfer_control.html').read_text().replace('__PAYLOAD__',json.dumps(payload,ensure_ascii=False).replace('<','\\u003c')),encoding='utf-8');write_json(out/'ui.local.json',{'page':str(output),'candidate_ids':ids,'source_session':session['session_id']})
    print('TRANSFER_CONTROL_READY:',output);print(json.dumps({'plan_id':out.name,'frames':len(frames),'candidate_ids':ids,'source_video_sha256':session['source_video_sha256'],'expected_direction_used':False}))

if __name__=='__main__':main()
