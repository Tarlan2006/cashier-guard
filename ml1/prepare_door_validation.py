"""Prepare an unseen door video with no predictions or prefilled ground truth."""
import argparse,base64,copy,datetime,hashlib,json,sys
from pathlib import Path
from run_ollama_trial import ROOT,write_json
sys.path.insert(0,str(ROOT.parent/'ml2'))
from backend.pipeline.video import VideoReader
import cv2
from scene_mvp.door_sequence_report import temporal_plan

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--video',type=Path,required=True);p.add_argument('--model',type=Path,required=True);p.add_argument('--reference-profile',type=Path,required=True);p.add_argument('--temporal',action='store_true',help='Freeze causal confirmation before annotation');args=p.parse_args()
 model=args.model.resolve();meta=json.loads((model/'model-metadata.local.json').read_text());sha=hashlib.sha256(args.video.read_bytes()).hexdigest()
 if sha in {s['sha256'] for s in meta['source_profiles']}:raise ValueError('Training video cannot be independent validation')
 digest=hashlib.sha256((model/'door-model.npz').read_bytes()).hexdigest()
 if digest!=meta['model_sha256']:raise ValueError('Model changed')
 manifest=json.loads((ROOT/'outputs/forte_dataset_manifest.json').read_text())
 if not any(v['sha256']==sha and v['filename']==args.video.name for v in manifest['videos']):raise ValueError('Uninspected video')
 reference=json.loads(args.reference_profile.read_text());box=reference['zones']['door_zone'];out=ROOT/'local'/('door-validation-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir();rows=[]
 with VideoReader(args.video) as reader:
  for i,sample in enumerate(reader.iter_samples(.5)):
   name=f'frame-{i:03d}.jpg';ok,encoded=cv2.imencode('.jpg',sample.frame_bgr,[cv2.IMWRITE_JPEG_QUALITY,90])
   if not ok:raise ValueError('Encode failed')
   (out/name).write_bytes(encoded.tobytes());h,w=sample.frame_bgr.shape[:2];rows.append({'timestamp_sec':sample.actual_timestamp_sec,'file':name,'width':w,'height':h,'persons':[]})
 profile={'schema_version':1,'profile_kind':'door_only','camera_id':out.name,'source_session':out.name,'source_video_sha256':sha,'confirmed':False,'confirmed_at':None,'zones':{'door_zone':copy.deepcopy(box)},'roles':{},'door_frame_labels':[],'stability_sec':1,'max_gap_sec':1,'door_zone_source':'proposal_from_reference_needs_review'}
 session={'schema_version':1,'session_id':out.name,'source_name':args.video.name,'source_video':str(args.video.resolve()),'source_video_sha256':sha,'frames':rows,'initial_roles':{},'privacy':'local_only'};write_json(out/'session.local.json',session);write_json(out/'calibration-draft.local.json',profile)
 plan={'schema_version':1,'model_folder':str(model),'model_sha256':digest,'model_metadata_sha256':hashlib.sha256((model/'model-metadata.local.json').read_bytes()).hexdigest(),'target_video_sha256':sha,'ground_truth_prefilled':False,'predictions_shown_to_annotator':False,'training_on_this_video':False,'feature_spec':meta['feature_spec']}
 if args.temporal:plan['temporal']=temporal_plan()
 write_json(out/'validation-plan.local.json',plan)
 payload=dict(session,initial_profile=profile,initial_roles={},restore_revision='blind-'+digest[:12],profile_kind='door_only',required_zones=['door_zone'],initial_zone='door_zone',hide_roles=True,require_all_door_labels=True,export_suffix='-door-validation.json',frames=[dict(f,image='data:image/jpeg;base64,'+base64.b64encode((out/f['file']).read_bytes()).decode()) for f in rows])
 text=(ROOT/'scene_mvp/calibration.html').read_text().replace('__PAYLOAD__',json.dumps(payload,ensure_ascii=False).replace('<','\\u003c'))
 text=text.replace('<h1>Калибровка сцены: зоны и роли</h1>','<h1>Независимая проверка двери: '+args.video.name+'</h1>')
 a=text.index('<p><b>1.</b>');b=text.index('</p>',a)+4;text=text[:a]+'<p><b>1.</b> Проверь область двери (она перенесена только как предложение). <b>2.</b> Разметь открыта/закрыта, используя интервалы ниже. Если состояние не различимо, отметь это отдельно. <b>3.</b> Подтверди и экспортируй JSON. Предсказания модели скрыты, чтобы не влиять на твою разметку. Роли людей здесь не нужны.</p>'+text[b:]
 (out/'validate.html').write_text(text,encoding='utf-8');print('DOOR_VALIDATION_READY:',out/'validate.html',flush=True);print(json.dumps({'frames':len(rows),'unseen_video':True,'prefilled_labels':0,'model_frozen':True}))
if __name__=='__main__':main()
