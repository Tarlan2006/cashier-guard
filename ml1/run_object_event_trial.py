"""Local SAM tracking -> trained event head -> a self-contained review report."""
import argparse,base64,datetime,hashlib,html,json,subprocess
from pathlib import Path
import numpy as np
from run_ollama_trial import ROOT,write_json
from scene_mvp.engine import validate_profile
from scene_mvp.object_event_model import extract,predict

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def bind_model(profile,model_dir=None):
    binding=profile.get('object_event_check')
    if binding:
        directory=(ROOT/'local'/binding['plan_id']).resolve()
        if not directory.is_relative_to((ROOT/'local').resolve()):raise ValueError('Invalid plan path')
        path=directory/'plan.local.json';plan=json.loads(path.read_text())
        if sha(path)!=binding['sha256'] or plan['source_video_sha256']!=profile['source_video_sha256'] or plan['source_session']!=profile['source_session']:raise ValueError('Frozen check binding mismatch')
        if sha(ROOT/'scene_mvp/object_event_model.py')!=plan['feature_code_sha256'] or sha(ROOT/'run_sam2_object_trial.py')!=plan['sam_code_sha256']:raise ValueError('Inference code changed since check was frozen')
        model_dir=model_dir or directory/'frozen-model'
    else:plan=None;model_dir=model_dir or ROOT/'models/object_event_baseline'
    model_dir=Path(model_dir);meta=json.loads((model_dir/'model-metadata.local.json').read_text());path=model_dir/'object-event-model.npz'
    if meta['schema_version']!='object-event-model/1' or sha(path)!=meta['model_sha256']:raise ValueError('Model weights/version mismatch')
    if plan and meta['model_sha256']!=plan['model_sha256']:raise ValueError('Model differs from frozen check')
    return model_dir,meta

def validate_sam_source(folder,profile):
    saved=json.loads((folder/'calibration.local.json').read_text())
    if saved!=profile:raise ValueError('SAM observations use a different calibration')
    if json.loads((folder/'status.json').read_text())['status']!='completed':raise ValueError('SAM tracking is not completed')
    return json.loads((folder/'observations.local.json').read_text())

def make_report(out,source,session,sam_folder,profile,result,features):
    observations=json.loads((sam_folder/'observations.local.json').read_text());frames=sorted(session['frames'],key=lambda f:f['timestamp_sec']);timeline=observations['timeline'];replay=[]
    if len(frames)!=len(timeline):raise ValueError('Source/SAM timeline length mismatch')
    for i,(f,row) in enumerate(zip(frames,timeline)):
        if abs(f['timestamp_sec']-row['timestamp_sec'])>.001:raise ValueError('Source/SAM timestamps differ')
        path=sam_folder/'overlays'/f'{i:03d}.jpg'
        replay.append({'time':f['timestamp_sec'],'image':'data:image/jpeg;base64,'+base64.b64encode(path.read_bytes()).decode(),'mask':row.get('experimental_object',{}) .get('state','unknown')})
    best=result.get('strongest_window');anchor=profile.get('object_anchor_sec',frames[0]['timestamp_sec']);evidence=[anchor,frames[-1]['timestamp_sec']]+(best['evidence_times_sec'] if best else [])
    unknown=next((r['timestamp_sec'] for r in timeline if r['timestamp_sec']>=anchor and r.get('experimental_object',{}).get('state')!='mask_observed'),None)
    if unknown is not None:evidence.append(unknown)
    indexes=sorted({min(range(len(frames)),key=lambda i:abs(frames[i]['timestamp_sec']-t)) for t in evidence});cards=''.join('<article><h3>'+f"{frames[i]['timestamp_sec']:.3f} с"+'</h3><img src="'+replay[i]['image']+'"><p>'+('Маска получена' if replay[i]['mask']=='mask_observed' else 'Маска неизвестна / потеряна')+'</p></article>' for i in indexes)
    names={'object_left_pattern':'Модель выделила сценарий оставленного предмета','no_object_left_pattern_detected':'Модель не выделила сценарий оставленного предмета',None:'Недостаточно наблюдений для ответа'};score='не вычислялся' if result['video_risk_score'] is None else f"{result['video_risk_score']:.3f}";seen='Это обучающий ролик: запуск проверяет подключение модели, а не перенос на новые данные.' if result['is_training_video'] else 'Этот SHA-256 отсутствует в обучающих роликах. Метка события пока не получена; точность здесь ещё не посчитана.'
    data=json.dumps({'schema_version':1,'review_kind':'object_event_model_review','review_session':out.name,'source_session':session['session_id'],'source_video_sha256':session['source_video_sha256'],'model_sha256':result['model_sha256'],'sam_report':sam_folder.name,'model_prediction':result['prediction'],'model_candidate':result['candidate'],'approved_for_rule_engine':False},ensure_ascii=False).replace('<','\\u003c');images=json.dumps(replay,ensure_ascii=False).replace('<','\\u003c')
    script='const frames='+images+',review='+data+';let index=0,timer=null;const visited=new Set();function show(i){index=Math.max(0,Math.min(frames.length-1,i));visited.add(index);document.getElementById("player").src=frames[index].image;document.getElementById("time").value=index;document.getElementById("info").textContent=frames[index].time.toFixed(3)+" с · "+(frames[index].mask==="mask_observed"?"маска получена":"маска неизвестна")}function play(){if(timer){clearInterval(timer);timer=null}else timer=setInterval(()=>show((index+1)%frames.length),500)}function save(){const mask=document.getElementById("mask-answer").value,event=document.getElementById("event-answer").value,checked=document.getElementById("confirmed").checked;const data={...review,human_mask_review:mask||null,human_event_label:event||null,confirmed:!!(mask&&event&&checked),review_scope:"user_review_of_sampled_timeline_not_all_native_frames",visited_times_sec:[...visited].sort((a,b)=>a-b).map(i=>frames[i].time),all_sampled_frames_visited:visited.size===frames.length,comment:document.getElementById("comment").value};const raw=JSON.stringify(data,null,2);document.getElementById("json").value=raw;const url=URL.createObjectURL(new Blob([raw],{type:"application/json"})),a=document.createElement("a");a.href=url;a.download=review.review_session+"-object-event-review.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);document.getElementById("status").textContent=data.confirmed?"Проверка сохранена. Можно написать в чате: сохранил.":"Черновик сохранён. Для подтверждения выбери два ответа и галочку; файл уже можно прислать для проверки."}show('+str(min(range(len(frames)),key=lambda i:abs(frames[i]['timestamp_sec']-anchor)))+');'
    page='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'"><title>Сумка / документы: применение обученной модели</title><style>body{font:18px system-ui;max-width:1250px;margin:28px auto;padding:18px}aside{background:#fff0ce;padding:18px}#player{width:100%;height:65vh;object-fit:contain}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}article{background:#edf2f8;padding:12px}article img{width:100%}select,input,button,textarea{font:inherit;padding:8px;margin:8px}label{display:block}#time{width:65%}textarea{width:95%}</style><h1>'''+html.escape(session['source_name'])+' · '+('Сумка' if profile['target_object_kind']=='bag' else 'Документы')+'</h1><h2>'+names[result['prediction']]+'</h2><p>Внутренний балл: '+score+'. Это не калиброванная вероятность.</p><aside>'+seen+' Модель обучена всего на четырёх видео. Она ищет сценарий оставленного предмета; другие нарушения не проверяются. Правильность SAM-маски, тип предмета и роль кассира не подтверждаются этим баллом.</aside><p>Рамка и роль заданы человеком. SAM выполнил офлайн-сопровождение с выборкой кадров; затем обученный классификатор обработал его признаки. Пропуски трекинга остаются неизвестными. Модель не переобучалась на этом запуске.</p><p>Совместное наблюдение предмета и кассира: '+f"{features['joint_observed_coverage']:.1%}"+'. Готовых окон: '+str(len(features['windows']))+'.</p><img id="player"><p id="info"></p><button onclick="show(index-1)">←</button><button onclick="play()">Воспроизвести / пауза</button><button onclick="show(index+1)">→</button><input id="time" type="range" min="0" max="'+str(len(frames)-1)+'" oninput="show(Number(this.value))"><details><summary>Опорный кадр, сильнейшее окно, потери и конец ролика</summary><div class="grid">'+cards+'</div></details><label>Маска сумки / документов верна на просмотренных кадрах? <select id="mask-answer"><option value="">Выбери</option><option value="correct_on_reviewed_frames">Да</option><option value="incorrect_on_reviewed_frames">Нет / местами неверно</option><option value="unclear">Неясно</option></select></label><label>Что видно на просмотренной шкале? <select id="event-answer"><option value="">Выбери независимо от ответа модели</option><option value="object_left_pattern">Кассир отошёл, предмет остался</option><option value="object_removed_before_departure">Кассир убрал / унёс предмет перед уходом</option><option value="no_departure_visible">Отхода кассира не видно</option><option value="unclear">Недостаточно данных</option></select></label><label><input id="confirmed" type="checkbox">Проверил просмотренные кадры и подтверждаю выбранные ответы.</label><label>Комментарий: <textarea id="comment" rows="2"></textarea></label><button onclick="save()">Сохранить проверку / черновик</button><p id="status"></p><details><summary>JSON для копирования, если загрузка файла не сработала</summary><textarea id="json" rows="10" readonly></textarea></details><script>'+script+'</script></html>'
    (out/'report.html').write_text(page,encoding='utf-8')

def main():
    p=argparse.ArgumentParser();p.add_argument('--calibration',type=Path,required=True);p.add_argument('--model',type=Path);p.add_argument('--reuse-sam-report',type=Path);args=p.parse_args();profile=json.loads(args.calibration.read_text());validate_profile(profile)
    if not profile['confirmed'] or profile.get('target_object_kind') not in ('bag','documents'):p.error('Confirmed bag/documents calibration required; cash is deferred')
    source=(ROOT/'local'/profile['source_session']).resolve()
    if not source.is_relative_to((ROOT/'local').resolve()):p.error('Local source session required')
    session=json.loads((source/'session.local.json').read_text())
    if session['source_video_sha256']!=profile['source_video_sha256']:p.error('Calibration/source video mismatch')
    model_dir,meta=bind_model(profile,args.model);out=ROOT/'local'/('object-event-prediction-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir();write_json(out/'protocol.local.json',{'source_session':session['session_id'],'source_video_sha256':session['source_video_sha256'],'model_sha256':meta['model_sha256'],'model_directory':str(model_dir),'feature_spec':meta['feature_spec'],'calibration_sha256':sha(args.calibration),'model_retrained':False,'expected_event_label_used':False,'cash_excluded':True,'approved_for_rule_engine':False});write_json(out/'calibration.local.json',profile);write_json(out/'status.json',{'status':'running','phase':'object_tracking'});print('OBJECT_EVENT_TRIAL:',out,flush=True)
    try:
        if args.reuse_sam_report:sam_folder=args.reuse_sam_report.resolve()
        else:
            process=subprocess.Popen([str(ROOT/'local/perception-venv/bin/python'),str(ROOT/'run_sam2_object_trial.py'),'--calibration',str(args.calibration.resolve())],cwd=ROOT.parent,stdout=subprocess.PIPE,text=True);sam_folder=None
            for line in process.stdout:
                print(line,end='',flush=True)
                if line.startswith('SAM2_TRIAL:'):sam_folder=Path(line.split(':',1)[1].strip()).resolve()
            if process.wait()!=0 or sam_folder is None:raise RuntimeError('SAM tracker failed')
        if not sam_folder.is_relative_to((ROOT/'local').resolve()):raise ValueError('Local SAM report required')
        observations=validate_sam_source(sam_folder,profile);features=extract(observations,profile,meta['feature_spec'])
        with np.load(model_dir/'object-event-model.npz',allow_pickle=False) as weights:model={k:weights[k] for k in weights.files}
        result={'schema_version':'object-event-prediction/1','source_video_sha256':profile['source_video_sha256'],'source_session':session['session_id'],'sam_report':sam_folder.name,'object_kind':profile['target_object_kind'],'model_sha256':meta['model_sha256'],'is_training_video':profile['source_video_sha256'] in meta['source_video_sha256'],'joint_observed_coverage':features['joint_observed_coverage'],'valid_windows':len(features['windows']),'mask_human_review_required':True,**predict(model,features,meta['feature_spec'])};write_json(out/'prediction.local.json',result);write_json(out/'features.local.json',features);write_json(out/'sam-reference.local.json',{'path':str(sam_folder),'observations_sha256':sha(sam_folder/'observations.local.json'),'calibration_sha256':sha(sam_folder/'calibration.local.json')});make_report(out,source,session,sam_folder,profile,result,features);write_json(out/'status.json',{'status':'completed','model_retrained':False,'approved_for_rule_engine':False});print('OBJECT_EVENT_REPORT_READY:',out/'report.html',flush=True);print(json.dumps({k:v for k,v in result.items() if k!='window_scores'},ensure_ascii=False),flush=True)
    except Exception as e:write_json(out/'status.json',{'status':'failed','error_type':type(e).__name__,'error':str(e)[:1000],'approved_for_rule_engine':False});raise

if __name__=='__main__':main()
