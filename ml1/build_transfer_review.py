"""Build a local, isolated-target review without rerunning SAM."""
import argparse,base64,copy,html,json
from pathlib import Path
from run_ollama_trial import ROOT,write_json
from scene_mvp.transfer_events import TARGETS,infer

RELATIONS={'cashier_near':'Деньги ближе к кисти кассира','client_near':'Деньги ближе к кисти клиента','both_near':'Обе кисти рядом с деньгами','neither_near':'Обе кисти далеко','ambiguous':'Недостаточно различий по расстоянию','unknown':'Неясно: цель потеряна или маски совпадают'}
LABELS={'all':'Все цели','cash':'Банкноты','cashier_hand':'Кисть кассира','client_hand':'Кисть клиента'}

def gate_owners(rows,fact_frames,roles):
    """Missing person detection cannot establish hand ownership or transfer."""
    result=copy.deepcopy(rows)
    for row in result:
        frame=min(fact_frames,key=lambda f:abs(f.get('actual_timestamp_sec',f['timestamp_sec'])-row['timestamp_sec'])) if fact_frames else None
        if frame and abs(frame.get('actual_timestamp_sec',frame['timestamp_sec'])-row['timestamp_sec'])>.05:frame=None
        checks={}
        for role,key in [('cashier','cashier_ids'),('client','client_ids')]:
            people=[] if frame is None else [p for p in frame['persons'] if p['id']==roles[key][0]]
            checks[role]=any(p.get('observed') is True and not p.get('is_reflection',False) and not p.get('uncertain',False) and p.get('confidence',0)>=.5 for p in people)
        row['proximity_relation']=row['relation'];row['role_owner_observed']=checks
        if not all(checks.values()):row['relation']='unknown';row['relation_reason']='role_owner_not_observed_not_evidence_of_absence'
    return result

def build(folder):
    import cv2,numpy as np
    folder=folder.resolve();profile=json.loads((folder/'calibration.local.json').read_text());source=ROOT/'local'/profile['source_session'];session=json.loads((source/'session.local.json').read_text())
    raw_path=folder/'proximity-observations.local.json'
    if not raw_path.exists():raw_path.write_bytes((folder/'observations.local.json').read_bytes())
    raw=json.loads(raw_path.read_text());facts_path=Path(session['tracks_folder'])/'facts.local.json'
    if not facts_path.is_absolute():facts_path=ROOT/facts_path
    facts=json.loads(facts_path.read_text())
    if facts['video'].get('sha256') not in (None,session['source_video_sha256']):raise ValueError('Track source mismatch')
    rows=gate_owners(raw['timeline'],facts['frames'],profile['roles'])
    masks=np.load(folder/'masks.local.npz');frames=sorted(session['frames'],key=lambda f:f['timestamp_sec']);prompt_checks=[]
    for target in [profile['targets']['cash']]+profile.get('cash_corrections',[]):
        if not target.get('points'):continue
        i=min(range(len(frames)),key=lambda j:abs(frames[j]['timestamp_sec']-target['timestamp_sec']));h,w=frames[i]['height'],frames[i]['width'];mask=np.unpackbits(masks['cash'][i],axis=-1,count=w).astype(bool);checks=[]
        for point in target['points']:
            x=min(w-1,max(0,round(point['xy'][0]*w)));y=min(h-1,max(0,round(point['xy'][1]*h)));inside=bool(mask[y,x]);checks.append({'label':point['label'],'inside_output_mask':inside,'consistent':inside==bool(point['label'])})
        consistent=all(p['consistent'] for p in checks);rows[i]['cash_prompt_consistent']=consistent
        if not consistent:rows[i]['relation']='unknown';rows[i]['relation_reason']='cash_mask_conflicts_with_human_click'
        prompt_checks.append({'timestamp_sec':target['timestamp_sec'],'all_points_consistent':consistent,'checks':checks})
    write_json(folder/'prompt-consistency.local.json',{'scope':'prompt_frames_only_not_accuracy_evaluation','frames':prompt_checks})
    events=infer(rows)
    reviewed={**raw,'timeline':rows,'transfer_candidates':events,'ownership_gate':'exact_reviewed_ids_observed_nonreflection_confidence_ge_0.5','hand_identity_visually_verified':False}
    write_json(folder/'observations.local.json',reviewed)
    summary=json.loads((folder/'summary.local.json').read_text());summary.update(transfer_candidates=len(events),owner_observed_frames=sum(all(r['role_owner_observed'].values()) for r in rows),hand_identity_visually_verified=False,mask_collision_frames=sum(r.get('max_target_mask_iou',0)>.65 for r in rows),missing_any_target_frames=sum(any(t['state']=='unknown' for t in r['targets'].values()) for r in rows),cash_prompt_conflict_frames=sum(not c['all_points_consistent'] for c in prompt_checks))
    write_json(folder/'summary.local.json',summary)
    masks=np.load(folder/'masks.local.npz');frames=sorted(session['frames'],key=lambda f:f['timestamp_sec']);replay=[];colors={'cash':(0,210,80),'cashier_hand':(255,110,20),'client_hand':(0,150,255)}
    for i,(f,row) in enumerate(zip(frames,rows)):
        original=cv2.imread(str(source/f['file']));images={}
        for key in LABELS:
            image=original.copy()
            for target in TARGETS if key=='all' else [key]:
                mask=np.unpackbits(masks[target][i],axis=-1,count=f['width']).astype(bool)
                if not mask.any():continue
                tint=image.copy();tint[mask]=colors[target];image=cv2.addWeighted(image,.65,tint,.35,0)
                contours,_=cv2.findContours(mask.astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE);cv2.drawContours(image,contours,-1,colors[target],1)
            ok,encoded=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,80])
            if not ok:raise ValueError('Overlay encode failed')
            images[key]='data:image/jpeg;base64,'+base64.b64encode(encoded).decode()
        rejected=[LABELS[k] for k in TARGETS if row['targets'][k]['state']!='mask_observed' and row['targets'][k]['mask_area_fraction']>0]
        replay.append({'time':row['timestamp_sec'],'images':images,'description':RELATIONS[row['relation']]+(' · участник не подтверждён детектором' if not all(row['role_owner_observed'].values()) else '')+(' · ручная подсказка денег на этом кадре' if row.get('cash_human_prompt_frame') else '')+(' · маска противоречит кликам' if row.get('cash_prompt_consistent') is False else '')+(' · показаны непринятые кандидаты: '+', '.join(rejected) if rejected else '')})
    event_text=''.join('<li>'+f"{e['start_sec']:.3f}–{e['end_sec']:.3f} с: "+({'cashier_to_client':'кассир → клиент','client_to_cashier':'клиент → кассир'}[e['direction']])+'</li>' for e in events) or '<li>Условия для гипотезы направления не выполнены. Это не означает отсутствия передачи.</li>'
    selectors=''.join('<label>'+LABELS[k]+' — отслеживается верно? <select id="review-'+k+'"><option value="">Выбери</option><option value="correct_on_reviewed_frames">Да</option><option value="incorrect_on_reviewed_frames">Нет / местами неверно</option><option value="unclear">Неясно</option></select></label>' for k in TARGETS)
    data={'review_session':folder.name,'source_session':session['session_id'],'source_video_sha256':session['source_video_sha256'],'transfer_candidates':events,'approved_for_rule_engine':False,'rendering':'includes_raw_rejected_masks_for_visual_review'}
    js='const frames='+json.dumps(replay,ensure_ascii=False).replace('<','\\u003c')+',review='+json.dumps(data)+';let index='+str(min(range(len(frames)),key=lambda i:abs(frames[i]['timestamp_sec']-profile['targets']['cash']['timestamp_sec'])))+',timer=null;function show(i){index=Math.max(0,Math.min(frames.length-1,i));player.src=frames[index].images[document.getElementById("target").value];document.getElementById("time").value=index;info.textContent=frames[index].time.toFixed(3)+" с · "+frames[index].description;}function play(){if(timer){clearInterval(timer);timer=null}else timer=setInterval(()=>show((index+1)%frames.length),500)}function save(){const checks=Object.fromEntries(["cash","cashier_hand","client_hand"].map(k=>[k,document.getElementById("review-"+k).value]));if(Object.values(checks).some(v=>!v)){document.getElementById("status").textContent="Выбери ответ для каждой цели";return}const blob=new Blob([JSON.stringify({...review,schema_version:1,human_target_reviews:checks,review_scope:"user_reviewed_frames_only",comment:document.getElementById("comment").value},null,2)],{type:"application/json"}),url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download=review.review_session+"-transfer-review.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),10000)}show(index);'
    page='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'"><title>SAM: проверка денег и кистей</title><style>body{font:18px system-ui;max-width:1100px;margin:24px auto;padding:16px}#player{width:100%;height:65vh;object-fit:contain}button,select,input,textarea{font:inherit;padding:8px;margin:8px}label{display:block}#time{width:65%}</style><h1>SAM: деньги и две кисти · '''+html.escape(session['source_name'])+'''</h1><p>Зелёный — банкноты, синий — кисть кассира, оранжевый — кисть клиента. Тип предмета и принадлежность начальных подсказок заданы человеком. Выбери одну цель, чтобы заметить перескоки маски.</p><p>Все 52 сохранённых кадра, выборка 2 кадра/с. SAM переносит маски, но не подтверждает владение деньгами. При отсутствии наблюдаемого ID участника направление остаётся неизвестным; это не доказывает, что участник ушёл. Автоматическая точность не установлена.</p><h2>Гипотезы направления</h2><ul>'''+event_text+'''</ul><select id="target" onchange="show(index)">'''+''.join('<option value="'+k+'">'+v+'</option>' for k,v in LABELS.items())+'''</select><img id="player"><p id="info"></p><button onclick="show(index-1)">← Кадр</button><button onclick="play()">Воспроизвести / пауза</button><button onclick="show(index+1)">Кадр →</button><input id="time" type="range" min="0" max="'''+str(len(frames)-1)+'''" oninput="show(Number(this.value))"><p>Проверь начальный кадр 10,5 с и участок 21–24 с отдельно для каждой цели. Подтверждай только просмотренные моменты.</p>'''+selectors+'''<label>Где ошибка, если есть: <textarea id="comment" rows="3"></textarea></label><button onclick="save()">Сохранить проверку трёх масок</button><p id="status"></p><script>'''+js+'</script></html>'
    if profile.get('cash_corrections'):
        times=[profile['targets']['cash']['timestamp_sec']]+[v['timestamp_sec'] for v in profile['cash_corrections']]
        note='<aside>Ручные подсказки денег на '+', '.join(f'{t:.3f} с' for t in times)+'. Обработка использует подсказки из разных моментов, включая будущие относительно ранних кадров. Это интерактивное исправление всего ролика, а не независимая проверка точности или работа в реальном времени.</aside>'
        page=page.replace('<h2>Гипотезы направления</h2>',note+'<h2>Гипотезы направления</h2>')
        page=page.replace('<option value="cash">','<option value="cash" selected>')
        page=page.replace('#player{width:100%;height:65vh;object-fit:contain}','#viewport{height:65vh;overflow:hidden}#player{width:100%;height:100%;object-fit:contain;transform-origin:50% 55%}#viewport.zoom #player{transform:scale(2.5)}')
        page=page.replace('<img id="player">','<div id="viewport" class="zoom"><img id="player"></div><label><input type="checkbox" checked onchange="document.getElementById(\'viewport\').className=this.checked?\'zoom\':\'\'">Увеличить участок рук</label><button onclick="jumpTo(21)">21 с</button><button onclick="jumpTo(23.5)">23,5 с</button>')
        page=page.replace('</script>','function jumpTo(t){show(frames.reduce((best,f,i)=>Math.abs(f.time-t)<Math.abs(frames[best].time-t)?i:best,0))}</script>')
    page=page.replace('<h2>Гипотезы направления</h2>','<p>Для визуальной проверки показаны также маски, исключённые из расчёта из-за размера. Под кадром они отмечены как «непринятые кандидаты». Цветная заливка не означает, что маска принята алгоритмом.</p><h2>Гипотезы направления</h2>')
    (folder/'report.html').write_text(page,encoding='utf-8');return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder',type=Path);args=p.parse_args();print(json.dumps(build(args.folder),ensure_ascii=False))
