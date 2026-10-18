"""Local reusable mask/direction review with a sampled full-video player."""
import base64,html,json
from pathlib import Path
from run_ollama_trial import ROOT

TARGETS=('cash','cashier_hand','client_hand')
LABELS={'all':'Все маски','cash':'Банкноты','cashier_hand':'Кисть кассира','client_hand':'Кисть клиента'}
COLORS={'cash':(0,210,80),'cashier_hand':(255,110,20),'client_hand':(0,150,255)}

def build(trial,motion=None):
    import cv2,numpy as np
    profile=json.loads((trial/'calibration.local.json').read_text())
    session=json.loads((ROOT/'local'/profile['source_session']/'session.local.json').read_text())
    source=ROOT/'local'/profile['source_session'];frames=sorted(session['frames'],key=lambda f:f['timestamp_sec'])
    observations=json.loads((trial/'observations.local.json').read_text())
    summary=json.loads((trial/'summary.local.json').read_text())
    motion_data=json.loads((motion/'motion-observations.local.json').read_text()) if motion else None
    rows=motion_data['timeline'] if motion else observations['timeline']
    if len(rows)!=len(frames):raise ValueError('Money review timeline length mismatch')
    replay=[]
    with np.load(trial/'masks.local.npz') as packed:
        for i,(f,row) in enumerate(zip(frames,rows)):
            if abs(f['timestamp_sec']-row['timestamp_sec'])>.001:raise ValueError('Money review timestamp mismatch')
            masks={k:np.unpackbits(packed[k][i],axis=-1,count=f['width']).astype(bool) for k in TARGETS}
            original=cv2.imread(str(source/f['file']));images={}
            for key in LABELS:
                image=original.copy()
                for k in TARGETS if key=='all' else [key]:
                    m=masks[k]
                    if not m.any():continue
                    tint=image.copy();tint[m]=COLORS[k];image=cv2.addWeighted(image,.7,tint,.3,0)
                    contours,_=cv2.findContours(m.astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
                    cv2.drawContours(image,contours,-1,COLORS[k],1)
                ok,encoded=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,80])
                if not ok:raise ValueError('Money review image encode failed')
                images[key]='data:image/jpeg;base64,'+base64.b64encode(encoded).decode()
            replay.append({'time':f['timestamp_sec'],'images':images,'relation':row['relation'],
                           'unknown_reason':row.get('reason') or row.get('relation_reason'),
                           'targets':row['targets']})
    events=(motion_data or observations)['transfer_candidates']
    record={'schema_version':1,'review_kind':'transfer_direction_review' if motion else 'transfer_mask_review',
            'review_session':(motion or trial).name,'source_session':profile['source_session'],
            'source_video_sha256':profile['source_video_sha256'],'source_trial':trial.name,
            'transfer_candidates':events,'approved_for_rule_engine':False}
    payload={'frames':replay,'review':record,'direction_mode':bool(motion),
             'initial_index':min(range(len(frames)),key=lambda i:abs(frames[i]['timestamp_sec']-profile['targets']['cash']['timestamp_sec']))}
    selects=''
    if motion:
        for i,e in enumerate(events):
            name='кассир → клиент' if e['direction']=='cashier_to_client' else 'клиент → кассир'
            gap_note=('<p>Потеря маски банкнот: '+', '.join(f'{t:.3f} с' for t in e['missing_cash_times_sec'])+'. Непрерывность предмета не подтверждена.</p>') if e.get('missing_cash_times_sec') else ''
            selects+='<article><h3>'+f"{e['start_sec']:.3f}–{e['end_sec']:.3f} с"+'</h3><p>Гипотеза: '+name+'</p>'+gap_note+'<button onclick="jump('+str(e['start_sec'])+')">Начало окна</button><label>Что происходит? <select id="answer-'+str(i)+'"><option value="">Выбери</option><option value="cashier_to_client">Кассир передаёт банкноты клиенту</option><option value="client_to_cashier">Клиент передаёт банкноты кассиру</option><option value="no_transfer">Передачи нет</option><option value="unclear">Неясно</option></select></label></article>'
        if not events:selects='<p>Условия для гипотезы передачи не выполнены. Это не доказывает отсутствие передачи; проверь шкалу и потери масок.</p>'
        selects+='''<h3>Добавить эпизод, который алгоритм не предложил</h3><p>Поставь начало и конец по шкале выше. Это приблизительное окно по сохранённым кадрам.</p><label>Начало, с: <input id="start-sec" type="number" min="0" step="0.1"><button onclick="document.getElementById('start-sec').value=frames[index].time">Текущий кадр — начало</button></label><label>Конец, с: <input id="end-sec" type="number" min="0" step="0.1"><button onclick="document.getElementById('end-sec').value=frames[index].time">Текущий кадр — конец</button></label><select id="manual-direction"><option value="">Что происходит?</option><option value="cashier_to_client">Кассир передаёт банкноты клиенту</option><option value="client_to_cashier">Клиент передаёт банкноты кассиру</option><option value="no_transfer">Передачи в этом окне нет</option><option value="unclear">Неясно</option></select><button onclick="addManual()">Добавить окно</button><button onclick="manual.pop();renderManual()">Удалить последнее окно</button><div id="manual-list"></div>'''
    else:
        for k in TARGETS:selects+='<label>'+LABELS[k]+' — маска верна на просмотренных кадрах? <select id="review-'+k+'"><option value="">Выбери</option><option value="correct_on_reviewed_frames">Да</option><option value="incorrect_on_reviewed_frames">Нет / местами неверно</option><option value="unclear">Неясно</option></select></label>'
    template='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'"><title>Деньги: проверка</title><style>body{font:18px system-ui;max-width:1150px;margin:25px auto;padding:18px}aside{background:#fff0ce;padding:16px}#viewport{height:64vh;overflow:hidden}#player{width:100%;height:100%;object-fit:contain;transform-origin:50% 55%}#viewport.zoom #player{transform:scale(2.5)}select,button,input,textarea{font:inherit;padding:8px;margin:8px}#time{width:60%}textarea{width:95%}label{display:block}article{background:#edf2f8;padding:12px;margin:12px 0}</style>
<h1>__TITLE__</h1><aside>Тип банкнот и роли заданы человеком. SAM отслеживает три подсказки отдельно. Цветом показаны и маски, отклонённые расчётом: заливка не подтверждает правильность. Обрабатывается выборка всей длительности, не каждый исходный кадр; анализ офлайн, с подсказками из разных моментов.</aside>
<p>__COUNT__ сохранённых кадров. Кассир: ID __CASHIER__, клиент: ID __CLIENT__. Зелёный — банкноты, синий — кисть кассира, оранжевый — кисть клиента. Увеличение помогает просмотреть исходные пиксели, но не восстанавливает детали.</p>
<select id="target" onchange="show(index)">__OPTIONS__</select><label><input type="checkbox" checked onchange="document.getElementById('viewport').className=this.checked?'zoom':''">Увеличить участок рук</label><div id="viewport" class="zoom"><img id="player"></div><p id="info"></p><p id="quality"></p><button onclick="show(index-1)">← Кадр</button><button onclick="play()">Воспроизвести / пауза</button><button onclick="show(index+1)">Кадр →</button><input id="time" type="range" min="0" max="__MAX__" oninput="show(Number(this.value))">
<h2>__HEADING__</h2>__SELECTS__<label>Комментарий / пропущенный эпизод и время: <textarea id="comment" rows="3"></textarea></label><label><input id="confirmed" type="checkbox">Подтверждаю выбранные ответы по просмотренным моментам.</label><button onclick="save()">Сохранить проверку / черновик</button><p id="status"></p><details><summary>JSON, если файл не скачивается</summary><textarea id="json" rows="10" readonly></textarea></details>
<p>Близость масок не доказывает владение. Потери целей сохраняются как неопределённость. Передача денег сама по себе не является нарушением. Проверка предложенных окон не измеряет пропущенные события по всему видео.</p>
<script>
const payload=__PAYLOAD__,frames=payload.frames,review=payload.review,$=id=>document.getElementById(id),visited={all:new Set(),cash:new Set(),cashier_hand:new Set(),client_hand:new Set()},manual=[];let index=payload.initial_index,timer=null;
function show(i){index=Math.max(0,Math.min(frames.length-1,i));const f=frames[index],target=$('target').value;visited[target].add(index);$('player').src=f.images[target];$('time').value=index;$('info').textContent=f.time.toFixed(3)+' с · '+(index+1)+'/'+frames.length+' · '+f.relation;$('quality').textContent=(f.unknown_reason?'Неопределённость: '+f.unknown_reason+'. ':'')+Object.entries(f.targets).map(([k,v])=>k+': '+(v.state|| (v.usable?'маска допущена':'маска неизвестна / отклонена'))).join(' · ')}
function jump(t){show(frames.reduce((best,f,i)=>Math.abs(f.time-t)<Math.abs(frames[best].time-t)?i:best,0))}
function play(){if(timer){clearInterval(timer);timer=null}else timer=setInterval(()=>show((index+1)%frames.length),500)}
function renderManual(){const labels={cashier_to_client:'кассир → клиент',client_to_cashier:'клиент → кассир',no_transfer:'передачи нет',unclear:'неясно'};$('manual-list').textContent=manual.map(e=>e.start_sec+'–'+e.end_sec+' с: '+labels[e.human_direction]).join('; ');$('confirmed').checked=false}
function addManual(){const start=Number($('start-sec').value),end=Number($('end-sec').value),label=$('manual-direction').value;if(!$('start-sec').value||!$('end-sec').value||!Number.isFinite(start)||!Number.isFinite(end)||start<frames[0].time||end>frames[frames.length-1].time||end<=start||!['cashier_to_client','client_to_cashier','no_transfer','unclear'].includes(label)){$('status').textContent='Укажи начало и конец внутри сохранённой шкалы, конец позже начала, и выбери действие.';return}if(manual.some(e=>e.start_sec===start&&e.end_sec===end&&e.human_direction===label)){$('status').textContent='Такое окно уже добавлено.';return}manual.push({start_sec:start,end_sec:end,human_direction:label,source:'human_selected_sampled_timeline_window',frame_accurate_boundaries:false});renderManual();$('status').textContent='Окно добавлено. Затем сохрани проверку.'}
function save(){const data={...review,comment:$('comment').value,reviewed_at:new Date().toISOString(),sampled_frames_not_all_native_frames:true,visited_times_by_view:Object.fromEntries(Object.entries(visited).map(([k,v])=>[k,[...v].sort((a,b)=>a-b).map(i=>frames[i].time)]))};let complete=false;if(payload.direction_mode){data.human_event_reviews=review.transfer_candidates.map((e,i)=>({...e,human_direction:$('answer-'+i).value}));data.human_additional_event_reviews=manual;data.review_scope=manual.length?'sampled_timeline_human_windows_and_candidate_intervals':'displayed_candidate_intervals_only';complete=(data.human_event_reviews.length>0||manual.length>0)&&data.human_event_reviews.every(e=>e.human_direction)}else{data.human_target_reviews=Object.fromEntries(['cash','cashier_hand','client_hand'].map(k=>[k,$('review-'+k).value]));data.review_scope='user_reviewed_frames_only';complete=Object.values(data.human_target_reviews).every(Boolean)}data.confirmed=!!(complete&&$('confirmed').checked);const raw=JSON.stringify(data,null,2);$('json').value=raw;const url=URL.createObjectURL(new Blob([raw],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download=review.review_session+(payload.direction_mode?'-direction-review':'-transfer-review')+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);$('status').textContent=data.confirmed?'Проверка сохранена.':'Черновик сохранён. Заполни ответы и подтверждение для продолжения.'}
$('target').value='cash';show(index);
</script></html>'''
    replacements={'__TITLE__':html.escape(session['source_name'])+(' · направление передачи' if motion else ' · банкноты и кисти'),
                  '__COUNT__':str(len(frames)),'__CASHIER__':str(profile['roles']['cashier_ids'][0]),'__CLIENT__':str(profile['roles']['client_ids'][0]),
                  '__MAX__':str(len(frames)-1),'__OPTIONS__':''.join('<option value="'+k+'">'+v+'</option>' for k,v in LABELS.items()),
                  '__HEADING__':'Проверка направления' if motion else 'Проверка трёх масок','__SELECTS__':selects,
                  '__PAYLOAD__':json.dumps(payload,ensure_ascii=False).replace('<','\\u003c')}
    for key,value in replacements.items():template=template.replace(key,value)
    path=(motion or trial)/'money-review.html';path.write_text(template,encoding='utf-8')
    return path
