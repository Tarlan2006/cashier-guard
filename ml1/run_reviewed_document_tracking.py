"""Dense local SAM clip tracking from an already human-selected document box."""
import argparse,base64,datetime,hashlib,json,os,sys,time
from pathlib import Path
os.environ.update(HF_HUB_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',PYTORCH_ENABLE_MPS_FALLBACK='1')
from run_ollama_trial import ROOT,write_json
from import_document_search_review import validate
RUN_OUTPUT=None


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    global RUN_OUTPUT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial',type=Path,required=True);parser.add_argument('--key',required=True)
    parser.add_argument('--radius-sec',type=float,default=3.);parser.add_argument('--sample-fps',type=int,default=4)
    args=parser.parse_args();trial=args.trial.resolve()
    if not trial.is_relative_to((ROOT/'local').resolve()):parser.error('Local candidate trial required')
    if not 0<args.radius_sec<=5 or args.sample_fps not in [2,4]:parser.error('Bounded local clip required')
    review_path=trial/'human-candidate-review.accepted.local.json';review=json.loads(review_path.read_text());validate(review,trial)
    if sha(trial/'human-candidate-review.original.local.json')!=review['review_sha256']:parser.error('Original review changed')
    row=next(r for r in review['reviews'] if r['key']==args.key)
    if row['human_selection'] not in {'A','B','C'}:parser.error('A human-selected document box is required')
    box=row['proposals'][ord(row['human_selection'])-65]['bbox'];anchor_sec=row['timestamp_sec']
    source=ROOT/'local'/row['source_session'];session=json.loads((source/'session.local.json').read_text())
    video=Path(session['source_video'])
    if sha(video)!=row['source_video_sha256']:parser.error('Original source video changed')
    original_frame=min(session['frames'],key=lambda f:abs(f['timestamp_sec']-anchor_sec))
    if abs(original_frame['timestamp_sec']-anchor_sec)>.001 or sha(source/original_frame['file'])!=row['frame_sha256']:
        parser.error('Reviewed anchor frame changed')
    runtime=json.loads((ROOT/'local/runtime/sam2-runtime.local.json').read_text());weights=Path(runtime['weights_path'])
    if sha(weights)!=runtime['weights_sha256']:parser.error('SAM checkpoint changed')
    out=ROOT/'local'/('document-track-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir()
    RUN_OUTPUT=out
    (out/'video_frames').mkdir();(out/'overlays').mkdir()
    protocol={'schema_version':'reviewed-document-track/1','review_session':out.name,'source_session':row['source_session'],
        'source_video_sha256':row['source_video_sha256'],'source_candidate_trial':str(trial),
        'accepted_candidate_review_sha256':sha(review_path),'original_candidate_review_sha256':review['review_sha256'],
        'anchor_frame_sha256':row['frame_sha256'],'anchor_sec':anchor_sec,'human_selected_bbox':box,
        'human_type_claim':'human_selected_document_candidate_not_identity_document_verified',
        'runtime':runtime,'clip_radius_sec':args.radius_sec,'sample_fps_nominal':args.sample_fps,
        'runner_sha256':sha(Path(__file__)),'automatic_object_classification':False,'bidirectional_offline_tracking':True,
        'mask_loss_means_unknown':True,'native_frames_all_processed':False,'object_identity_established':False,
        'document_presentation_or_inspection_established':False,'identity_verification_established':False,
        'approved_for_rule_engine':False,'legal_violation_label':None,'bank_data_uploaded':False}
    write_json(out/'protocol.local.json',protocol);write_json(out/'status.json',{'status':'running','phase':'extracting_clip'})
    print('DOCUMENT_TRACK:',out,flush=True);started=time.monotonic()
    sys.path.insert(0,str(ROOT.parent/'ml2'))
    from backend.pipeline.video import VideoReader
    import cv2,numpy as np
    frames=[]
    with VideoReader(video) as reader:
        count=round(args.radius_sec*args.sample_fps)
        for step in range(-count,count+1):
            requested=anchor_sec+step/args.sample_fps
            if not 0<=requested<reader.metadata.duration_sec:continue
            nearest=min(session['frames'],key=lambda f:abs(f['timestamp_sec']-requested))
            filename=f'{len(frames):05d}.jpg';dest=out/'video_frames'/filename
            if abs(nearest['timestamp_sec']-requested)<.001:
                os.link(source/nearest['file'],dest);actual=nearest['timestamp_sec']
            else:
                sample=reader.read_at(requested);actual=sample.actual_timestamp_sec
                ok,encoded=cv2.imencode('.jpg',sample.frame_bgr,[cv2.IMWRITE_JPEG_QUALITY,90])
                if not ok:raise ValueError('Native clip frame encode failed')
                dest.write_bytes(encoded.tobytes())
            if frames and actual<=frames[-1]['timestamp_sec']:dest.unlink();continue
            frames.append({'timestamp_sec':actual,'file':'video_frames/'+filename,'sha256':sha(dest)})
    anchor=min(range(len(frames)),key=lambda i:abs(frames[i]['timestamp_sec']-anchor_sec))
    if frames[anchor]['sha256']!=row['frame_sha256']:raise ValueError('Dense clip anchor differs from human-reviewed pixels')
    write_json(out/'clip-frames.local.json',{'frames':frames,'anchor_index':anchor})
    sys.path.insert(0,str(ROOT/'local/runtime/edgetam-deps'));sys.path.insert(0,runtime['source_path'])
    import torch
    from sam2.build_sam import build_sam2_video_predictor
    from sam2.sam2_image_predictor import SAM2ImagePredictor
    torch.set_num_threads(2);device='mps' if torch.backends.mps.is_available() else 'cpu'
    write_json(out/'status.json',{'status':'running','phase':'loading_sam','device':device})
    predictor=build_sam2_video_predictor('configs/sam2.1/sam2.1_hiera_t.yaml',str(weights),device=device,apply_postprocessing=False)
    image=cv2.imread(str(out/frames[anchor]['file']));h,w=image.shape[:2];masks={}
    with torch.inference_mode():
        x1,y1,x2,y2=max(0,round((box[0]-.1)*w)),max(0,round((box[1]-.1)*h)),min(w,round((box[2]+.1)*w)),min(h,round((box[3]+.1)*h))
        ok,encoded=cv2.imencode('.jpg',image[y1:y2,x1:x2])
        if not ok:raise ValueError('Seed crop encode failed')
        seed_image=cv2.imdecode(encoded,cv2.IMREAD_COLOR);image_predictor=SAM2ImagePredictor(predictor)
        image_predictor.set_image(cv2.cvtColor(seed_image,cv2.COLOR_BGR2RGB))
        crop_box=np.array([box[0]*w-x1,box[1]*h-y1,box[2]*w-x1,box[3]*h-y1],np.float32)
        options,values,_=image_predictor.predict(box=crop_box,multimask_output=True);best=int(np.argmax(values))
        initial=np.zeros((h,w),bool);initial[y1:y2,x1:x2]=options[best].astype(bool);area=int(initial.sum())
        human_area=(box[2]-box[0])*w*(box[3]-box[1])*h
        if not 16<=area<=human_area*4:raise ValueError('Seed mask needs correction')
        write_json(out/'seed.local.json',{'initial_mask_pixels':area,'human_box_pixels':human_area,'sam_score_uncalibrated':float(values[best])})
        image_predictor.reset_predictor();del image_predictor
        state=predictor.init_state(str(out/'video_frames'),offload_video_to_cpu=True,offload_state_to_cpu=True)
        predictor.add_new_mask(state,frame_idx=anchor,obj_id=1,mask=initial)
        for reverse in (False,True):
            for index,_,logits in predictor.propagate_in_video(state,start_frame_idx=anchor,reverse=reverse):
                masks[index]=(logits[0,0]>0).cpu().numpy()
                if len(masks)%5==0:print('DOCUMENT_CLIP_TRACKED:',len(masks),'/',len(frames),flush=True)
        del state
    limits={'min_pixels':max(16,area*.1),'max_pixels':area*8};timeline=[];replay=[]
    for i,frame in enumerate(frames):
        mask=masks.get(i,np.zeros((h,w),bool));n=int(mask.sum());usable=limits['min_pixels']<=n<=limits['max_pixels']
        bbox=None;image=cv2.imread(str(out/frame['file']))
        if mask.any():
            yy,xx=np.nonzero(mask);bbox=[float(xx.min()/w),float(yy.min()/h),float((xx.max()+1)/w),float((yy.max()+1)/h)]
            overlay=image.copy();overlay[mask]=(0,210,80);image=cv2.addWeighted(image,.7,overlay,.3,0)
        state_name='mask_candidate' if usable else 'unknown_mask_lost' if not n else 'unknown_mask_size_rejected'
        timeline.append({'timestamp_sec':frame['timestamp_sec'],'bbox':bbox,'mask_pixels':n,'state':state_name,'object_identity_verified':False})
        cv2.imwrite(str(out/'overlays'/f'{i:03d}.jpg'),image)
        # Fixed work-surface preview; every SAM input remains a single full native frame.
        focus=image[round(.32*h):round(.68*h),round(.10*w):round(.72*w)]
        ok,encoded=cv2.imencode('.jpg',focus,[cv2.IMWRITE_JPEG_QUALITY,95])
        if not ok:raise ValueError('Local preview encode failed')
        replay.append({'time':frame['timestamp_sec'],'state':state_name,'image':'data:image/jpeg;base64,'+base64.b64encode(encoded).decode()})
    np.savez_compressed(out/'masks.local.npz',document=np.packbits(np.array([masks.get(i,np.zeros((h,w),bool)) for i in range(len(frames))]),axis=-1))
    write_json(out/'observations.local.json',{'timeline':timeline,'mask_size_limits':limits,'identity_verification_established':False})
    summary={'frames':len(frames),'mask_candidate_frames':sum(r['state']=='mask_candidate' for r in timeline),
             'unknown_frames':sum(r['state']!='mask_candidate' for r in timeline),'start_sec':frames[0]['timestamp_sec'],
             'end_sec':frames[-1]['timestamp_sec'],'anchor_sec':anchor_sec,'sample_fps_nominal':args.sample_fps,
             'device':device,'elapsed_sec':round(time.monotonic()-started,2),'tracking_accuracy_not_established':True,
             'document_presentation_established':False,'approved_for_rule_engine':False}
    write_json(out/'summary.local.json',summary)
    payload={'review_session':out.name,'source_session':row['source_session'],'source_video_sha256':row['source_video_sha256'],
             'protocol_sha256':sha(out/'protocol.local.json'),'frames':replay,'anchor_index':anchor}
    page=(ROOT/'scene_mvp/document_track_review.html').read_text()
    (out/'review.html').write_text(page.replace('__PAYLOAD__',json.dumps(payload,ensure_ascii=False).replace('<','\\u003c')),encoding='utf-8')
    write_json(out/'status.json',{'status':'completed','human_mask_review_required':True})
    write_json(ROOT/'local/document-tracking-current.local.json',{'trial':str(out),'report':str(out/'review.html'),'status':'needs_clip_mask_review'})
    print('DOCUMENT_TRACK_READY:',out/'review.html',flush=True);print(json.dumps(summary),flush=True)


if __name__=='__main__':
    try:main()
    except Exception as error:
        if RUN_OUTPUT is not None:write_json(RUN_OUTPUT/'status.json',{'status':'failed','error_type':type(error).__name__,'error':str(error)[:1000]})
        raise
