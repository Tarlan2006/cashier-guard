"""Object-only SAM trial from a human document seed; no people or identity inference."""
import argparse,base64,datetime,hashlib,html,json,os,sys,time
from pathlib import Path
os.environ.update(HF_HUB_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',PYTORCH_ENABLE_MPS_FALLBACK='1')
from run_ollama_trial import ROOT,write_json
from scene_mvp.engine import valid_box

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--review',type=Path,required=True);p.add_argument('--source-session',required=True);args=p.parse_args()
    review_path=args.review.resolve()
    if not review_path.is_relative_to((ROOT/'local').resolve()):p.error('Local accepted human review required')
    accepted=json.loads(review_path.read_text());reference_path=review_path.parent/'protocol.local.json'
    if accepted['protocol_sha256']!=sha(reference_path):p.error('Original review protocol changed')
    references=json.loads(reference_path.read_text());cases=[c for c in accepted['accepted_observations'] if c['source_session']==args.source_session]
    if accepted.get('confirmed') is not True or len(cases)!=1:p.error('One accepted human source required')
    case=cases[0];seed=case.get('document_seed')
    if not seed or seed.get('source')!='human_box_on_visible_object':p.error('Human visible-object seed required; cannot prompt an absent document')
    reference=[r for r in references['cases'] if r['session_id']==args.source_session and r['sha256']==case['source_video_sha256']]
    if len(reference)!=1:p.error('Review source binding changed')
    source=(ROOT/'local'/args.source_session).resolve()
    if not source.is_relative_to((ROOT/'local').resolve()):p.error('Local session required')
    session=json.loads((source/'session.local.json').read_text());frames=sorted(session['frames'],key=lambda f:f['timestamp_sec'])
    if session['source_video_sha256']!=case['source_video_sha256'] or sha(Path(session['source_video']))!=case['source_video_sha256']:p.error('Source video changed')
    box=valid_box(seed['bbox']);anchor=min(range(len(frames)),key=lambda i:abs(frames[i]['timestamp_sec']-seed['timestamp_sec']))
    if abs(frames[anchor]['timestamp_sec']-seed['timestamp_sec'])>.001:p.error('Seed must match source frame')
    runtime=json.loads((ROOT/'local/runtime/sam2-runtime.local.json').read_text());weights=Path(runtime['weights_path'])
    if sha(weights)!=runtime['weights_sha256']:p.error('SAM weights changed')
    out=ROOT/'local'/('identity-sam2-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir();(out/'video_frames').mkdir();(out/'overlays').mkdir()
    protocol={'source_session':args.source_session,'source_video_sha256':case['source_video_sha256'],'human_seed':seed,
              'human_type_claim':seed['object_kind'],'human_presentation_window_sec':case['presentation_window_sec'],
              'accepted_review_sha256':sha(review_path),'runner_sha256':sha(Path(__file__)),'runtime':runtime,'full_video_sampled':True,'native_frames_all_processed':False,
              'bidirectional_offline_tracking':True,'people_or_roles_required':False,'face_recognition_used':False,
              'automatic_identity_document_classification':False,'identity_verification_established':False,
              'mask_loss_is_absence_evidence':False,'legal_violation_label':None}
    write_json(out/'protocol.local.json',protocol);write_json(out/'status.json',{'status':'running','phase':'loading'});print('IDENTITY_SAM_TRIAL:',out,flush=True)
    sys.path.insert(0,str(ROOT/'local/runtime/edgetam-deps'));sys.path.insert(0,runtime['source_path'])
    import cv2,numpy as np,torch
    from sam2.build_sam import build_sam2_video_predictor
    from sam2.sam2_image_predictor import SAM2ImagePredictor
    torch.set_num_threads(2);device='mps' if torch.backends.mps.is_available() else 'cpu';started=time.monotonic();h,w=frames[0]['height'],frames[0]['width']
    try:
        for i,f in enumerate(frames):
            path=(source/f['file']).resolve()
            if not path.is_relative_to(source):raise ValueError('Frame outside source')
            if sha(path)!=reference[0]['frame_sha256'][f['file']]:raise ValueError('Cached frame changed after human review')
            os.link(path,out/'video_frames'/f'{i:05d}.jpg')
        model=build_sam2_video_predictor('configs/sam2.1/sam2.1_hiera_t.yaml',str(weights),device=device,apply_postprocessing=False)
        masks={}
        with torch.inference_mode():
            x1,y1,x2,y2=[max(0,round((box[0]-.1)*w)),max(0,round((box[1]-.1)*h)),min(w,round((box[2]+.1)*w)),min(h,round((box[3]+.1)*h))]
            image=cv2.imread(str(source/frames[anchor]['file']));ok,encoded=cv2.imencode('.jpg',image[y1:y2,x1:x2])
            if not ok:raise ValueError('Seed crop encode failed')
            crop=cv2.imdecode(encoded,cv2.IMREAD_COLOR);image_model=SAM2ImagePredictor(model);image_model.set_image(cv2.cvtColor(crop,cv2.COLOR_BGR2RGB))
            crop_box=np.array([box[0]*w-x1,box[1]*h-y1,box[2]*w-x1,box[3]*h-y1],np.float32)
            options,scores,_=image_model.predict(box=crop_box,multimask_output=True);best=int(np.argmax(scores));initial=np.zeros((h,w),bool);initial[y1:y2,x1:x2]=options[best].astype(bool)
            area=int(initial.sum());box_area=(box[2]-box[0])*w*(box[3]-box[1])*h
            if not 16<=area<=4*box_area:raise ValueError('Seed mask too small or too broad; needs a human point/corrected box')
            write_json(out/'seed.local.json',{'timestamp_sec':frames[anchor]['timestamp_sec'],'mask_pixels':area,'human_box_pixels':box_area,
                         'sam_score_uncalibrated':float(scores[best]),'candidate_type_human_confirmed_not_model_classified':True,'crop_px':[x1,y1,x2,y2]})
            image_model.reset_predictor();del image_model
            state=model.init_state(str(out/'video_frames'),offload_video_to_cpu=True,offload_state_to_cpu=True);model.add_new_mask(state,frame_idx=anchor,obj_id=1,mask=initial)
            for reverse in (False,True):
                for i,_,logits in model.propagate_in_video(state,start_frame_idx=anchor,reverse=reverse):
                    masks[i]=(logits[0,0]>0).cpu().numpy()
                    if len(masks)%10==0:
                        print('DOCUMENT_TRACKED:',len(masks),'/',len(frames),flush=True)
                        write_json(out/'status.json',{'status':'running','phase':'tracking','frames':len(masks),'total_frames':len(frames),'device':device})
            del state
        limits={'min_pixels':max(16,area*.1),'max_pixels':area*8};rows=[];replay=[]
        for i,f in enumerate(frames):
            m=masks.get(i,np.zeros((h,w),bool));n=int(m.sum());usable=limits['min_pixels']<=n<=limits['max_pixels'];bbox=None
            image=cv2.imread(str(source/f['file']))
            if m.any():
                yy,xx=np.nonzero(m);bbox=[float(xx.min()/w),float(yy.min()/h),float((xx.max()+1)/w),float((yy.max()+1)/h)]
                tint=image.copy();tint[m]=(0,210,80);image=cv2.addWeighted(image,.7,tint,.3,0)
            state_name='mask_candidate' if usable else 'unknown_mask_lost' if not n else 'unknown_mask_size_rejected'
            row={'timestamp_sec':f['timestamp_sec'],'state':state_name,'bbox':bbox,'mask_pixels':n,'usable_geometry':usable,
                 'object_identity_verified':False,'document_absence_established':False};rows.append(row)
            name=f'overlays/{i:03d}.jpg';cv2.imwrite(str(out/name),image);replay.append({'time':f['timestamp_sec'],'image':'data:image/jpeg;base64,'+base64.b64encode((out/name).read_bytes()).decode(),'state':state_name})
        np.savez_compressed(out/'masks.local.npz',document=np.packbits(np.array([masks.get(i,np.zeros((h,w),bool)) for i in range(len(frames))]),axis=-1))
        write_json(out/'observations.local.json',{'source_session':args.source_session,'source_video_sha256':case['source_video_sha256'],'timeline':rows,'human_review_required':True,'legal_violation_label':None})
        result={'frames':len(frames),'mask_candidate_frames':sum(r['usable_geometry'] for r in rows),'unknown_frames':sum(not r['usable_geometry'] for r in rows),
                'anchor_sec':frames[anchor]['timestamp_sec'],'elapsed_sec':round(time.monotonic()-started,2),'device':device,'identity_verification_established':False}
        write_json(out/'summary.local.json',result);write_json(out/'status.json',{'status':'completed','human_mask_review_required':True})
        review={'schema_version':1,'review_kind':'identity_mask_review','review_session':out.name,'source_session':args.source_session,'source_video_sha256':case['source_video_sha256'],'approved_for_rule_engine':False}
        js='const frames='+json.dumps(replay).replace('<','\\u003c')+',review='+json.dumps(review)+';let index='+str(anchor)+',timer=null;function show(i){index=Math.max(0,Math.min(frames.length-1,i));document.getElementById("player").src=frames[index].image;document.getElementById("time").value=index;document.getElementById("info").textContent=frames[index].time.toFixed(3)+" с · "+frames[index].state}function play(){if(timer){clearInterval(timer);timer=null}else timer=setInterval(()=>show((index+1)%frames.length),500)}function save(){const data={...review,human_mask_review:document.getElementById("answer").value,comment:document.getElementById("comment").value,review_scope:"user_reviewed_sampled_frames_only",confirmed:!!(document.getElementById("answer").value&&document.getElementById("confirmed").checked),reviewed_at:new Date().toISOString()};const text=JSON.stringify(data,null,2);document.getElementById("json").value=text;const url=URL.createObjectURL(new Blob([text],{type:"application/json"})),a=document.createElement("a");a.href=url;a.download=review.review_session+"-identity-mask-review.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);document.getElementById("status").textContent=data.confirmed?"Проверка сохранена":"Черновик сохранён"}show(index);'
        page='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'"><title>SAM: документ</title><style>body{font:18px system-ui;max-width:1100px;margin:24px auto;padding:18px}aside{padding:16px;background:#fff0ce}#viewport{height:65vh;overflow:hidden}#player{width:100%;height:100%;object-fit:contain;transform:scale(2.3);transform-origin:50% 55%}select,button,input,textarea{font:inherit;margin:8px;padding:8px}textarea{width:95%}label{display:block}#time{width:65%}</style><h1>Х-3 · сопровождение отмеченного документа</h1><aside>Тип предмета задан твоей разметкой. SAM переносит маску, но не проверяет удостоверение и не распознаёт личность. Потеря маски не доказывает отсутствия документа. Заливка показана также для кандидатов, отклонённых по размеру. Обработаны сохранённые кадры всей длительности, не все исходные кадры.</aside><p>Проверь движение маски около предъявления и не перескакивает ли она на банкноты или руку.</p><div id="viewport"><img id="player"></div><p id="info"></p><button onclick="show(index-1)">←</button><button onclick="play()">Воспроизвести / пауза</button><button onclick="show(index+1)">→</button><input id="time" type="range" min="0" max="'''+str(len(frames)-1)+'''" oninput="show(Number(this.value))"><label>Маска верна на просмотренных кадрах? <select id="answer"><option value="">Выбери</option><option value="correct_on_reviewed_frames">Да</option><option value="incorrect_on_reviewed_frames">Нет / местами неверно</option><option value="unclear">Неясно</option></select></label><label>Где ошибка: <textarea id="comment" rows="2"></textarea></label><label><input id="confirmed" type="checkbox">Подтверждаю ответ по просмотренным кадрам.</label><button onclick="save()">Сохранить проверку / черновик</button><p id="status"></p><details><summary>JSON, если файл не скачался</summary><textarea id="json" rows="8" readonly></textarea></details><script>'''+js+'</script></html>'
        page=page.replace('Х-3 · сопровождение отмеченного документа',html.escape(session['source_name'])+' · сопровождение отмеченного документа')
        (out/'report.html').write_text(page,encoding='utf-8');print('IDENTITY_SAM_REPORT_READY:',out/'report.html',flush=True);print(json.dumps(result),flush=True)
    except Exception as e:
        write_json(out/'status.json',{'status':'failed','error_type':type(e).__name__,'error':str(e)[:1000]});raise

if __name__=='__main__':main()
