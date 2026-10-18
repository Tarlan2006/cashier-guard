"""Build local scene calibration from cached perception and raw video frames."""
import argparse,base64,copy,datetime,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'ml2'))
from backend.pipeline.video import VideoReader
import cv2

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--video',type=Path,required=True);p.add_argument('--tracks',type=Path,required=True);args=p.parse_args();tracks=args.tracks.resolve()
 if not tracks.is_relative_to((ROOT/'local').resolve()):p.error('Local tracks required')
 facts=json.loads((tracks/'facts.local.json').read_text());status=json.loads((tracks/'status.json').read_text())
 if status['status']!='completed' or facts['video']['name']!=args.video.name:p.error('Video/tracks mismatch')
 sha=hashlib.sha256(args.video.read_bytes()).hexdigest();manifest=json.loads((ROOT/'outputs/forte_dataset_manifest.json').read_text())
 if not any(v['sha256']==sha and v['filename']==args.video.name for v in manifest['videos']):p.error('Video does not match inspected dataset')
 folder=ROOT/'local'/('scene-session-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));folder.mkdir();rows=[]
 with VideoReader(args.video) as reader:
  if abs(reader.metadata.duration_sec-facts['video']['duration_sec'])>.1:p.error('Cached track timeline mismatch')
  for i,row in enumerate(facts['frames']):
   t=row.get('actual_timestamp_sec',row['timestamp_sec']);sample=reader.read_at(t);ok,encoded=cv2.imencode('.jpg',sample.frame_bgr,[cv2.IMWRITE_JPEG_QUALITY,90])
   if not ok:raise ValueError('Frame encode failed')
   name=f'frame-{i:03d}.jpg';(folder/name).write_bytes(encoded.tobytes());h,w=sample.frame_bgr.shape[:2]
   persons=[{k:p.get(k) for k in ['id','bbox','confidence','observed','is_reflection','counted','uncertain','track_confirmed']} for p in row['persons']]
   rows.append({'timestamp_sec':sample.actual_timestamp_sec,'file':name,'width':w,'height':h,'persons':persons})
 roles={};role_file=tracks/'user-role-map.local.json'
 if role_file.exists():
  role=json.loads(role_file.read_text())
  if not role.get('client_mapping_needs_clarification',True):roles={'cashier_ids':[role['cashier_id']],'client_ids':[role['client_id']]}
 session={'schema_version':1,'session_id':folder.name,'source_name':args.video.name,'source_video_sha256':sha,'source_video':str(args.video.resolve()),'tracks_folder':str(tracks),'frames':rows,'initial_roles':roles,'source_commit':'20a184b','privacy':'local_only','role_ids_scope':'this_cached_track_run_only'}
 (folder/'session.local.json').write_text(json.dumps(session,ensure_ascii=False,indent=2))
 payload=dict(session,frames=[dict(r,image='data:image/jpeg;base64,'+base64.b64encode((folder/r['file']).read_bytes()).decode()) for r in rows]);text=(ROOT/'scene_mvp/calibration.html').read_text().replace('__PAYLOAD__',json.dumps(payload,ensure_ascii=False).replace('<','\\u003c'));(folder/'calibrate.html').write_text(text,encoding='utf-8')
 (folder/'calibration-draft.local.json').write_text(json.dumps({'schema_version':1,'source_video_sha256':sha,'confirmed':False,'zones':{},'roles':roles,'stability_sec':1,'max_gap_sec':1,'source_session':folder.name},indent=2))
 print('SCENE_CALIBRATION_READY:',folder/'calibrate.html',flush=True);print(json.dumps({'frames':len(rows),'prefilled_role_count':sum(len(v) for v in roles.values()),'geometry_confirmed':False,'new_inference':False}))
if __name__=='__main__':main()
