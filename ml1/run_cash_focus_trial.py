"""Short exploratory crop comparison after a human-reported SAM identity failure."""
import argparse,base64,datetime,hashlib,html,json,os,sys,time
from pathlib import Path
os.environ.update(HF_HUB_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',PYTORCH_ENABLE_MPS_FALLBACK='1')
from run_ollama_trial import ROOT,write_json
from scene_mvp.cash_focus import focus_bounds,local_box
from scene_mvp.cash_process import validate_case


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--trial',type=Path,required=True);parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--case',choices=['X-13','X-14'],default='X-13');parser.add_argument('--start',type=float,default=25);parser.add_argument('--end',type=float,default=30);args=parser.parse_args()
    trial=args.trial.resolve();baseline=args.baseline.resolve()
    if any(not p.is_relative_to((ROOT/'local').resolve()) for p in [trial,baseline]):parser.error('Local source and baseline required')
    review=json.loads((trial/'human-review.accepted.local.json').read_text());case=next(c for c in review['cases'] if c['case_id']==args.case)
    plan=json.loads((trial/'protocol.local.json').read_text());definition=next(c for c in plan['cases'] if c['case_id']==args.case);validate_case(case,definition)
    source=Path(case['source_session']).resolve()
    if not source.is_relative_to(trial):parser.error('Bound source required')
    session=json.loads((source/'session.local.json').read_text());frames=[f for f in session['frames'] if args.start-.001<=f['timestamp_sec']<=args.end+.001]
    if not frames or not args.start<=case['cash_anchor_sec']<=args.end or args.end-args.start>10:parser.error('Short clip containing the human seed required')
    old=json.loads((baseline/args.case/'result.local.json').read_text())
    if old['source_video_sha256']!=case['source_video_sha256']:parser.error('Baseline video mismatch')
    runtime=json.loads((ROOT/'local/runtime/sam2-runtime.local.json').read_text());weights=Path(runtime['weights_path'])
    if sha(weights)!=runtime['weights_sha256']:parser.error('SAM checkpoint changed')
    out=ROOT/'local'/('cash-focus-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir();(out/'frames').mkdir();(out/'overlays').mkdir()
    w,h=frames[0]['width'],frames[0]['height'];roi=focus_bounds(case['zones'],w,h);x1,y1,x2,y2=roi
    protocol={'version':'cash-focus-exploratory/1','source_video_sha256':case['source_video_sha256'],'case_id':args.case,
        'source_review_sha256':sha(trial/'human-review.accepted.local.json'),'baseline_result_sha256':sha(baseline/args.case/'result.local.json'),
        'sam_weights_sha256':runtime['weights_sha256'],'runner_sha256':sha(Path(__file__)),'crop_module_sha256':sha(ROOT/'scene_mvp/cash_focus.py'),
        'crop_bounds_px':roi,'padding_normalized':.04,'sample_times_sec':[f['timestamp_sec'] for f in frames],
        'developed_after_baseline_failure':True,'independent_evaluation':False,'cash_label_and_seed_unchanged':True,
        'crop_jpeg_quality':95,'image_upscaling_before_model':False,'automatic_action_detection_validated':False}
    write_json(out/'protocol.local.json',protocol);write_json(out/'status.json',{'status':'running'});print('CASH_FOCUS_TRIAL:',out,flush=True)
    sys.path.insert(0,str(ROOT/'local/runtime/edgetam-deps'));sys.path.insert(0,runtime['source_path'])
    import cv2,numpy as np,torch
    from sam2.build_sam import build_sam2_video_predictor
    from sam2.sam2_image_predictor import SAM2ImagePredictor
    started=time.monotonic();torch.set_num_threads(2);device='mps' if torch.backends.mps.is_available() else 'cpu'
    try:
        for i,f in enumerate(frames):
            original=(source/f['file']).resolve()
            if not original.is_relative_to(source) or sha(original)!=definition['frame_sha256'][f['file']]:raise ValueError('Source frame changed')
            image=cv2.imread(str(original));cv2.imwrite(str(out/'frames'/f'{i:05d}.jpg'),image[y1:y2,x1:x2],[cv2.IMWRITE_JPEG_QUALITY,95])
        anchor=next(i for i,f in enumerate(frames) if abs(f['timestamp_sec']-case['cash_anchor_sec'])<.001)
        predictor=build_sam2_video_predictor('configs/sam2.1/sam2.1_hiera_t.yaml',str(weights),device=device,apply_postprocessing=False)
        masks={}
        with torch.inference_mode():
            ip=SAM2ImagePredictor(predictor);image=cv2.imread(str(out/'frames'/f'{anchor:05d}.jpg'));ip.set_image(cv2.cvtColor(image,cv2.COLOR_BGR2RGB))
            choices,scores,_=ip.predict(box=np.array(local_box(case['zones']['cash_seed'],roi,w,h),np.float32),multimask_output=True)
            seed=choices[int(np.argmax(scores))].astype(bool);ip.reset_predictor();del ip
            if not seed.any():raise ValueError('Empty focused cash seed')
            state=predictor.init_state(str(out/'frames'),offload_video_to_cpu=True,offload_state_to_cpu=True)
            predictor.add_new_mask(state,frame_idx=anchor,obj_id=1,mask=seed)
            for reverse in [False,True]:
                for i,ids,logits in predictor.propagate_in_video(state,start_frame_idx=anchor,reverse=reverse):masks[i]=(logits[0,0]>0).cpu().numpy()
            del state
        rows=[];cards=[];b=case['zones']['cash_seed'];maximum=max(.03,4*(b[2]-b[0])*(b[3]-b[1]));example_times=[args.start,args.start+1,args.start+3,args.end]
        for i,f in enumerate(frames):
            mask=masks.get(i);area=float(mask.sum()/(w*h)) if mask is not None else 0;valid=.0002<=area<=maximum
            original=cv2.imread(str(source/f['file']));image=original.copy();bbox=None
            if valid:
                full=np.zeros((h,w),bool);full[y1:y2,x1:x2]=mask;tint=image.copy();tint[full]=(30,220,80);image=cv2.addWeighted(image,.65,tint,.35,0)
                ys,xs=np.nonzero(full);bbox=[float(xs.min()/w),float(ys.min()/h),float((xs.max()+1)/w),float((ys.max()+1)/h)]
            cv2.rectangle(image,(x1,y1),(x2,y2),(0,150,255),1);file=out/'overlays'/f'{i:03d}.jpg';cv2.imwrite(str(file),image)
            rows.append({'timestamp_sec':f['timestamp_sec'],'state':'mask_observed' if valid else 'unknown','bbox':bbox,'mask_area_fraction':area,'overlay_file':str(file)})
            if any(abs(f['timestamp_sec']-t)<.001 for t in example_times):
                old_row=next(r for r in old['timeline'] if abs(r['timestamp_sec']-f['timestamp_sec'])<.001)
                pictures=[('Прежний полный кадр',Path(old_row['overlay_file'])),('Новый участок: маску ещё нужно проверить',file)]
                cards.append('<section><h2>'+f"{f['timestamp_sec']:.3f} с"+'</h2><div class="grid">'+''.join('<figure><figcaption>'+label+'</figcaption><img src="data:image/jpeg;base64,'+base64.b64encode(path.read_bytes()).decode()+'"></figure>' for label,path in pictures)+'</div></section>')
        write_json(out/'result.local.json',{'protocol':protocol,'timeline':rows,'cash_mask_human_reviewed':False,'automatic_machine_use_established':False,'automatic_storage_established':False})
        page='<!doctype html><html lang="ru"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'"><style>body{font:18px system-ui;max-width:1300px;margin:25px auto;padding:15px}.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:15px}figure{margin:0}img{height:60vh;width:100%;object-fit:contain}aside{background:#fff1cc;padding:18px}section{margin:25px 0}</style><h1>'+html.escape(args.case)+' · короткая проверка участка '+str(args.start)+'–'+str(args.end)+' с</h1><aside>Слева прежнее сопровождение, которое ты признал неверным после 25 с. Справа — новая попытка на более крупном рабочем участке с той же исходной рамкой банкнот. Оранжевая рамка показывает участок обработки. Новые детали не восстановлены; модель сама меняет масштаб входа. Это эксперимент после известной ошибки, без доказанной точности. Проверь, остаётся ли зелёная маска на банкнотах на 26, 28 и 30 с.</aside>'+''.join(cards)+'</html>'
        (out/'report.html').write_text(page,encoding='utf-8');summary={'sampled_frames':len(rows),'mask_observed_frames':sum(r['state']=='mask_observed' for r in rows),'elapsed_sec':round(time.monotonic()-started,2),'accuracy_established':False}
        write_json(out/'status.json',{'status':'completed',**summary});write_json(ROOT/'local/cash-focus-current.local.json',{'trial':str(out),'report':str(out/'report.html'),'status':'needs_focused_cash_mask_review',**summary})
        print('CASH_FOCUS_REPORT_READY:',out/'report.html',flush=True)
    except Exception as error:write_json(out/'status.json',{'status':'failed','error_type':type(error).__name__});raise


if __name__=='__main__':main()
