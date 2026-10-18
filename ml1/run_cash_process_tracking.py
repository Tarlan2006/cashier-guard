"""SAM tracking of a human cash seed; report machine/safe overlap as candidates only."""
import argparse,base64,datetime,hashlib,html,json,os,sys,time
from pathlib import Path
os.environ.update(HF_HUB_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',PYTORCH_ENABLE_MPS_FALLBACK='1')
from run_ollama_trial import ROOT,write_json
from scene_mvp.cash_process import SPEC,validate_case,candidates


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--trial',type=Path,required=True);parser.add_argument('--case',choices=['X-13','X-14']);args=parser.parse_args()
    trial=args.trial.resolve()
    if not trial.is_relative_to((ROOT/'local').resolve()):parser.error('Local review required')
    pp=trial/'protocol.local.json';protocol=json.loads(pp.read_text());review=json.loads((trial/'human-review.accepted.local.json').read_text())
    if review.get('confirmed') is not True or review.get('protocol_sha256')!=sha(pp):parser.error('Accepted source-bound review required')
    bound={c['case_id']:c for c in protocol['cases']};selected=[c for c in review['cases'] if args.case is None or c['case_id']==args.case]
    if not selected:parser.error('No selected case')
    for case in selected:validate_case(case,bound[case['case_id']])
    runtime=json.loads((ROOT/'local/runtime/sam2-runtime.local.json').read_text());weights=Path(runtime['weights_path'])
    if sha(weights)!=runtime['weights_sha256']:parser.error('SAM checkpoint changed')
    sys.path.insert(0,str(ROOT/'local/runtime/edgetam-deps'));sys.path.insert(0,runtime['source_path'])
    import torch,numpy as np,cv2
    from sam2.build_sam import build_sam2_video_predictor
    from sam2.sam2_image_predictor import SAM2ImagePredictor
    torch.set_num_threads(2);device='mps' if torch.backends.mps.is_available() else 'cpu'
    predictor=build_sam2_video_predictor('configs/sam2.1/sam2.1_hiera_t.yaml',str(weights),device=device,apply_postprocessing=False)
    out=ROOT/'local'/('cash-process-tracking-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir();started=time.monotonic()
    write_json(out/'status.json',{'status':'running','device':device});print('CASH_PROCESS_TRACKING:',out,flush=True)
    try:
        results=[]
        for case in selected:
            source=Path(case['source_session']).resolve()
            if not source.is_relative_to(trial):raise ValueError('Source outside bound review')
            session=json.loads((source/'session.local.json').read_text());frames=session['frames'];definition=bound[case['case_id']]
            if session['source_video_sha256']!=case['source_video_sha256'] or sha(Path(session['source_video']))!=case['source_video_sha256']:raise ValueError('Source video mismatch')
            target=out/case['case_id'];target.mkdir();(target/'frames').mkdir();(target/'overlays').mkdir()
            for i,f in enumerate(frames):
                path=(source/f['file']).resolve()
                if not path.is_relative_to(source) or sha(path)!=definition['frame_sha256'][f['file']]:raise ValueError('Bound frame changed')
                os.link(path,target/'frames'/f'{i:05d}.jpg')
            anchor=next(i for i,f in enumerate(frames) if abs(f['timestamp_sec']-case['cash_anchor_sec'])<.001)
            h,w=frames[anchor]['height'],frames[anchor]['width'];box=np.array(case['zones']['cash_seed'])*np.array([w,h,w,h]);masks={}
            if any(f['width']!=w or f['height']!=h for f in frames):raise ValueError('Source dimensions changed')
            with torch.inference_mode():
                image=cv2.imread(str(source/frames[anchor]['file']));ip=SAM2ImagePredictor(predictor);ip.set_image(cv2.cvtColor(image,cv2.COLOR_BGR2RGB))
                choices,scores,_=ip.predict(box=box.astype(np.float32),multimask_output=True);seed=choices[int(np.argmax(scores))].astype(bool);ip.reset_predictor();del ip
                if not seed.any():raise ValueError('Empty cash seed')
                state=predictor.init_state(str(target/'frames'),offload_video_to_cpu=True,offload_state_to_cpu=True)
                predictor.add_new_mask(state,frame_idx=anchor,obj_id=1,mask=seed)
                for reverse in [False,True]:
                    for index,ids,logits in predictor.propagate_in_video(state,start_frame_idx=anchor,reverse=reverse):
                        masks[index]=(logits[0,0]>0).cpu().numpy()
                        if len(masks)%20==0:print(case['case_id'],'TRACKED',len(masks),'/',len(frames),flush=True)
                del state
            rows=[];pictures=[];b=case['zones']['cash_seed'];max_area=max(.03,4*(b[2]-b[0])*(b[3]-b[1]))
            for i,f in enumerate(frames):
                mask=masks.get(i);area=float(mask.mean()) if mask is not None else 0;valid=SPEC['minimum_mask_fraction']<=area<=max_area
                row={'timestamp_sec':f['timestamp_sec'],'state':'mask_observed' if valid else 'unknown','mask_area_fraction':area,'bbox':None}
                if valid:
                    ys,xs=np.nonzero(mask);row['bbox']=[float(xs.min()/w),float(ys.min()/h),float((xs.max()+1)/w),float((ys.max()+1)/h)]
                image=cv2.imread(str(source/f['file']))
                if valid:
                    tint=image.copy();tint[mask]=(30,220,80);image=cv2.addWeighted(image,.65,tint,.35,0)
                for zone,color in [('machine',(220,100,0)),('safe',(200,30,180))]:
                    z=case['zones'][zone+'_zone'];x1,y1,x2,y2=[round(v) for v in np.array(z)*np.array([w,h,w,h])]
                    row[zone+'_overlap_fraction']=float(mask[y1:y2,x1:x2].sum()/mask.sum()) if valid else None
                    cv2.rectangle(image,(x1,y1),(x2,y2),color,1)
                file=target/'overlays'/f'{i:04d}.jpg';cv2.imwrite(str(file),image);row['overlay_file']=str(file);rows.append(row)
                pictures.append({'time':f['timestamp_sec'],'state':row['state'],'image':'data:image/jpeg;base64,'+base64.b64encode(file.read_bytes()).decode()})
            events=candidates(rows);result={'source_video_sha256':case['source_video_sha256'],'case_id':case['case_id'],'spec':SPEC,
                'timeline':rows,'candidates':events,'cash_mask_human_reviewed':False,'machine_use_established':False,
                'cash_storage_established':False,'cabinet_closure_established':False,'legal_violation_label':None,'approved_for_rule_engine':False}
            write_json(target/'result.local.json',result);results.append({'case_id':case['case_id'],'source_video_sha256':case['source_video_sha256'],'sampled_frames':len(rows),'mask_observed_frames':sum(r['state']=='mask_observed' for r in rows),'candidates':len(events),'result_file':str(target/'result.local.json')})
            data=json.dumps(pictures).replace('<','\\u003c')
            script="const frames="+data+";let index=0,timer=null;function show(i){index=Math.max(0,Math.min(frames.length-1,i));document.getElementById('pic').src=frames[index].image;document.getElementById('t').textContent=frames[index].time.toFixed(3)+' с · '+frames[index].state;document.getElementById('seek').value=index}function play(){if(timer){clearInterval(timer);timer=null}else timer=setInterval(()=>show((index+1)%frames.length),250)}show(0);"
            intervals=''.join('<li>'+html.escape(e['type'])+f" · {e['start_sec']:.3f}–{e['end_sec']:.3f} с"+'</li>' for e in events) or '<li>Устойчивых пересечений не выделено; это не означает отсутствие действий.</li>'
            page='<!doctype html><html lang="ru"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'"><style>body{font:18px system-ui;max-width:1100px;margin:30px auto;padding:16px}img{height:70vh;max-width:100%;object-fit:contain}button,input{font:inherit;padding:8px;margin:8px}aside{background:#fff1cc;padding:15px}</style><h1>'+html.escape(case['case_id'])+' · банкноты, машина и сейф</h1><aside>Зелёная маска сопровождает выбранный тобой предмет. Синяя рамка — машина, фиолетовая — сейф. Маску нужно проверить. Пересечение рамок не доказывает пересчёт или помещение внутрь; потеря маски не доказывает хранение. Состояние дверцы не определяется.</aside><img id="pic"><p id="t"></p><button onclick="show(index-1)">←</button><button onclick="play()">Пуск / пауза</button><button onclick="show(index+1)">→</button><input id="seek" type="range" min="0" max="'+str(len(rows)-1)+'" oninput="show(Number(this.value))"><h2>Кандидаты для просмотра</h2><ul>'+intervals+'</ul><script>'+script+'</script></html>'
            (target/'report.html').write_text(page,encoding='utf-8');del masks
            if device=='mps':torch.mps.empty_cache()
        write_json(out/'summary.local.json',{'cases':results,'elapsed_sec':round(time.monotonic()-started,2),'sam_retrained':False,'cloud_used':False,'approved_for_rule_engine':False})
        write_json(out/'status.json',{'status':'completed','device':device});print('CASH_PROCESS_TRACKING_READY:',out,flush=True)
    except Exception as error:
        write_json(out/'status.json',{'status':'failed','error_type':type(error).__name__,'approved_for_rule_engine':False});raise


if __name__=='__main__':main()
