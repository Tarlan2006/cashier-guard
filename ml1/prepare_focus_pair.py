"""Crop around human-confirmed actors; re-detect each instant, no bank labels."""
import argparse,base64,datetime,html,json,sys,time,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'ml2'))
from backend.pipeline.video import VideoReader
from backend.pipeline.perception.detector import get_detector
from backend.pipeline.perception.config import PerceptionConfig
from backend.pipeline.perception.tracking import bbox_iou,validated_bbox
from scipy.optimize import linear_sum_assignment
from PIL import Image,ImageDraw,ImageFont
import cv2,numpy as np


def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--video',type=Path,required=True)
 parser.add_argument('--tracks',type=Path,required=True)
 parser.add_argument('--start-sec',type=float,default=21)
 parser.add_argument('--end-sec',type=float,default=24)
 args=parser.parse_args();source=args.tracks.resolve()
 if not source.is_relative_to((ROOT/'local').resolve()):parser.error('Use local track output only')
 mapping=json.loads((source/'user-role-map.local.json').read_text())
 if mapping.get('client_mapping_needs_clarification',True):parser.error('Human role mapping required')
 selected=[mapping['cashier_id'],mapping['client_id']]
 if len(set(selected))!=2:parser.error('Two distinct human-confirmed IDs required')
 baseline=json.loads((source/'frames.local.json').read_text())['frames']
 refs=[p['bbox'] for f in baseline if args.start_sec-.5<=f['timestamp_sec']<=args.end_sec+.5 for p in f['persons'] if p['id'] in selected]
 if not refs:parser.error('Confirmed actors unavailable in selected segment')
 boxes=np.asarray(refs)
 # Workspace derives from actor boxes, not a labelled cash/card location.
 roi=np.array([max(0,boxes[:,0].min()-.10),max(0,boxes[:,1].min()-.05),min(1,boxes[:,2].max()+.10),min(1,boxes[:,3].max()+.05)])
 folder=ROOT/'local'/('focus-pair-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));folder.mkdir(parents=True)
 shutil.copyfile(source/'user-role-map.local.json',folder/'user-role-map.local.json')
 start=time.monotonic();detector=get_detector(PerceptionConfig(model_path=str(ROOT/'models/rtdetr_r18vd'),refine_scene=False,state_engine_enabled=False))
 try:font=ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc',12)
 except OSError:font=ImageFont.load_default()
 colors={selected[0]:'#1261b0',selected[1]:'#c14b00'}
 frames=[];figures=[]
 with VideoReader(args.video) as reader:
  targets=np.arange(args.start_sec,args.end_sec+.001,.25)
  for index,target in enumerate(targets):
   sample=reader.read_at(float(target));reference=min(baseline,key=lambda f:abs(f['timestamp_sec']-sample.actual_timestamp_sec))
   expected={p['id']:p for p in reference['persons'] if p['id'] in selected}
   observed=[p for p in detector.predict_batch([sample.frame_bgr])[0] if p['class']=='person']
   keys=list(expected);matched=[]
   if keys and observed:
    overlaps=np.array([[bbox_iou(validated_bbox(expected[key]['bbox']),validated_bbox(p['bbox'])) for p in observed] for key in keys])
    rows,columns=linear_sum_assignment(1-overlaps)
    for a,b in zip(rows,columns):
     if overlaps[a,b]>=.2:matched.append((keys[a],observed[b],float(overlaps[a,b])))
   image=Image.fromarray(cv2.cvtColor(sample.frame_bgr,cv2.COLOR_BGR2RGB));width,height=image.size
   bounds=(int(roi[0]*width),int(roi[1]*height),int(np.ceil(roi[2]*width)),int(np.ceil(roi[3]*height)))
   crop=image.crop(bounds);draw=ImageDraw.Draw(crop);cw,ch=crop.size;persons=[]
   for identifier,p,overlap in matched:
    b=p['bbox'];box=[(b[0]*width-bounds[0])/cw,(b[1]*height-bounds[1])/ch,(b[2]*width-bounds[0])/cw,(b[3]*height-bounds[1])/ch]
    box=np.clip(box,0,1).tolist();color=colors[identifier]
    # Keep the label connected to its person box, rather than floating near
    # another actor. Roles come from the user's review, not model inference.
    xy=[box[0]*cw,box[1]*ch,box[2]*cw,box[3]*ch]
    draw.rectangle(xy,outline=color,width=2)
    label=f'ID {identifier} '+('CASHIER' if identifier==selected[0] else 'CLIENT')
    extent=draw.textbbox((0,0),label,font=font);tw=extent[2]-extent[0];th=extent[3]-extent[1]
    middle=(xy[0]+xy[2])/2
    left=max(2,min(cw-tw-3,middle-tw/2))
    preferred=xy[3]+3 if identifier==selected[0] else xy[1]-th-8
    top=max(2,min(ch-th-4,preferred))
    anchor_y=xy[3] if identifier==selected[0] else xy[1]
    draw.line((middle,anchor_y,left+tw/2,top+th/2),fill=color,width=2)
    extent=draw.textbbox((left,top),label,font=font)
    draw.rectangle((extent[0]-2,extent[1]-2,extent[2]+2,extent[3]+2),fill='white',outline=color,width=1)
    draw.text((left,top),label,font=font,fill=color)
    persons.append({'id':identifier,'bbox':box,'source_bbox':b,'confidence':p['confidence'],
       'role':'user_verified_cashier' if identifier==selected[0] else 'user_verified_client',
       'observed':True,'track_confirmed':True,'is_reflection':False,'source_id_association_iou':overlap})
   filename=f'frame-{index:03d}.jpg';crop.save(folder/filename,quality=95)
   frames.append({'timestamp_sec':sample.actual_timestamp_sec,'file':filename,'persons':persons,'source_roi_xyxy':roi.tolist()})
   uri='data:image/jpeg;base64,'+base64.b64encode((folder/filename).read_bytes()).decode('ascii')
   figures.append(f'<article><h2>{sample.actual_timestamp_sec:.3f} с</h2><img src="{uri}" alt="Рабочая область"></article>')
 (folder/'frames.local.json').write_text(json.dumps({'frames':frames},ensure_ascii=False,indent=2))
 status={'status':'completed','source_name':args.video.name,'input_scope':'focused_segment','sample_interval_sec':.25,
    'sampled_range_sec':[args.start_sec,args.end_sec],'timeline_frames':len(frames),
    'view_note':'Рабочая область вокруг подтверждённых ID 1 и ID 4. Внешние участники исключены из этого эксперимента; это не универсальная классификация отражений.',
    'selected_actor_ids':selected,'source_tracks':str(source),'roi_xyxy':roi.tolist(),
    'frame_id_sets':[[p['id'] for p in f['persons']] for f in frames],'elapsed_sec':round(time.monotonic()-start,3)}
 (folder/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2))
 (folder/'report.html').write_text('''<!doctype html><html lang="ru"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'"><style>body{font:16px system-ui;max-width:1000px;margin:30px auto}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}img{width:100%}</style><h1>Вход новой короткой проверки</h1><p>Кадры 21–24 с, шаг 0,25 с. Рабочая область получена из рамок подтверждённых участников с запасом. Сопоставление новых детекций с номерами треков — геометрическая гипотеза; проверь подписи. Внешние треки не подаются модели.</p><div class="grid">'''+''.join(figures)+'</div></html>',encoding='utf-8')
 print('FOCUS_SOURCE_READY:',folder,flush=True)
 print(json.dumps({'frames':len(frames),'redetected_primary_actor_observations':sum(len(f['persons']) for f in frames),'elapsed_sec':status['elapsed_sec']}),flush=True)


if __name__=='__main__':main()
