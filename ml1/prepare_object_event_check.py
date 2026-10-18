"""Prepare a new bag/documents trial with frozen event model and two-click calibration."""
import argparse,datetime,hashlib,json,shutil,subprocess,sys
from pathlib import Path
from run_ollama_trial import ROOT,write_json

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--session',type=Path,required=True);p.add_argument('--kind',choices=['bag','documents'],required=True);p.add_argument('--reference-calibration',type=Path);p.add_argument('--model',type=Path,default=ROOT/'models/object_event_baseline');p.add_argument('--initial-sec',type=float,default=0);args=p.parse_args();source=args.session.resolve()
    if not source.is_relative_to((ROOT/'local').resolve()):p.error('Local source required')
    session=json.loads((source/'session.local.json').read_text());meta=json.loads((args.model/'model-metadata.local.json').read_text());weights=args.model/'object-event-model.npz'
    if sha(weights)!=meta['model_sha256']:p.error('Model weights changed')
    if session['source_video_sha256'] in meta['source_video_sha256']:p.error('Choose a video outside model training groups')
    plan=ROOT/'local'/('object-event-check-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));plan.mkdir();(plan/'frozen-model').mkdir()
    for name in ('object-event-model.npz','model-metadata.local.json'):shutil.copy2(args.model/name,plan/'frozen-model'/name)
    shutil.copy2(ROOT/'scene_mvp/object_event_model.py',plan/'object_event_model.snapshot.py')
    data={'schema_version':1,'plan_id':plan.name,'source_session':session['session_id'],'source_video_sha256':session['source_video_sha256'],'model_sha256':meta['model_sha256'],'feature_code_sha256':sha(ROOT/'scene_mvp/object_event_model.py'),'sam_code_sha256':sha(ROOT/'run_sam2_object_trial.py'),'feature_spec':meta['feature_spec'],'expected_event_label':None,'expected_event_times_sec':None,'ground_truth_not_derived_from_organizer_violation_label':True,'source_not_in_training':True,'object_kind_proposal':args.kind,'confirmed_visual_input':False,'approved_for_rule_engine':False};write_json(plan/'plan.local.json',data)
    command=[sys.executable,str(ROOT/'prepare_object_scene.py'),'--session',str(source),'--kind',args.kind]
    if args.reference_calibration:command+=['--reference-calibration',str(args.reference_calibration)]
    subprocess.run(command,check=True,cwd=ROOT.parent)
    page=(source/'object-calibrate.html').read_text();page=page.replace('обведи предмет заново','задай рамку предмета двумя кликами');page=page.replace('обведи его плотно','задай плотную рамку двумя кликами');page=page.replace('иначе обведи','иначе задай рамку');page=page.replace('max-height:65vh','max-height:none;height:auto;width:620px')
    page=page.replace('<canvas id="canvas">','<p id="clickHint" style="font-weight:650">Рамка задаётся двумя отдельными кликами по противоположным углам. Тянуть мышь не нужно.</p><canvas id="canvas">')
    initial=min(range(len(session['frames'])),key=lambda i:abs(session['frames'][i]['timestamp_sec']-args.initial_sec));binding={'plan_id':plan.name,'sha256':sha(plan/'plan.local.json')}
    extra='''
canvas.onpointerdown=null;canvas.onpointermove=null;canvas.onpointerup=null;
canvas.onmousemove=e=>{if(!begin||!ready)return;const q=point(e);preview=[Math.min(begin[0],q[0]),Math.min(begin[1],q[1]),Math.max(begin[0],q[0]),Math.max(begin[1],q[1])];draw()};
canvas.onclick=e=>{if(!ready)return;const q=point(e);if(!begin){begin=q;$('clickHint').textContent='Теперь кликни по противоположному углу выбранной зоны.';return}const b=[Math.min(begin[0],q[0]),Math.min(begin[1],q[1]),Math.max(begin[0],q[0]),Math.max(begin[1],q[1])];begin=null;preview=null;if((b[2]-b[0])*canvas.width<3||(b[3]-b[1])*canvas.height<3){$('status').textContent='Рамка слишком мала';draw();return}const k=$('zone').value;if(k==='ignore_zone')(zones[k]??=[]).push(b);else zones[k]=b;if(k==='object_zone')objectAnchorSec=frames[index].timestamp_sec;$('verified').checked=false;persist();draw();$('clickHint').textContent='Рамка сохранена. Проверь ID кассира, синюю рабочую зону и поставь подтверждение внизу.'};
$('zone').onchange=()=>{begin=null;preview=null;$('clickHint').textContent='Кликни по первому углу выбранной зоны.';draw()};
$('cashier').oninput=()=>{$('verified').checked=false;persist()};
const originalEventExportData=exportData;
exportData=function(confirmed){originalEventExportData(confirmed)};
'''
    # Bind the exported profile to the frozen test plan without touching inference settings.
    page=page.replace("profile_scope:'this_video_only',",'object_event_check:'+json.dumps(binding)+",profile_scope:'this_video_only',")
    page=page.replace('</script>',extra+'\nshow('+str(initial)+');</script>');output=source/'object-event-calibrate-two-click.html';output.write_text(page,encoding='utf-8');write_json(plan/'ui.local.json',{'path':str(output),'source_session':session['session_id']});print('OBJECT_EVENT_CHECK_READY:',output);print(json.dumps({'plan_id':plan.name,'frames':len(session['frames']),'object_kind':args.kind,'expected_label':None,'source_not_in_training':True}))

if __name__=='__main__':main()
