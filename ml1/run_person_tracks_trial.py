"""Whole-video person tracking from teammate's ML1; local visual review only."""
import argparse,base64,copy,datetime,hashlib,html,json,os,sys,time,colorsys
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'ml2'))
os.environ.update(HF_HUB_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',DO_NOT_TRACK='1')
from backend.pipeline.perception.config import PerceptionConfig
from backend.pipeline.perception.run import perceive_video
from backend.pipeline.perception.scene_tracks import repair_tracks,apply_hysteresis
from backend.pipeline.perception.reflections import annotate_reflections
from backend.pipeline.perception.roles_v2 import assign_temporal_roles
from backend.pipeline.perception.roles import RoleAssigner
from backend.pipeline.video import VideoReader
from PIL import Image,ImageDraw,ImageFont
import cv2,numpy as np


def write_json(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False))

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--video',type=Path,required=True)
 parser.add_argument('--geometry',type=Path,help='Optional camera calibration; never assumed verified')
 args=parser.parse_args()
 if not args.video.is_file():parser.error('Video missing')
 geometry=json.loads(args.geometry.read_text()) if args.geometry else None
 if geometry:RoleAssigner(geometry) # validate before inference
 folder=ROOT/'local'/('tracks-trial-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));folder.mkdir(parents=True)
 status={'status':'running','phase':'person_detection','source_name':args.video.name,'sample_interval_sec':.5,
         'source_commit':'20a184b','semantic_model_used':False,'geometry_supplied':bool(geometry)}
 write_json(folder/'status.json',status);print('Trial directory:',folder,flush=True)
 start=time.monotonic()
 try:
  config=PerceptionConfig(model_path=str(ROOT/'models/rtdetr_r18vd'),refine_scene=False,
                          state_engine_enabled=False,torch_threads=2)
  facts=perceive_video(args.video,config)
  # Same deterministic track refinement used by refine_v5, without SigLIP.
  annotate_reflections(facts);repair_tracks(facts,max_gap_sec=2,require_appearance=True)
  annotate_reflections(facts);apply_hysteresis(facts)
  facts.setdefault('fixtures',[])
  assign_temporal_roles(facts,config.role_settings)
  facts['trial_scope']='RT-DETR + appearance-assisted tracks + geometric reflection hypotheses + temporal roles; no semantic anchors or action recognition'
  if geometry:
   # Preserve automatic hypotheses separately. Final calibrated candidates
   # are applied AFTER temporal refinement, preventing silent overwrite.
   assigner=RoleAssigner(geometry)
   for row in facts['frames']:
    automatic={p['id']:p for p in row['persons']}
    calibrated=assigner.assign(row['persons'],row['timestamp_sec'])
    for person in calibrated:
     old=automatic[person['id']]
     person['temporal_role']=old['role'];person['temporal_role_confidence']=old.get('role_confidence',0)
     person['geometry_role']=person['role'];person['role_source']='provisional_camera_geometry'
    row['persons']=calibrated
   facts['camera_geometry_trial']={'geometry':geometry,'verified':False,
       'source':'manual trial configuration, not a learned or validated camera calibration'}
  write_json(folder/'facts.local.json',facts)
  status['phase']='rendering';write_json(folder/'status.json',status)
  tracks=defaultdict(list)
  for row in facts['frames']:
   for p in row['persons']:tracks[p['id']].append((row['actual_timestamp_sec'],p))
  summaries=[]
  for identifier,rows in sorted(tracks.items()):
   summaries.append({'id':identifier,'observations':len(rows),'first_sec':rows[0][0],'last_sec':rows[-1][0],
      'median_bbox':np.median([p['bbox'] for _,p in rows],axis=0).tolist(),
      'mean_detection_confidence':float(np.mean([p['confidence'] for _,p in rows])),
      'roles':sorted({p['role'] for _,p in rows}),'temporal_roles':sorted({p.get('temporal_role',p['role']) for _,p in rows}),
      'reflection_observations':sum(p.get('is_reflection',False) for _,p in rows),
      'confirmed_observations':sum(p.get('track_confirmed',False) for _,p in rows)})
  write_json(folder/'track-summary.local.json',{'tracks':summaries,'not_identity':True})
  try:font=ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc',14)
  except OSError:font=ImageFont.load_default()
  cards=[]; frame_manifest=[]
  with VideoReader(args.video) as reader:
   for index,row in enumerate(facts['frames']):
    sample=reader.read_at(row['actual_timestamp_sec']);image=Image.fromarray(cv2.cvtColor(sample.frame_bgr,cv2.COLOR_BGR2RGB));draw=ImageDraw.Draw(image)
    width,height=image.size
    if geometry:
     line=geometry['line'];draw.line([(x*width,y*height) for x,y in line],fill='#e92e2e',width=3)
     x,y=geometry['cashier_side_reference'];draw.ellipse((x*width-5,y*height-5,x*width+5,y*height+5),fill='#e92e2e')
    labels=[]
    for person in row['persons']:
     identifier=person['id'];box=person['bbox'];xy=[box[0]*width,box[1]*height,box[2]*width,box[3]*height]
     color=tuple(round(v*255) for v in colorsys.hsv_to_rgb((identifier*.61803398875)%1,.85,.75))
     role=person['role'];reflect=person.get('is_reflection',False)
     label=f'ID {identifier}: {role}' + (' / reflection?' if reflect else '') + (' / tentative' if not person.get('track_confirmed') else '')
     draw.rectangle(xy,outline=color,width=2 if reflect else 3)
     left,top=xy[0],max(0,xy[1]-18);rect=draw.textbbox((left,top),label,font=font)
     draw.rectangle(rect,fill='#ffffff');draw.text((left,top),label,font=font,fill=color)
     labels.append(label)
    file=f'frame-{index:03d}.jpg';image.save(folder/file,quality=90)
    frame_manifest.append({'timestamp_sec':sample.actual_timestamp_sec,'file':file,'persons':row['persons']})
    uri='data:image/jpeg;base64,'+base64.b64encode((folder/file).read_bytes()).decode('ascii')
    cards.append(f'<article><h2>{sample.actual_timestamp_sec:.3f} с</h2><img src="{uri}" alt="Локальный кадр с рамками"><p>'+html.escape('; '.join(labels))+'</p></article>')
  write_json(folder/'frames.local.json',{'frames':frame_manifest})
  rows=''.join('<tr>'+''.join('<td>'+html.escape(str(value))+'</td>' for value in (
      t['id'],t['observations'],f'{t["first_sec"]:.2f}–{t["last_sec"]:.2f}',', '.join(t['temporal_roles']),', '.join(t['roles']),t['reflection_observations']))+'</tr>' for t in summaries)
  status.update(status='completed',phase='finished',elapsed_sec=round(time.monotonic()-start,3),
                timeline_frames=len(facts['frames']),rendered_frames=len(frame_manifest),track_count=len(summaries),
                detector_timing=facts['timing'],review_status='needs_human_review')
  write_json(folder/'status.json',status)
  note=('Красная линия — предварительная граница стола, точка — сторона кассира. Геометрия задана для этой камеры и требует проверки. '
        'Роли по ней назначены после временного алгоритма; исходные временные гипотезы сохранены отдельно.' if geometry else
        'Калибровка стола не задана. Показаны только автоматические временные гипотезы; unknown — допустимый результат.')
  (folder/'report.html').write_text(f'''<!doctype html><html lang="ru"><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Участники и треки — весь X-1</title>
<style>body{{font:16px system-ui;max-width:1200px;margin:30px auto;padding:0 20px;background:#f5f7fb;color:#17212b}}
.note{{background:#fff0ce;padding:20px;border-radius:12px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}}
article{{background:white;padding:16px;border-radius:12px}}img{{width:100%;height:auto}}table{{width:100%;border-collapse:collapse}}td,th{{padding:8px;border:1px solid #ccc;text-align:left}}p{{overflow-wrap:anywhere}}</style>
<h1>Участники и треки по всему ролику</h1><p>{html.escape(args.video.name)} · шаг 0,5 с · {len(frame_manifest)} моментов · {status['elapsed_sec']:.1f} с обработки</p>
<p class="note">{note}<br>ID — временный номер трека, а не личность. cashier_candidate — кандидат в кассиры, visitor_candidate — человек с противоположной стороны, client_candidate — кандидат в клиенты.
reflection? — предположение об отражении. Пока не распознаются руки, банкноты и направление передачи.</p>
<h2>Сводка треков</h2><table><tr><th>ID</th><th>Наблюдений</th><th>Время, с</th><th>Временной алгоритм</th><th>Итоговая гипотеза</th><th>Отражение?</th></tr>{rows}</table>
<h2>Проверь: сохраняется ли номер у человека, верны ли стороны и отражения</h2><div class="grid">{''.join(cards)}</div></html>''',encoding='utf-8')
  print(json.dumps({k:status[k] for k in ('status','elapsed_sec','timeline_frames','rendered_frames','track_count')},ensure_ascii=False),flush=True)
  print('REPORT_READY:',folder/'report.html',flush=True)
 except Exception as error:
  import traceback
  status.update(status='failed',error_type=type(error).__name__,elapsed_sec=round(time.monotonic()-start,3));write_json(folder/'status.json',status)
  (folder/'error.local.txt').write_text(traceback.format_exc());print('Trial failed:',type(error).__name__,flush=True);raise SystemExit(1)


if __name__=='__main__':main()
