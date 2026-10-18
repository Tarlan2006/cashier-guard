"""Local motion experiment on saved masks; does not modify strict SAM results."""
import argparse,base64,datetime,hashlib,html,json
from pathlib import Path
from run_ollama_trial import ROOT,write_json
from scene_mvp.transfer_motion import infer_motion
from scene_mvp.transfer_events import TARGETS

PROTOCOL={'version':'transfer-motion-experiment/1','minimum_mask_pixels':16,'minimum_relative_to_seed_area':.1,'maximum_relative_to_seed_area':8,'near_distance_relative_to_cash':.2,'exclusive_other_hand_distance':.5,'max_mask_iou':.65,'max_cash_step_relative_to_size':4,'max_sample_gap_sec':.75,'stable_exclusive_sec':.5,'max_transition_sec':3.,'min_displacement_relative_to_object':.25,'max_owner_missing_samples':1,'requires_observed_two_hand_contact':True,'expected_direction_used':False,'missing_samples_interpolated':False,'independent_evaluation':False,'approved_for_rule_engine':False}
NAMES={'cashier_near':'Деньги ближе к кисти кассира','client_near':'Деньги ближе к кисти клиента','both_near':'Обе кисти рядом с деньгами','unknown':'Неясно','ambiguous':'Недостаточно различий по расстоянию','neither_near':'Кисти далеко от денег'}

def main():
    import cv2,numpy as np
    p=argparse.ArgumentParser();p.add_argument('--trial',type=Path,required=True);args=p.parse_args();trial=args.trial.resolve()
    if not trial.is_relative_to((ROOT/'local').resolve()):p.error('Local source required')
    profile=json.loads((trial/'calibration.local.json').read_text());review_path=trial/'human-transfer-review.accepted.local.json';review=json.loads(review_path.read_text());old=json.loads((trial/'observations.local.json').read_text());summary=json.loads((trial/'summary.local.json').read_text())
    if review['review_session']!=trial.name or review['source_video_sha256']!=profile['source_video_sha256'] or review['source_session']!=profile['source_session'] or review['review_scope']!='user_reviewed_frames_only':p.error('Review binding mismatch')
    if any(review['human_target_reviews'].get(k)!='correct_on_reviewed_frames' for k in TARGETS):p.error('Targets need visual correction first')
    source=ROOT/'local'/profile['source_session'];session=json.loads((source/'session.local.json').read_text());frames=sorted(session['frames'],key=lambda f:f['timestamp_sec']);h,w=frames[0]['height'],frames[0]['width'];total=h*w
    out=ROOT/'local'/('transfer-motion-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir()
    protocol={**PROTOCOL,'source_trial':trial.name,'source_video_sha256':profile['source_video_sha256'],'review_sha256':hashlib.sha256(review_path.read_bytes()).hexdigest(),'source_masks_sha256':hashlib.sha256((trial/'masks.local.npz').read_bytes()).hexdigest(),'review_scope':'user_reviewed_frames_only_not_all_frames','seed_frames_used_in_same_video':True,'native_size':[w,h]}
    # Save settings before evaluating this development video.
    write_json(out/'protocol.local.json',protocol)
    initial={k:[summary['initialization'][k]['mask_area_fraction']*total] for k in TARGETS}
    initial['cash'] += [v['mask_area_fraction']*total for v in summary.get('cash_correction_seeds',[])]
    limits={k:{'min_pixels':max(PROTOCOL['minimum_mask_pixels'],min(initial[k])*PROTOCOL['minimum_relative_to_seed_area']),'max_pixels':max(initial[k])*PROTOCOL['maximum_relative_to_seed_area']} for k in TARGETS}
    protocol['area_limits']=limits;write_json(out/'protocol.local.json',protocol)
    with np.load(trial/'masks.local.npz') as z:tracks={k:np.unpackbits(z[k],axis=-1,count=w).astype(bool) for k in TARGETS}
    if any(m.shape!=(len(frames),h,w) for m in tracks.values()):raise ValueError('Mask/frame mismatch')
    rows=[];previous=None
    for i,(f,prior) in enumerate(zip(frames,old['timeline'])):
        if abs(f['timestamp_sec']-prior['timestamp_sec'])>.001:raise ValueError('Timestamp mismatch')
        row={'timestamp_sec':f['timestamp_sec'],'relation':'unknown','reason':None,'targets':{},'role_owner_observed':prior['role_owner_observed'],'all_masks_usable':False,'cash_motion_continuous':False,'cash_prompt_frame':prior.get('cash_human_prompt_frame',False)};valid={}
        for k in TARGETS:
            m=tracks[k][i];area=int(m.sum());usable=limits[k]['min_pixels']<=area<=limits[k]['max_pixels'];box=None
            if m.any():
                yy,xx=np.nonzero(m);box=[int(xx.min()),int(yy.min()),int(xx.max()+1),int(yy.max()+1)]
            row['targets'][k]={'mask_pixels':area,'usable':usable,'bbox_px':box}
            if usable:valid[k]=m
        row['all_masks_usable']=len(valid)==3
        cash=row['targets']['cash']
        if cash['usable']:
            b=cash['bbox_px'];row['cash_center_px']=[(b[0]+b[2])/2,(b[1]+b[3])/2];row['cash_diagonal_px']=float(np.hypot(b[2]-b[0],b[3]-b[1]));row['cash_motion_continuous']=True
            if previous and previous['targets']['cash']['usable']:
                step=float(np.linalg.norm(np.array(row['cash_center_px'])-previous['cash_center_px'])/max(1,(row['cash_diagonal_px']+previous['cash_diagonal_px'])/2));row['cash_step_relative_to_size']=step;row['cash_motion_continuous']=step<=PROTOCOL['max_cash_step_relative_to_size']
        if len(valid)==3:
            ious=[float(np.count_nonzero(valid[a]&valid[b])/max(1,np.count_nonzero(valid[a]|valid[b]))) for j,a in enumerate(TARGETS) for b in TARGETS[j+1:]];row['max_mask_iou']=max(ious)
            if max(ious)>PROTOCOL['max_mask_iou']:row['reason']='mask_identity_collision'
            elif prior.get('cash_prompt_consistent') is False:row['reason']='human_prompt_conflict'
            elif not row['cash_motion_continuous']:row['reason']='object_position_jump'
            else:
                distances={k:float(cv2.distanceTransform((~valid[k]).astype(np.uint8),cv2.DIST_L2,3)[valid['cash']].min()/max(1,row['cash_diagonal_px'])) for k in ('cashier_hand','client_hand')};row['hand_distance_relative_to_cash']=distances;a,b=distances['cashier_hand'],distances['client_hand'];near=PROTOCOL['near_distance_relative_to_cash'];far=PROTOCOL['exclusive_other_hand_distance'];rel='both_near' if a<=near and b<=near else 'cashier_near' if a<=near and b>=far else 'client_near' if b<=near and a>=far else 'neither_near' if a>=far and b>=far else 'ambiguous';row['raw_proximity_relation']=rel
                if not all(row['role_owner_observed'].values()):row['reason']='role_owner_not_observed'
                else:row['relation']=rel
        else:row['reason']='missing_or_out_of_scale_mask'
        rows.append(row);previous=row
    events=infer_motion(rows,PROTOCOL)
    output={'schema_version':'transfer-motion-experiment/1','source_trial':trial.name,'source_session':profile['source_session'],'source_video_sha256':profile['source_video_sha256'],'roles':profile['roles'],'timeline':rows,'transfer_candidates':events,'strict_method_candidates':len(old['transfer_candidates']),'independent_evaluation':False,'status':'experimental_review_only','is_legal_verdict':False,'approved_for_rule_engine':False}
    write_json(out/'motion-observations.local.json',output)
    result={'frames':len(rows),'candidates':len(events),'directions':[e['direction'] for e in events],'candidate_intervals':[[e['start_sec'],e['end_sec']] for e in events],'unknown_frames':sum(r['relation']=='unknown' for r in rows),'strict_method_candidates':len(old['transfer_candidates']),'independent_evaluation':False,'approved_for_rule_engine':False};write_json(out/'summary.local.json',result)
    cards=[];colors={'cash':(0,210,80),'cashier_hand':(255,110,20),'client_hand':(0,150,255)}
    for n,event in enumerate(events):
        indexes=[i for i,r in enumerate(rows) if event['start_sec']<=r['timestamp_sec']<=event['end_sec']];images=[]
        for i in indexes:
            image=cv2.imread(str(source/frames[i]['file']))
            for k in TARGETS:
                mask=tracks[k][i];tint=image.copy();tint[mask]=colors[k];image=cv2.addWeighted(image,.7,tint,.3,0);contours,_=cv2.findContours(mask.astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE);cv2.drawContours(image,contours,-1,colors[k],1)
            # Same camera ROI as the human annotation UI. Display only; analysis used original masks.
            image=image[round(.33*h):round(.70*h),round(.22*w):round(.75*w)];ok,enc=cv2.imencode('.jpg',image)
            if not ok:raise ValueError('Image encoding failed')
            uri='data:image/jpeg;base64,'+base64.b64encode(enc).decode();r=rows[i];reason=' · ID участника не наблюдается; направление здесь неизвестно' if r['reason']=='role_owner_not_observed' else ''
            images.append('<article><h3>'+f"{r['timestamp_sec']:.3f} с"+'</h3><img src="'+uri+'"><p>'+NAMES[r['relation']]+reason+'</p></article>')
        title='кассир → клиент' if event['direction']=='cashier_to_client' else 'клиент → кассир';uncertainty=', '.join(str(t) for t in event['uncertain_times_sec']) or 'нет'
        cards.append('<section><h2>Гипотеза '+str(n+1)+': '+title+' · '+f"{event['start_sec']:.3f}–{event['end_sec']:.3f} с"+'</h2><p>Неопределённые моменты: '+uncertainty+'. Позиции и владельцы на них не восстанавливались.</p><div class="grid">'+''.join(images)+'</div><label>Что происходит на самом деле? <select id="answer-'+str(n)+'"><option value="">Выбери после просмотра</option><option value="cashier_to_client">Кассир передаёт деньги клиенту</option><option value="client_to_cashier">Клиент передаёт деньги кассиру</option><option value="no_transfer">Передачи нет</option><option value="unclear">Неясно</option></select></label></section>')
    table='<table><tr><th>Время, с</th><th>Наблюдение</th><th>Деньги, пиксели</th><th>Неопределённость</th></tr>'+''.join('<tr><td>'+str(r['timestamp_sec'])+'</td><td>'+NAMES[r['relation']]+'</td><td>'+str(r['targets']['cash']['mask_pixels'])+'</td><td>'+html.escape(r['reason'] or '')+'</td></tr>' for r in rows)+'</table>'
    data=json.dumps({'schema_version':1,'review_kind':'transfer_direction_review','review_session':out.name,'source_trial':trial.name,'source_session':profile['source_session'],'source_video_sha256':profile['source_video_sha256'],'transfer_candidates':events,'approved_for_rule_engine':False}).replace('<','\\u003c')
    script='const review='+data+';function save(){const answers=review.transfer_candidates.map((e,i)=>({...e,human_direction:document.getElementById("answer-"+i).value}));if(answers.some(a=>!a.human_direction)){document.getElementById("status").textContent="Проверь каждую гипотезу";return}const blob=new Blob([JSON.stringify({...review,human_event_reviews:answers,review_scope:"displayed_candidate_intervals_only",reviewed_at:new Date().toISOString()},null,2)],{type:"application/json"}),url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download=review.review_session+"-direction-review.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),10000)}'
    page='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'"><title>Передача денег: проверка движения</title><style>body{font:18px system-ui;max-width:1450px;margin:25px auto;padding:18px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px}article{background:#edf2f8;padding:12px}img{width:100%}select,button{font:inherit;padding:10px;margin:12px}table{border-collapse:collapse;width:100%}td,th{padding:8px;border:1px solid #ccd}aside{background:#fff0ce;padding:18px}</style><h1>Деньги: движение от одной кисти к другой</h1><aside>Это эксперимент на том же ролике после ручной проверки и исправления масок. Порог размера изменён относительно опорных масок; разрешён один кадр с потерянным ID внутри передачи, при сохранённых масках и кадре с близостью обеих кистей к деньгам. Пропуск остаётся неизвестным. Это настройка на данном видео, а не независимая оценка точности. SAM заново не запускался. Передача денег сама по себе не является нарушением.</aside><p>Зелёный — банкноты, синий — кисть кассира, оранжевый — кисть клиента. Правильное направление в расчёт не передавалось. Строгий предыдущий алгоритм остаётся без изменений.</p>'''+(''.join(cards) if cards else '<p>Гипотезы передачи не выделены; смотри временную шкалу ниже.</p>')+('<button onclick="save()">Сохранить проверку направления</button><p id="status"></p>' if cards else '')+'<details><summary>Временная шкала всех кадров</summary>'+table+'</details><script>'+script+'</script></html>'
    (out/'report.html').write_text(page,encoding='utf-8');print('TRANSFER_MOTION_REPORT:',out/'report.html');print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
