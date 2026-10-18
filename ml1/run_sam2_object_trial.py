"""Offline full-frame SAM 2.1 tracking from a human object region, no text prompting."""
import argparse,base64,datetime,hashlib,html,json,math,os,sys,time,traceback
from pathlib import Path
os.environ.update(HF_HUB_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',PYTORCH_ENABLE_MPS_FALLBACK='1')
from run_ollama_trial import ROOT,write_json
from scene_mvp.engine import analyze,validate_profile
from scene_mvp.bag_events import attach_review

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--calibration',type=Path,required=True);p.add_argument('--initialization',choices=['crop-mask','box'],default='crop-mask');p.add_argument('--anchor-sec',type=float);args=p.parse_args()
 profile=json.loads(args.calibration.read_text());validate_profile(profile)
 if profile.get('profile_kind') not in {'object_scene','bag_scene'} or not profile['confirmed']:p.error('Confirmed object or legacy bag scene required')
 source=(ROOT/'local'/profile['source_session']).resolve()
 if not source.is_relative_to((ROOT/'local').resolve()):p.error('Local session required')
 session=json.loads((source/'session.local.json').read_text())
 if session['source_video_sha256']!=profile['source_video_sha256']:p.error('Video mismatch')
 frames=sorted(session['frames'],key=lambda f:f['timestamp_sec'])
 anchor_sec=args.anchor_sec if args.anchor_sec is not None else profile.get('object_anchor_sec',frames[0]['timestamp_sec'])
 if type(anchor_sec) not in (int,float) or not math.isfinite(anchor_sec) or anchor_sec<0:p.error('Finite nonnegative anchor required')
 anchor=min(range(len(frames)),key=lambda i:abs(frames[i]['timestamp_sec']-anchor_sec))
 if abs(frames[anchor]['timestamp_sec']-anchor_sec)>.001:p.error('Unknown anchor time')
 anchor_source='human_object_box_frame' if args.anchor_sec is None and profile.get('profile_kind')=='object_scene' else 'trial_selected_needs_visual_review'
 zone_key='bag_zone' if profile.get('profile_kind')=='bag_scene' else 'object_zone'
 if not set(profile['roles']['cashier_ids'])<={v['id'] for f in frames for v in f['persons']}:p.error('Cashier ID absent')
 runtime=json.loads((ROOT/'local/runtime/sam2-runtime.local.json').read_text());weights=Path(runtime['weights_path'])
 if hashlib.sha256(weights.read_bytes()).hexdigest()!=runtime['weights_sha256']:p.error('Checkpoint changed')
 sys.path.insert(0,str(ROOT/'local/runtime/edgetam-deps'));sys.path.insert(0,runtime['source_path'])
 import torch,numpy as np,cv2
 torch.set_num_threads(2);device='mps' if torch.backends.mps.is_available() else 'cpu'
 from sam2.build_sam import build_sam2_video_predictor
 from sam2.sam2_image_predictor import SAM2ImagePredictor
 out=ROOT/'local'/('sam2-object-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir();(out/'video_frames').mkdir();(out/'overlays').mkdir()
 print('SAM2_TRIAL:',out,flush=True);start=time.monotonic();write_json(out/'status.json',{'status':'running','phase':'loading_model','device':device})
 try:
  for i,f in enumerate(frames):
   path=(source/f['file']).resolve()
   if not path.is_relative_to(source):raise ValueError('Frame outside source')
   os.link(path,out/'video_frames'/f'{i:05d}.jpg')
  predictor=build_sam2_video_predictor('configs/sam2.1/sam2.1_hiera_t.yaml',str(weights),device=device,apply_postprocessing=False)
  h,w=frames[anchor]['height'],frames[anchor]['width'];b=profile['zones'][zone_key];box=np.array([b[0]*w,b[1]*h,b[2]*w,b[3]*h],dtype=np.float32)
  initial_score=None;seed_crop=None;masks={}
  with torch.inference_mode():
   seed_mask=None
   if args.initialization=='crop-mask':
    seed_crop=[max(0,round((b[0]-.1)*w)),max(0,round((b[1]-.1)*h)),min(w,round((b[2]+.1)*w)),min(h,round((b[3]+.1)*h))]
    x1,y1,x2,y2=seed_crop;image=cv2.imread(str(out/'video_frames'/f'{anchor:05d}.jpg'))
    # Match the previous local seed-view JPEG encoding; only the seed is cropped.
    ok,encoded=cv2.imencode('.jpg',image[y1:y2,x1:x2])
    if not ok:raise RuntimeError('Seed crop encode failed')
    crop=cv2.imdecode(encoded,cv2.IMREAD_COLOR);image_predictor=SAM2ImagePredictor(predictor)
    image_predictor.set_image(cv2.cvtColor(crop,cv2.COLOR_BGR2RGB))
    candidates,scores,_=image_predictor.predict(box=box-np.array([x1,y1,x1,y1],dtype=np.float32),multimask_output=True)
    selected=int(np.argmax(scores));initial_score=float(scores[selected]);seed_mask=np.zeros((h,w),dtype=bool);seed_mask[y1:y2,x1:x2]=candidates[selected].astype(bool)
    image_predictor.reset_predictor();del image_predictor
    if not seed_mask.any():raise RuntimeError('No initial object mask')
   state=predictor.init_state(str(out/'video_frames'),offload_video_to_cpu=True,offload_state_to_cpu=True)
   if seed_mask is not None:predictor.add_new_mask(state,frame_idx=anchor,obj_id=1,mask=seed_mask)
   else:predictor.add_new_points_or_box(state,frame_idx=anchor,obj_id=1,box=box)
   for reverse in (False,True):
    for index,ids,logits in predictor.propagate_in_video(state,start_frame_idx=anchor,reverse=reverse):
     masks[index]=(logits[0,0]>0).cpu().numpy()
     if len(masks)%10==0:
      print('SAM2_TRACKED_FRAMES:',len(masks),'/',len(frames),flush=True)
      write_json(out/'status.json',{'status':'running','phase':'tracking','frames':len(masks),'total_frames':len(frames),'device':device})
   del state
  observations={};cards=[];replay=[]
  for i,f in enumerate(frames):
   mask=masks.get(i);bbox=None;area=0
   if mask is not None and mask.any():
    ys,xs=np.nonzero(mask);area=float(mask.mean());bbox=[float(xs.min()/w),float(ys.min()/h),float((xs.max()+1)/w),float((ys.max()+1)/h)]
   valid=bbox is not None and .0002<=area<=max(.03,4*(b[2]-b[0])*(b[3]-b[1]))
   observations[round(f['timestamp_sec'],3)]={'state':'mask_observed' if valid else 'unknown','bbox':bbox if valid else None,'mask_area_fraction':area,'source':'sam2_1_full_frame_offline_tracking'}
   image=cv2.imread(str(source/f['file']))
   if valid:
    tint=image.copy();tint[mask]=(0,210,80);image=cv2.addWeighted(image,.65,tint,.35,0)
    cv2.rectangle(image,(round(bbox[0]*w),round(bbox[1]*h)),(round(bbox[2]*w),round(bbox[3]*h)),(0,210,80),1)
   if i==anchor:cv2.rectangle(image,(round(b[0]*w),round(b[1]*h)),(round(b[2]*w),round(b[3]*h)),(255,100,0),2)
   name=f'overlays/{i:03d}.jpg';cv2.imwrite(str(out/name),image);uri='data:image/jpeg;base64,'+base64.b64encode((out/name).read_bytes()).decode()
   note='Маска получена' if valid else 'Маска неясна / потеряна';replay.append({'time':f['timestamp_sec'],'image':uri,'state':note})
   cards.append('<article><h3>'+f"{f['timestamp_sec']:.3f}"+' с'+(' · опорный кадр' if i==anchor else '')+'</h3><img src="'+uri+'"><p>'+note+'</p></article>')
  result=analyze(frames,profile,session['source_video_sha256']);attach_review(result,observations,profile)
  for signal in result.get('experimental_signals',[]):signal['source']='sam2_1_full_frame_offline_tracking'
  deltas=[frames[i+1]['timestamp_sec']-frames[i]['timestamp_sec'] for i in range(len(frames)-1)];nominal_fps=round(1/float(np.median(deltas)),2) if deltas else None
  summary={'model':'SAM 2.1 Hiera Tiny','device':device,'mode':'video','frames':len(frames),'mask_observed_frames':sum(o['state']=='mask_observed' for o in observations.values()),'anchor_sec':frames[anchor]['timestamp_sec'],'anchor_time_source':anchor_source,'human_target_kind':profile['target_object_kind'],'initialization':args.initialization,'seed_crop_px':seed_crop,'focus_crop_px':None,'full_frame_tracking':True,'initial_mask_iou_score_uncalibrated':initial_score,'sample_fps_nominal':nominal_fps,'all_original_video_frames_processed':False,'bidirectional_offline_tracking':True,'first_sample_sec':frames[0]['timestamp_sec'],'last_sample_sec':frames[-1]['timestamp_sec'],'model_trained_here':False,'cloud_inference_used':False,'text_prompt_used':False,'automatic_object_classification':False,'object_identity_visually_verified':False,'approved_for_rule_engine':False,'experimental_review_candidates':len(result.get('experimental_signals',[])),'elapsed_sec':round(time.monotonic()-start,2)}
  for name,data in [('observations.local.json',result),('summary.local.json',summary),('calibration.local.json',profile),('runtime.local.json',runtime)]:write_json(out/name,data)
  seed_description='Начальная маска получена на увеличенном участке, затем сопровождение выполняется по всему кадру вперёд и назад.' if args.initialization=='crop-mask' else 'Начальная рамка передана непосредственно SAM на полном кадре; затем сопровождение выполняется по всему кадру вперёд и назад.'
  labels={'bag':'сумка','cash':'деньги','documents':'документы'};intervals='; '.join(f"{s['start_sec']:.2f}–{s['end_sec']:.2f} с" for s in result.get('experimental_signals',[])) or 'сигнал не выделен'
  data=json.dumps(replay,ensure_ascii=False).replace('<','\\u003c')
  script="const frames="+data+";let index=0,timer=null;function show(i){index=Math.max(0,Math.min(frames.length-1,i));document.getElementById('player').src=frames[index].image;document.getElementById('time').value=index;document.getElementById('info').textContent=frames[index].time.toFixed(3)+' с · '+frames[index].state;}function play(){if(timer){clearInterval(timer);timer=null;return;}timer=setInterval(()=>{show((index+1)%frames.length)},500)}show(0);"
  page='<!doctype html><html lang="ru"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'; script-src \'unsafe-inline\'; connect-src \'none\'"><title>SAM 2.1 — отслеживание предмета</title><style>body{font:18px system-ui;max-width:1200px;margin:30px auto;padding:20px}img{width:100%}#player{height:65vh;object-fit:contain}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:15px}article{padding:15px;background:#edf2f8}button,input{font:inherit;margin:12px;padding:10px}</style><h1>'+html.escape(session['source_name'])+' · SAM 2.1 · '+labels[profile['target_object_kind']]+'</h1><p>Твоя рамка задаёт нужный предмет; текстовый запрос не используется. '+seed_description+' Тип задан человеком, модель его не проверяет.</p><p>Обработана вся длительность с выборкой '+str(nominal_fps)+' кадра/с, не каждый исходный кадр. Это офлайн-анализ. Число полученных масок не является оценкой точности; потеря маски — неизвестность.</p><p>Результат для проверки: '+intervals+'. Время: '+str(summary['elapsed_sec'])+' с, '+device+'. Основной покадровый режим сохранён.</p><img id="player"><p id="info"></p><button onclick="play()">Воспроизвести / пауза</button><input id="time" type="range" min="0" max="'+str(len(frames)-1)+'" value="0" oninput="show(Number(this.value))"><h2>Опорный кадр</h2>'+cards[anchor]+'<details><summary>Все обработанные кадры</summary><div class="grid">'+''.join(cards)+'</div></details><script>'+script+'</script></html>'
  (out/'report.html').write_text(page,encoding='utf-8');write_json(out/'status.json',{'status':'completed','device':device,'approved_for_rule_engine':False});print('SAM2_REPORT_READY:',out/'report.html',flush=True);print(json.dumps(summary),flush=True)
 except Exception as e:
  write_json(out/'status.json',{'status':'failed','error_type':type(e).__name__,'error':str(e)[:1000],'approved_for_rule_engine':False});raise

if __name__=='__main__':main()
