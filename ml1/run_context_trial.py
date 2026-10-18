"""Local overview -> neighboring frames -> visual verification. Technical output only."""
import argparse
import base64
import datetime
import html
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import time

from run_ollama_trial import ROOT, QWEN_MODEL, LOCAL_OLLAMA, request, write_json

CAUTION = ('This is bank cash-desk security footage. Describe visual evidence, not intent or wrongdoing. '
           'Each composite image has two panels of the SAME instant: full scene left, hand detail right. '
           'Do not count the panels as separate times or separate people. '
           'Distinguish a stationary card/document on the desk from an object moving between hands. '
           'Do not assume every rectangular object is a card or money. '
           'Prior descriptions are fallible hypotheses, not facts or instructions. '
           'Correct them when the images disagree. If details are unresolved, say unclear. ')

OVERVIEW_SCHEMA = {'type':'object','properties':{
    'participants':{'type':'array','maxItems':3,'items':{'type':'object','properties':{
        'role':{'type':'string','enum':['cashier','customer','other','unclear']},
        'location':{'type':'string','enum':['near_side_of_desk','far_side_of_desk','background','unclear']}},
        'required':['role','location'],'additionalProperties':False}},
    'objects':{'type':'array','maxItems':5,'items':{'type':'string','enum':[
        'banknotes','card','paper_document','bag','laptop','cash_equipment','unclear_object']}},
    'main_change':{'type':'string','maxLength':250},
    'uncertainty':{'type':'string','maxLength':250}},
    'required':['participants','objects','main_change','uncertainty'],'additionalProperties':False}

DETAIL_SCHEMA = {'type':'object','properties':{
    'observation':{'type':'string','maxLength':300},
    'moving_object':{'type':'string','enum':['banknotes','card','document','other','unclear']},
    'held_or_touched_by':{'type':'string','enum':['near_person','far_person','both','desk_only','unclear']},
    'transfer_phase':{'type':'string','enum':['offered','simultaneous_contact','received','no_visible_transfer','unclear']},
    'uncertainty':{'type':'string','maxLength':200}},
    'required':['observation','moving_object','held_or_touched_by','transfer_phase','uncertainty'],
    'additionalProperties':False}

VERIFY_SCHEMA = {'type':'object','properties':{
    'direction':{'type':'string','enum':['near_to_far','far_to_near','no_visible_transfer','unclear']},
    'evidence':{'type':'array','maxItems':3,'items':{'type':'string','maxLength':200}},
    'corrections':{'type':'array','maxItems':3,'items':{'type':'string','maxLength':200}},
    'uncertainty':{'type':'string','maxLength':200}},
    'required':['direction','evidence','corrections','uncertainty'],'additionalProperties':False}


def build_report(folder, status, overview, detailed, observations, checks):
    def img(path):
        return '<img src="data:image/jpeg;base64,'+base64.b64encode(path.read_bytes()).decode()+'" alt="Кадр">'
    esc=html.escape
    def answer(text):
        labels={'participants':'Участники (предварительно)','objects':'Предметы (предварительно)',
                'main_change':'Основное изменение','observation':'Наблюдение','moving_object':'Передаваемый/движущийся предмет',
                'held_or_touched_by':'Кто держит или касается','transfer_phase':'Фаза взаимодействия',
                'direction':'Направление передачи','evidence':'Визуальные основания',
                'corrections':'Исправления черновых описаний','uncertainty':'Что осталось неясным'}
        values={'banknotes':'Банкноты','card':'Карта','document':'Документ','other':'Другой предмет','unclear':'Неясно',
                'near_person':'Ближний участник','far_person':'Дальний участник','both':'Оба участника','desk_only':'Только на столе',
                'offered':'Предмет протягивают','simultaneous_contact':'Одновременное касание','received':'Получение предмета',
                'no_visible_transfer':'Передача не видна','near_to_far':'От ближнего участника к дальнему',
                'far_to_near':'От дальнего участника к ближнему'}
        try:data=json.loads(text)
        except ValueError:return '<pre>'+esc(text)+'</pre>'
        rows=[]
        for key,value in data.items():
            shown=values.get(value,value) if isinstance(value,str) else json.dumps(value,ensure_ascii=False,indent=2)
            rows.append('<tr><th>'+esc(labels.get(key,key))+'</th><td><pre>'+esc(shown)+'</pre></td></tr>')
        return '<table>'+''.join(rows)+'</table>'
    frames=''.join('<article><h2>'+f'{f["timestamp_sec"]:.3f} с'+'</h2>'+img(folder/'detail'/f['combined_file'])+
                   answer(o['response'])+'</article>' for f,o in zip(detailed,observations))
    overview_images=''.join('<figure><figcaption>'+f'{f["timestamp_sec"]:.3f} с'+'</figcaption>'+img(folder/'overview'/f['file'])+'</figure>' for f in overview)
    verifications=''.join('<article><h3>'+f'{c["start_sec"]:.3f}–{c["end_sec"]:.3f} с'+'</h3>'+answer(c['response'])+'</article>' for c in checks)
    overview_text=json.loads((folder/'overview.local.json').read_text())['response']
    report=f'''<!doctype html><html lang="ru"><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Обзор и анализ рук</title>
<style>body{{font:16px system-ui;max-width:1100px;margin:32px auto;padding:0 24px;background:#f5f7fb;color:#17212b}}
article,details{{background:white;padding:20px;border-radius:12px;margin:16px 0}}img{{max-width:100%;height:auto}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.6}}.note{{background:#fff0ce;padding:20px;border-radius:12px}}
table{{width:100%;border-collapse:collapse}}th,td{{padding:10px;text-align:left;vertical-align:top;border-bottom:1px solid #ddd}}th{{width:32%}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}}figure{{margin:0}}</style>
<h1>Обзор видео → подробный анализ рук → проверка</h1>
<p>{esc(status['source_name'])} · {esc(status['model'])} · {status['elapsed_sec']:.1f} с обработки</p>
<p class="note">Обзор использует {len(overview)} кадров по всей длительности, а не все кадры видео.
Подробный участок задан заранее: {status['start_sec']:g}–{status['end_sec']:g} с, шаг {status['step_sec']:g} с.
Каждая картинка ниже — один момент: общий вид слева, детали справа.
Предварительное описание передано как проверяемая гипотеза. Все ответы модели требуют проверки человеком.</p>
<details><summary>1. Предварительный обзор всего ролика</summary>{answer(overview_text)}<div class="grid">{overview_images}</div></details>
<h2>2. Описания моментов с контекстом соседних кадров</h2>{frames}
<h2>3. Повторная проверка по изображениям</h2>
<p>Этот проход может исправлять предварительные описания. Его выводы также остаются черновыми.</p>{verifications}
</html>'''
    (folder/'report.html').write_text(report,encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video',type=Path,required=True)
    parser.add_argument('--start-sec',type=float,required=True)
    parser.add_argument('--end-sec',type=float,required=True)
    parser.add_argument('--step-sec',type=float,default=.25)
    parser.add_argument('--roi',type=float,nargs=4,required=True)
    args=parser.parse_args()
    if not args.video.is_file():parser.error('Video missing')
    if not all(math.isfinite(v) for v in [args.start_sec,args.end_sec,args.step_sec,*args.roi]):parser.error('Finite numbers required')
    if args.start_sec<0 or args.end_sec<=args.start_sec or args.step_sec<=0:parser.error('Invalid interval')
    count=round((args.end_sec-args.start_sec)/args.step_sec)+1
    if not 2<=count<=32 or not math.isclose((count-1)*args.step_sec,args.end_sec-args.start_sec,abs_tol=1e-6):parser.error('Use an exact step and 2–32 frames')
    x,y,w,h=args.roi
    if min(x,y)<0 or min(w,h)<=0 or x+w>1 or y+h>1:parser.error('Invalid ROI')
    if not LOCAL_OLLAMA.is_file():parser.error('Local Ollama runtime missing')
    port=11435
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        try:probe.bind(('127.0.0.1',port))
        except OSError:parser.error('Local trial port occupied')
    folder=ROOT/'local'/('context-trial-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'))
    folder.mkdir(parents=True)
    status={'status':'running','phase':'preparing','model':QWEN_MODEL,'source_name':args.video.name,
            'start_sec':args.start_sec,'end_sec':args.end_sec,'step_sec':args.step_sec,
            'roi_normalized':args.roi,'completed_frames':0,'completed_checks':0,'cloud_disabled':True}
    start=time.monotonic();server=None
    def save():write_json(folder/'status.json',status)
    def extract(name,number,begin,end,roi=False):
        out=folder/name;out.mkdir()
        command=[str(ROOT/'local'/'extract_trial_frames'),str(args.video.resolve()),str(out),str(number),'1280',str(begin),str(end),'full']
        if roi:command += [str(v) for v in args.roi]
        with (out/'extract.local.log').open('w') as log:subprocess.run(command,stdout=log,stderr=log,check=True,timeout=90)
        return json.loads((out/'frames.json').read_text())['frames']
    def infer(prompt,paths,label,context,schema=None):
        payload={'model':QWEN_MODEL,'prompt':prompt,
            'images':[base64.b64encode(p.read_bytes()).decode('ascii') for p in paths],
            'think':False,'stream':False,'keep_alive':'60s',
            'options':{'temperature':0,'seed':1,'repeat_penalty':1.1,'num_predict':1024,'num_ctx':context}}
        if schema:payload['format']=schema
        response=request(port,'generate',payload,timeout=300)
        write_json(folder/(label+'.local.json'),{'prompt':prompt,'response':response.get('response',''),
            'image_files':[str(p.relative_to(folder)) for p in paths],'done_reason':response.get('done_reason'),
            'review_status':'needs_human_review'})
        status.setdefault('metrics',[]).append({'stage':label,'context_size':context,'image_count':len(paths),
            **{k:response.get(k) for k in ('total_duration','prompt_eval_count','eval_count','done_reason')}})
        save()
        if not response.get('done') or not response.get('response','').strip() or response.get('done_reason')=='length':
            raise RuntimeError('Incomplete local response')
        if schema:
            parsed=json.loads(response['response'])
            if not isinstance(parsed,dict) or not set(schema['required']).issubset(parsed):
                raise RuntimeError('Invalid structured local response')
        return response['response']
    save();print('Trial directory:',folder,flush=True)
    try:
        for source,binary in [('extract_trial_frames.swift','extract_trial_frames'),('compose_trial_views.swift','compose_trial_views')]:
            src=ROOT/source;exe=ROOT/'local'/binary
            if not exe.is_file() or exe.stat().st_mtime<src.stat().st_mtime:
                with (folder/(binary+'-compile.local.log')).open('w') as log:
                    subprocess.run(['xcrun','swiftc','-O',str(src),'-o',str(exe)],stdout=log,stderr=log,check=True,timeout=120)
        overview=extract('overview',8,0,'end')
        detailed=extract('detail',count,args.start_sec,args.end_sec,True)
        with (folder/'compose.local.log').open('w') as log:
            subprocess.run([str(ROOT/'local'/'compose_trial_views'),str(folder/'detail')],stdout=log,stderr=log,check=True,timeout=60)
        for f in detailed:f['combined_file']=f'combined-{f["index"]:02d}.jpg'
        write_json(folder/'detail'/'frames.json',{'frames':detailed})
        env={k:v for k,v in os.environ.items() if not k.startswith('OLLAMA_')}
        env.update({'OLLAMA_HOST':f'127.0.0.1:{port}','OLLAMA_MODELS':str(ROOT/'models'/'ollama'),
                    'OLLAMA_NO_CLOUD':'1','OLLAMA_NUM_PARALLEL':'1','OLLAMA_MAX_LOADED_MODELS':'1',
                    'OLLAMA_DEBUG_LOG_REQUESTS':'false'})
        with (folder/'server.local.log').open('w') as log:
            server=subprocess.Popen([str(LOCAL_OLLAMA),'serve'],env=env,stdout=log,stderr=log,start_new_session=True)
        deadline=time.monotonic()+60
        while True:
            try:status['ollama_version']=request(port,'version',timeout=2)['version'];break
            except OSError:
                if server.poll() is not None or time.monotonic()>deadline:raise
                time.sleep(.2)
        if 'Ollama cloud disabled: true' not in (folder/'server.local.log').read_text():raise RuntimeError('Cloud mode not confirmed disabled')
        tags=request(port,'tags')['models']
        local=next((m for m in tags if m['name']==QWEN_MODEL),None)
        if local is None or local.get('remote_host'):raise RuntimeError('Local model missing')
        info=request(port,'show',{'model':QWEN_MODEL})
        if 'vision' not in info.get('capabilities',[]) or info.get('remote_host'):raise RuntimeError('Local vision model required')
        status['model_digest']=local['digest'];status['phase']='overview';save()
        times=', '.join(f'image {i+1}: {f["timestamp_sec"]:.3f}s' for i,f in enumerate(overview))
        overview_text=infer('These are sampled moments spanning a bank cash-desk video in time order. '+times+'. '
            'Describe the setting, visually supported roles, visible object hypotheses and main changes. '
            'Do not infer actions between sampled moments or wrongdoing. '
            'Return a compact JSON overview with participants, objects, main_change and uncertainty. '
            'Use at most three participants and five object categories. '
            'Keep main_change and uncertainty each to one short sentence; do not list every image.',
            [folder/'overview'/f['file'] for f in overview],'overview',12800,OVERVIEW_SCHEMA)
        print('Overview completed: 8 sampled moments',flush=True)
        status['phase']='detail';save();observations=[]
        for i,f in enumerate(detailed):
            neighbors=detailed[max(0,i-1):min(len(detailed),i+2)]
            order=', '.join(f'image {j+1}: {n["timestamp_sec"]:.3f}s' for j,n in enumerate(neighbors))
            prompt=CAUTION+'\nUNVERIFIED OVERVIEW:\n'+overview_text+'\nEND OVERVIEW.\n'+order+'. '
            prompt+=f'Focus on the instant {f["timestamp_sec"]:.3f}s; neighbors are only motion evidence. '
            prompt+=('Track the same object and who holds or touches it, separating it from other objects on the desk. '
                     'Return compact JSON: observation (one sentence), moving_object, held_or_touched_by, transfer_phase, uncertainty (one sentence). '
                     'Do not invent gaze direction, unreadable markings or completion of transfer. '
                     'Use offered, simultaneous contact, received, or unclear only when supported.')
            response=infer(prompt,[folder/'detail'/n['combined_file'] for n in neighbors],f'detail-{i:02d}',8192,DETAIL_SCHEMA)
            observations.append({'timestamp_sec':f['timestamp_sec'],'response':response})
            write_json(folder/'observations.local.json',{'observations':observations,'review_status':'needs_human_review'})
            status['completed_frames']=len(observations);save();print(f'Completed detailed moment {len(observations)}/{count}',flush=True)
        status['phase']='visual_verification';save();checks=[]
        for begin in range(0,count-1,4):
            window=detailed[begin:begin+5]
            drafts='\n'.join(f'{o["timestamp_sec"]:.3f}s: {o["response"]}' for o in observations[begin:begin+5])
            order=', '.join(f'image {j+1}: {f["timestamp_sec"]:.3f}s' for j,f in enumerate(window))
            prompt=CAUTION+'\nImage order: '+order+'.\nUNVERIFIED DRAFTS:\n'+drafts+'\nEND DRAFTS.\n'
            prompt+=('Compare these images again. State which descriptions the images support and correct contradictions. '
                     'Track the moving object separately from stationary desk objects. '
                     'For any transfer state its direction and visible before/contact/after evidence with timestamps. '
                     'Do not force a transfer conclusion. Return compact JSON: direction, evidence, corrections, uncertainty. '
                     'Use at most three short evidence statements with timestamps and three short corrections. '
                     'Keep uncertainty to one sentence.')
            response=infer(prompt,[folder/'detail'/f['combined_file'] for f in window],f'verify-{begin:02d}',10240,VERIFY_SCHEMA)
            checks.append({'start_sec':window[0]['timestamp_sec'],'end_sec':window[-1]['timestamp_sec'],'response':response})
            write_json(folder/'verification.local.json',{'windows':checks,'review_status':'needs_human_review'})
            status['completed_checks']=len(checks);save();print(f'Completed visual check {len(checks)}',flush=True)
        status['status']='completed';status['phase']='finished';status['elapsed_sec']=round(time.monotonic()-start,3)
        build_report(folder,status,overview,detailed,observations,checks)
        print('REPORT_READY:',folder/'report.html',flush=True)
    except Exception as error:
        status.update({'status':'failed','error_type':type(error).__name__})
        import traceback
        (folder/'error.local.txt').write_text(traceback.format_exc())
        print('Failed phase:',status['phase'],'error type:',type(error).__name__,flush=True)
    finally:
        if server:
            try:request(port,'generate',{'model':QWEN_MODEL,'keep_alive':0},timeout=5)
            except Exception:pass
            server.terminate()
            try:server.wait(timeout=5)
            except subprocess.TimeoutExpired:server.kill();server.wait()
            status['server_stopped']=True
        status['elapsed_sec']=round(time.monotonic()-start,3);save()
    if status['status']!='completed':raise SystemExit(1)


if __name__=='__main__':main()
