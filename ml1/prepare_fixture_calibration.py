"""Prepare separate cabinet-state labels; no predictions or expected states shown."""
import argparse,base64,datetime,hashlib,html,json,re,sys
from pathlib import Path
from run_ollama_trial import ROOT,write_json
sys.path.insert(0,str(ROOT.parent/'ml2'))
from backend.pipeline.video import VideoReader
import cv2

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--videos',type=Path,nargs='+',required=True);p.add_argument('--validation-model',type=Path);p.add_argument('--reference-profile',type=Path);args=p.parse_args()
 meta=None;model=None
 if args.validation_model:
  model=args.validation_model.resolve()
  if not model.is_relative_to((ROOT/'local').resolve()):p.error('Local cabinet model required')
  meta=json.loads((model/'model-metadata.local.json').read_text())
  if meta.get('target_kind')!='cash_storage_cabinet':p.error('Cabinet model required')
  if hashlib.sha256((model/'cabinet-model.npz').read_bytes()).hexdigest()!=meta['model_sha256']:p.error('Model changed')
 reference=json.loads(args.reference_profile.read_text()) if args.reference_profile else None
 if reference and (not reference.get('confirmed') or reference.get('fixture_kind')!='cash_storage_cabinet'):p.error('Confirmed cabinet reference required')
 manifest=json.loads((ROOT/'outputs/forte_dataset_manifest.json').read_text());links=[]
 batch=ROOT/'local'/('cabinet-calibration-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));batch.mkdir()
 for video in args.videos:
  digest=hashlib.sha256(video.read_bytes()).hexdigest()
  if meta and digest in {v['sha256'] for v in meta['source_profiles']}:p.error('Training video cannot be independent validation')
  if not any(v['sha256']==digest and v['filename']==video.name for v in manifest['videos']):p.error('Uninspected video')
  out=ROOT/'local'/('cabinet-session-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir();rows=[]
  with VideoReader(video) as reader:
   for i,sample in enumerate(reader.iter_samples(.5)):
    file=f'frame-{i:03d}.jpg';ok,data=cv2.imencode('.jpg',sample.frame_bgr,[cv2.IMWRITE_JPEG_QUALITY,90])
    if not ok:raise ValueError('JPEG encode failed')
    (out/file).write_bytes(data.tobytes());h,w=sample.frame_bgr.shape[:2]
    rows.append({'timestamp_sec':sample.actual_timestamp_sec,'file':file,'width':w,'height':h,'persons':[]})
  profile={'schema_version':1,'profile_kind':'fixture_only','fixture_kind':'cash_storage_cabinet',
           'source_session':out.name,'source_video_sha256':digest,'confirmed':False,'confirmed_at':None,
           'zones':{},'roles':{},'fixture_frame_labels':[],'stability_sec':1,'max_gap_sec':1}
  if reference:
   profile['zones']['safe_zone']=reference['zones']['safe_zone']
   profile['zone_source']='proposal_from_reference_needs_review'
  session={'schema_version':1,'session_id':out.name,'source_name':video.name,'source_video':str(video.resolve()),
           'source_video_sha256':digest,'frames':rows,'initial_roles':{},'privacy':'local_only','target_kind':'cash_storage_cabinet'}
  write_json(out/'session.local.json',session);write_json(out/'calibration-draft.local.json',profile)
  if meta:write_json(out/'validation-plan.local.json',{'target_kind':'cash_storage_cabinet','model_folder':str(model),'model_sha256':meta['model_sha256'],'model_metadata_sha256':hashlib.sha256((model/'model-metadata.local.json').read_bytes()).hexdigest(),'target_video_sha256':digest,'feature_spec':meta['feature_spec'],'ground_truth_prefilled':False,'predictions_shown_to_annotator':False,'training_on_this_video':False})
  payload=dict(session,initial_profile=profile,profile_kind='fixture_only',fixture_kind='cash_storage_cabinet',
               frame_label_key='fixture_frame_labels',required_zones=['safe_zone'],initial_zone='safe_zone',hide_roles=True,
               require_all_door_labels=True,export_suffix='-cabinet-calibration.json',restore_revision='cabinet-v1',
               frames=[dict(f,image='data:image/jpeg;base64,'+base64.b64encode((out/f['file']).read_bytes()).decode()) for f in rows])
  text=(ROOT/'scene_mvp/calibration.html').read_text().replace('__PAYLOAD__',json.dumps(payload,ensure_ascii=False).replace('<','\\u003c'))
  text=text.replace('<h1>Калибровка сцены: зоны и роли</h1>','<h1>Дверца шкафа для денег: '+html.escape(video.name)+'</h1>')
  a=text.index('<aside>');b=text.index('</aside>',a)+8
  text=text[:a]+'<aside>Обведи металлический шкаф, включая пространство открытой створки. Затем разметь открыта/закрыта интервалами. Если человек закрывает обзор или состояние неразличимо, выбирай «Не различима». Состояние замка и наличие денег здесь не устанавливаются.</aside>'+text[b:]
  a=text.index('<p><b>1.</b>');b=text.index('</p>',a)+4
  text=text[:a]+'<p><b>1.</b> Выдели шкаф с открытой створкой. <b>2.</b> Проверь область на нескольких кадрах и разметь состояния интервалами. <b>3.</b> Подтверди и сохрани JSON. Предсказаний и готовых меток нет.</p>'+text[b:]
  text=re.sub(r'<select id="zone">.*?</select>','<select id="zone"><option value="safe_zone">Шкаф, включая открытую створку</option></select>',text,count=1,flags=re.S)
  text=text.replace('Дверь на текущем кадре:','Дверца шкафа на текущем кадре:').replace('Метки двери:','Метки дверцы шкафа:')
  (out/'calibrate.html').write_text(text,encoding='utf-8');links.append({'video':video.name,'session':str(out),'frames':len(rows),'labels_prefilled':0})
 index='<!doctype html><html lang="ru"><meta charset="utf-8"><style>body{font:20px system-ui;max-width:900px;margin:40px auto;padding:20px}li{margin:25px 0}</style><h1>Следующий объект: дверца шкафа для денег</h1><p>Два видео, состояния размечаются самостоятельно. Это отдельный набор для обучения модели шкафа; входная дверь сюда не относится. Открытая створка не устанавливает правовое нарушение.</p><ul>'+''.join('<li><a href="'+html.escape('../'+Path(x['session']).name+'/calibrate.html',quote=True)+'">'+html.escape(x['video'])+'</a> — '+str(x['frames'])+' кадров</li>' for x in links)+'</ul></html>'
 (batch/'index.html').write_text(index);write_json(batch/'sessions.local.json',{'target_kind':'cash_storage_cabinet','sessions':links})
 print('CABINET_CALIBRATION_READY:',batch/'index.html');print(json.dumps({'videos':len(links),'frames':sum(x['frames'] for x in links),'labels_prefilled':0}))

if __name__=='__main__':main()
