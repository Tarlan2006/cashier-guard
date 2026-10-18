"""Local multiscale bag proposals; exploratory low-score boxes require visual review."""
import argparse,base64,datetime,hashlib,json,sys,time
from pathlib import Path
from run_ollama_trial import ROOT,write_json
sys.path.insert(0,str(ROOT.parent/'ml2'))
from backend.pipeline.video import VideoReader
from backend.pipeline.perception.config import PerceptionConfig
from backend.pipeline.perception.detector import get_detector
import cv2

CLASSES={'handbag','backpack','suitcase'}
VIEWS=[(0,0,1,1),(0,0,.65,.65),(.35,0,1,.65),(0,.35,.65,1),(.35,.35,1,1)]

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--video',type=Path,required=True);p.add_argument('--times',type=float,nargs='+',default=[5,10,15,18,20]);args=p.parse_args()
 digest=hashlib.sha256(args.video.read_bytes()).hexdigest();manifest=json.loads((ROOT/'outputs/forte_dataset_manifest.json').read_text())
 if not any(v['sha256']==digest and v['filename']==args.video.name for v in manifest['videos']):p.error('Uninspected video')
 out=ROOT/'local'/('bag-probe-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir();start=time.monotonic()
 detector=get_detector(PerceptionConfig(model_path=str(ROOT/'models/rtdetr_r18vd'),refine_scene=False,state_engine_enabled=False,torch_threads=2));records=[];cards=[]
 with VideoReader(args.video) as reader:
  for i,t in enumerate(args.times):
   if not 0<=t<reader.metadata.duration_sec:p.error('Time outside video')
   sample=reader.read_at(t);image=sample.frame_bgr;h,w=image.shape[:2];proposals=[]
   for vi,b in enumerate(VIEWS):
    x1,y1,x2,y2=[round(b[0]*w),round(b[1]*h),round(b[2]*w),round(b[3]*h)];crop=image[y1:y2,x1:x2]
    detections=detector.predict_batch([crop],object_threshold=.2)[0]
    for d in detections:
     if d['class'] not in CLASSES:continue
     a=d['bbox'];box=[(x1+a[0]*(x2-x1))/w,(y1+a[1]*(y2-y1))/h,(x1+a[2]*(x2-x1))/w,(y1+a[3]*(y2-y1))/h]
     proposals.append({'class':d['class'],'confidence':d['confidence'],'bbox':box,'view':vi})
   records.append({'timestamp_sec':sample.actual_timestamp_sec,'proposals':proposals})
   annotated=image.copy()
   for d in proposals:
    a=d['bbox'];x1,y1,x2,y2=[round(a[0]*w),round(a[1]*h),round(a[2]*w),round(a[3]*h)]
    cv2.rectangle(annotated,(x1,y1),(x2,y2),(255,80,0),2);cv2.putText(annotated,d['class']+' '+str(round(d['confidence'],2)),(x1,max(15,y1-4)),cv2.FONT_HERSHEY_SIMPLEX,.4,(255,80,0),1)
   name=f'frame-{i:02d}.jpg';cv2.imwrite(str(out/name),annotated);uri=base64.b64encode((out/name).read_bytes()).decode()
   cards.append('<article><h2>'+str(round(sample.actual_timestamp_sec,3))+' с · кандидатов: '+str(len(proposals))+'</h2><img src="data:image/jpeg;base64,'+uri+'"></article>')
 summary={'target':'bag_proposals_only','video_sha256':digest,'times':len(records),'view_count':len(VIEWS),'candidate_boxes':sum(len(r['proposals']) for r in records),'moments_with_candidate':sum(bool(r['proposals']) for r in records),'object_score_cutoff':.2,'score_is_calibrated':False,'new_model_trained':False,'unattended_bag_detection_established':False,'elapsed_sec':round(time.monotonic()-start,2)}
 write_json(out/'proposals.local.json',{'summary':summary,'frames':records})
 (out/'report.html').write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'"><style>body{font:18px system-ui;max-width:1200px;margin:30px auto;padding:20px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:18px}img{width:100%}</style><h1>Проверка сумки: общий кадр и четыре увеличенных участка</h1><p>RT-DETR COCO; классы handbag/backpack/suitcase. Порог 0,2 — исследовательский, слабые рамки требуют проверки. Рамки одного предмета могут повторяться из разных масштабов. Модель не обучалась на этих кадрах. Наличие инкассаторской сумки и нарушение не установлены.</p><div class="grid">'+''.join(cards)+'</div></html>')
 print('BAG_PROBE_READY:',out/'report.html');print(json.dumps(summary))

if __name__=='__main__':main()
