"""Offline prompted object segmentation; framewise by default, video tracking experimental."""
import argparse,base64,datetime,hashlib,html,json,os,sys,time
from pathlib import Path
os.environ.update(HF_HUB_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',PYTORCH_ENABLE_MPS_FALLBACK='1')
from run_ollama_trial import ROOT,write_json
from scene_mvp.engine import analyze,validate_profile
from scene_mvp.bag_events import attach_review

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--calibration',type=Path,required=True);parser.add_argument('--anchor-sec',type=float,default=None);parser.add_argument('--focus-region',action=argparse.BooleanOptionalAction,default=True);parser.add_argument('--mode',choices=['video','framewise'],default='framewise');args=parser.parse_args()
    profile=json.loads(args.calibration.read_text());validate_profile(profile)
    if profile.get('profile_kind') not in {'bag_scene','object_scene'} or not profile['confirmed']:parser.error('Confirmed human object scene required')
    kind=profile['target_object_kind'];label={'bag':'сумка','cash':'деньги','documents':'документы'}[kind];zone_key='object_zone' if profile.get('profile_kind')=='object_scene' else 'bag_zone'
    source=(ROOT/'local'/profile['source_session']).resolve()
    if not source.is_relative_to((ROOT/'local').resolve()):parser.error('Local session required')
    session=json.loads((source/'session.local.json').read_text())
    if session['source_video_sha256']!=profile['source_video_sha256']:parser.error('Video mismatch')
    ids={p['id'] for f in session['frames'] for p in f['persons']}
    if not set(profile['roles']['cashier_ids'])<=ids:parser.error('Cashier ID absent from session')
    runtime=json.loads((ROOT/'local/runtime/edgetam-runtime.local.json').read_text());weights=Path(runtime['weights_path'])
    if hashlib.sha256(weights.read_bytes()).hexdigest()!=runtime['weights_sha256']:parser.error('Checkpoint changed')
    sys.path.insert(0,str(ROOT/'local/runtime/edgetam-deps'));sys.path.insert(0,runtime['source_path'])
    import torch,numpy as np,cv2,timm.models
    torch.set_num_threads(2);device='mps' if torch.backends.mps.is_available() else 'cpu'
    # The complete official checkpoint supplies these weights. Avoid downloading
    # a redundant classification backbone during model construction.
    original=timm.models.create_model
    def create_offline(*a,**kw):kw['pretrained']=False;return original(*a,**kw)
    timm.models.create_model=create_offline
    from sam2.build_sam import build_sam2_video_predictor
    from sam2.sam2_image_predictor import SAM2ImagePredictor
    out=ROOT/'local'/('edgetam-object-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir();(out/'video_frames').mkdir();(out/'overlays').mkdir()
    start=time.monotonic();write_json(out/'status.json',{'status':'running','phase':'loading_model','device':device});print('EDGETAM_TRIAL:',out,flush=True)
    frames=sorted(session['frames'],key=lambda f:f['timestamp_sec']);anchor_sec=args.anchor_sec if args.anchor_sec is not None else (profile.get('object_anchor_sec') if profile.get('object_anchor_sec') is not None else 15);anchor=min(range(len(frames)),key=lambda i:abs(frames[i]['timestamp_sec']-anchor_sec))
    if profile.get('profile_kind')=='object_scene' and abs(frames[anchor]['timestamp_sec']-anchor_sec)>.001:parser.error('Object anchor must match a saved frame')
    h,w=frames[anchor]['height'],frames[anchor]['width'];b=profile['zones'][zone_key];focus=None
    if args.focus_region:focus=[max(0,round((b[0]-.1)*w)),max(0,round((b[1]-.1)*h)),min(w,round((b[2]+.1)*w)),min(h,round((b[3]+.1)*h))]
    for i,f in enumerate(frames):
        path=(source/f['file']).resolve()
        if not path.is_relative_to(source):parser.error('Frame outside session')
        if focus:
            x1,y1,x2,y2=focus;image=cv2.imread(str(path));cv2.imwrite(str(out/'video_frames'/f'{i:05d}.jpg'),image[y1:y2,x1:x2])
        else:os.link(path,out/'video_frames'/f'{i:05d}.jpg')
    predictor=build_sam2_video_predictor('configs/edgetam.yaml',str(weights),device=device,apply_postprocessing=False)
    h,w=frames[anchor]['height'],frames[anchor]['width'];b=profile['zones'][zone_key];box=np.array([b[0]*w,b[1]*h,b[2]*w,b[3]*h],dtype=np.float32)
    if focus:box-=np.array([focus[0],focus[1],focus[0],focus[1]],dtype=np.float32)
    masks={}
    with torch.inference_mode():
        image_predictor=SAM2ImagePredictor(predictor)
        anchor_image=cv2.cvtColor(cv2.imread(str(out/'video_frames'/f'{anchor:05d}.jpg')),cv2.COLOR_BGR2RGB)
        image_predictor.set_image(anchor_image)
        initial_masks,initial_scores,_=image_predictor.predict(box=box,multimask_output=True)
        selected=int(np.argmax(initial_scores));initial_mask=initial_masks[selected].astype(bool)
        if not initial_mask.any():raise RuntimeError('No initial mask; do not fabricate tracked object')
        image_predictor.reset_predictor()
        if args.mode=='framewise':
            for index in range(len(frames)):
                rgb=cv2.cvtColor(cv2.imread(str(out/'video_frames'/f'{index:05d}.jpg')),cv2.COLOR_BGR2RGB)
                image_predictor.set_image(rgb)
                candidates,scores,_=image_predictor.predict(box=box,multimask_output=True)
                mask=candidates[int(np.argmax(scores))].astype(bool)
                if focus:
                    mapped=np.zeros((h,w),dtype=bool);mapped[focus[1]:focus[3],focus[0]:focus[2]]=mask;mask=mapped
                masks[index]=mask
                if (index+1)%10==0:print('Segmented frames:',index+1,'/',len(frames),flush=True)
            image_predictor.reset_predictor()
        else:
            state=predictor.init_state(str(out/'video_frames'),offload_video_to_cpu=True,offload_state_to_cpu=True)
            predictor.add_new_mask(state,frame_idx=anchor,obj_id=1,mask=initial_mask)
            for reverse in (False,True):
                for index,object_ids,logits in predictor.propagate_in_video(state,start_frame_idx=anchor,reverse=reverse):
                    mask=(logits[0,0]>0).cpu().numpy()
                    if focus:
                        mapped=np.zeros((h,w),dtype=bool);mapped[focus[1]:focus[3],focus[0]:focus[2]]=mask;mask=mapped
                    masks[index]=mask
    observations={};cards=[]
    for i,f in enumerate(frames):
        mask=masks.get(i);bbox=None;area=0
        if mask is not None and mask.any():
            ys,xs=np.nonzero(mask);area=float(mask.mean());bbox=[float(xs.min()/w),float(ys.min()/h),float((xs.max()+1)/w),float((ys.max()+1)/h)]
        valid=bbox is not None and .0002<=area<=max(.03,4*(b[2]-b[0])*(b[3]-b[1]))
        observations[round(f['timestamp_sec'],3)]={'state':'mask_observed' if valid else 'unknown','bbox':bbox if valid else None,'mask_area_fraction':area,'source':'edgetam_framewise_human_region_segmentation' if args.mode=='framewise' else 'edgetam_human_prompted_object_tracking'}
        image=cv2.imread(str(source/f['file']))
        if valid:
            tint=image.copy();tint[mask]=(0,210,80);image=cv2.addWeighted(image,.65,tint,.35,0)
        cv2.rectangle(image,(round(b[0]*w),round(b[1]*h)),(round(b[2]*w),round(b[3]*h)),(255,100,0),1)
        name=f'overlays/{i:03d}.jpg';cv2.imwrite(str(out/name),image);uri=base64.b64encode((out/name).read_bytes()).decode()
        cards.append('<article><h3>'+str(round(f['timestamp_sec'],3))+' с'+(' · опорный кадр' if i==anchor else '')+'</h3><img src="data:image/jpeg;base64,'+uri+'"><p>'+('Есть маска указанного объекта' if valid else 'Неясно')+'</p></article>')
    result=analyze(frames,profile,session['source_video_sha256']);attach_review(result,observations,profile)
    summary={'model':'EdgeTAM','device':device,'frames':len(frames),'mask_observed_frames':sum(o['state']=='mask_observed' for o in observations.values()),'anchor_sec':frames[anchor]['timestamp_sec'],'human_target_kind':kind,'anchor_time_source':'human_object_box_frame' if 'object_anchor_sec' in profile else 'legacy_trial_selected_needs_visual_review','initialization':'per_frame_reviewed_box' if args.mode=='framewise' else 'image_multimask_then_video_mask_prompt','anchor_mask_model_iou_score_uncalibrated':float(initial_scores[selected]),'human_reference_box':b,'model_trained_here':False,'vlm_used':False,'cloud_inference_used':False,'bidirectional_offline_tracking':args.mode=='video','mode':args.mode,'focus_crop_px':focus,'development_refinement':bool(focus),'elapsed_sec':round(time.monotonic()-start,2),'experimental_review_candidates':len(result['experimental_signals']),'approved_for_rule_engine':False,'object_identity_visually_verified':False,'automatic_object_classification':False,'object_presence_validated':False}
    for signal in result['experimental_signals']:signal['source']='edgetam_framewise_human_region_segmentation' if args.mode=='framewise' else 'edgetam_human_prompted_object_tracking'
    write_json(out/'observations.local.json',result);write_json(out/'summary.local.json',summary);write_json(out/'calibration.local.json',profile);write_json(out/'runtime.local.json',runtime)
    signal_rows=''.join('<li>'+str(s['start_sec'])+'–'+str(s['end_sec'])+' с: маска предмета при наблюдаемом отходе кассира. Требует проверки.</li>' for s in result['experimental_signals'])
    text='<!doctype html><html lang="ru"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'"><style>body{font:18px system-ui;max-width:1200px;margin:30px auto;padding:20px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px}img{width:100%}article{background:#eef3f8;padding:15px}</style><h1>Одна рамка → сопровождение объекта: EdgeTAM</h1><p>Проверь зелёную маску, особенно опорный кадр '+str(summary['anchor_sec'])+' с: покрывает ли она нужный предмет ('+label+')? Тип предмета задан человеком, модель его самостоятельно не определяет. Синяя рамка — твоя исходная область.</p><p>Это локальный эксперимент без обучения и LLM. Отсутствие маски и потеря трека кассира считаются неизвестностью. Сопровождение выполнено вперёд и назад по сохранённому видео; это не замер потокового режима.</p><p>Устройство: '+device+'; '+str(len(frames))+' кадров; '+str(summary['elapsed_sec'])+' с. '+('Модели подан крупный участок вокруг рамки; это дополнительный эксперимент на том же видео. ' if focus else '')+'Маска на '+str(summary['mask_observed_frames'])+' кадрах не доказывает её правильность. Общая точность не измерена.</p><h2>Кандидаты для проверки</h2><ul>'+signal_rows+'</ul><p>Модель выделяет область по рамке, но не проверяет её содержимое. Возможна маска фона после удаления предмета. Правовое нарушение и отсутствие всех людей в помещении не установлены.</p><div class="grid">'+''.join(cards)+'</div></html>'
    if args.mode=='framewise':text=text.replace('Одна рамка → сопровождение объекта: EdgeTAM','Одна рамка → маски по видео: EdgeTAM').replace('Сопровождение выполнено вперёд и назад по сохранённому видео; это не замер потокового режима.','Каждый кадр обработан отдельно с той же исходной рамкой. Это сегментация в подтверждённой области, а не слежение за перемещением по всему кадру.')
    text=text.replace('<div class="grid">','<h2>Опорный кадр</h2>'+cards[anchor]+'<h2>Все кадры</h2><div class="grid">');(out/'report.html').write_text(text);write_json(out/'status.json',{'status':'completed','device':device,'approved_for_rule_engine':False});print('EDGETAM_BAG_REPORT_READY:',out/'report.html',flush=True);print(json.dumps(summary),flush=True)

if __name__=='__main__':main()
