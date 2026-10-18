"""Export local review evidence plus an ML1-compatible observations payload."""
import argparse,base64,datetime,hashlib,json,math,shutil,zipfile
from io import BytesIO
from pathlib import Path
from PIL import Image
from run_ollama_trial import ROOT

DESCRIPTIONS={
 'bag_observed_during_cashier_departure':'Маска предмета, обозначенного человеком как сумка, оставалась рядом с исходной областью при наблюдаемом отходе кассира. Правильность сопровождения и контекст требуют проверки.',
 'cash_observed_during_cashier_departure':'Маска предмета, обозначенного человеком как деньги, оставалась рядом с исходной областью при наблюдаемом отходе кассира. Самостоятельное распознавание банкнот и нарушение не установлены.',
 'documents_observed_during_cashier_departure':'Маска предмета, обозначенного человеком как документ или журнал, оставалась рядом с исходной областью при наблюдаемом отходе кассира. Содержимое документа и нарушение не установлены.',
 'additional_visitor_near_service_zone':'При наблюдаемом кассире один посетитель находится в зоне обслуживания, рамка другого частично пересекает эту зону. Начало обслуживания и передача предмета не установлены; требуется проверка кадров.',
 'workplace_departure':'Подтверждённый для этого видео трек кассира наблюдается вне рабочей зоны после нахождения внутри неё. Выход из помещения и нарушение регламента не установлены.',
 'multiple_visitors_in_service_zone':'В зоне обслуживания одновременно наблюдаются несколько разных треков посетителей. Начало обслуживания второго клиента не установлено.',
 'door_open_while_cashier_away':'Экспериментальная локальная модель определяет дверь как открытую одновременно с наблюдаемым отходом кассира от рабочей зоны. Ответ требует проверки по кадрам; нарушение не установлено.'}


def jpeg(data):
 if len(base64.b64encode(data))>4_000_000:raise ValueError('Evidence too large')
 with Image.open(BytesIO(data)) as im:
  if im.format!='JPEG' or im.width*im.height>8_000_000 or max(im.size)>8192:raise ValueError('Invalid JPEG')
  im.verify()
 with Image.open(BytesIO(data)) as im:im.load()
 return base64.b64encode(data).decode('ascii')


def make_payload(result,session,source,duration):
 if not math.isfinite(duration) or duration<=0:raise ValueError('Invalid duration')
 if result['status']!='partial':raise ValueError('Confirmed partial scene required')
 frames={round(f['timestamp_sec'],3):f for f in session['frames']}
 source=Path(source).resolve();events=[];details=[]
 for i,signal in enumerate(result['signals']+result.get('experimental_signals',[])):
  a,b=signal['start_sec'],signal['end_sec']
  if not all(math.isfinite(t) for t in (a,b)) or not 0<=a<=b<=duration or a>=duration:raise ValueError('Event time outside video')
  if signal['legal_violation_established']:raise ValueError('Review export cannot assert violation')
  kind=signal['type']
  if kind not in DESCRIPTIONS:raise ValueError('Unsupported observation')
  if kind=='door_open_while_cashier_away' and signal.get('source')!='experimental_door_classifier':raise ValueError('Expected model source')
  evidence=[]
  for t in dict.fromkeys(signal['evidence_times_sec']):
   if not math.isfinite(t) or not 0<=t<duration:raise ValueError('Evidence time outside video')
   frame=frames.get(round(t,3))
   if frame is None:raise ValueError('Evidence must match decoded source frame')
   path=(source/frame['file']).resolve()
   if not path.is_relative_to(source):raise ValueError('Evidence outside session')
   evidence.append({'timestamp_sec':frame['timestamp_sec'],'image_base64':jpeg(path.read_bytes())})
  if not 1<=len(evidence)<=3:raise ValueError('One to three evidence frames required')
  identifier=f"scene-{session['source_video_sha256'][:12]}-{i+1}"
  events.append({'id':identifier,'start_sec':a,'end_sec':b,'description':DESCRIPTIONS[kind],'evidence_frames':evidence})
  details.append({'id':identifier,'type':kind,'participant_ids':signal['participant_ids'],
                  'status':signal['status'],'source':signal.get('source','calibrated_track_geometry'),
                  'rule_id':None,'legal_violation_established':False})
 if len(events)>100:raise ValueError('Too many observations')
 payload={'schema_version':'1.0','events':events}
 if len(json.dumps(payload).encode())>32*1024*1024:raise ValueError('Payload exceeds contract limit')
 return payload,details


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--scene-result',nargs='+',type=Path,required=True);args=p.parse_args()
 out=ROOT/'local'/('team-handoff-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir()
 manifest=json.loads((ROOT/'outputs/forte_dataset_manifest.json').read_text());index=[]
 for number,folder in enumerate(args.scene_result,1):
  folder=folder.resolve()
  if not folder.is_relative_to((ROOT/'local').resolve()):p.error('Use local scene results')
  status=json.loads((folder/'status.json').read_text())
  if status['status']!='completed':p.error('Completed analysis required')
  object_profile=folder/'calibration.local.json';model_summary=None
  if object_profile.exists() and (folder/'summary.local.json').exists():
   profile=json.loads(object_profile.read_text());source=(ROOT/'local'/profile['source_session']).resolve();sha=profile['source_video_sha256'];model_summary=json.loads((folder/'summary.local.json').read_text())
  else:source=Path(status['source_session']).resolve();sha=status['source_video_sha256']
  if not source.is_relative_to((ROOT/'local').resolve()):p.error('Use local scene session')
  session=json.loads((source/'session.local.json').read_text());result=json.loads((folder/'observations.local.json').read_text())
  if session['source_video_sha256']!=sha:p.error('Video mismatch')
  entry=next(v for v in manifest['videos'] if v['sha256']==session['source_video_sha256'])
  duration=entry['metadata']['duration_sec'];payload,details=make_payload(result,session,source,duration)
  target=out/f'case-{number}';target.mkdir()
  meta={'review_schema_version':'cashier-review/1.0','analysis_status':'partial','analysis_complete':False,
        'verdict':None,'requires_human_review':True,'source_video_sha256':session['source_video_sha256'],
        'filename':session['source_name'],'duration_sec':duration,'coverage':result['coverage'],
        'event_metadata':details,'experimental_door_provenance':result.get('experimental_door_provenance'),
        'limitations':['cash_and_hand_transfer_not_checked','identity_document_not_checked','screen_lock_not_checked',
                       'roles_and_geometry_require_video_bound_human_calibration','no_legal_verdict']}
  if model_summary is not None:
   meta.update(review_schema_version='cashier-object-review/1.0',object_tracking_model=model_summary['model'],object_tracking_summary=model_summary,
               target_kind_source='human_video_bound_calibration',object_trajectory=[{'timestamp_sec':row['timestamp_sec'],'cashier_presence':row['cashier_presence'],'departure_supported':row['departure_supported'],'object':row.get('experimental_object',row.get('experimental_bag',{'state':'unknown','bbox':None}))} for row in result['timeline']],
               limitations=['object_kind_is_human_seeded','mask_identity_requires_review','lost_mask_or_person_is_unknown','offline_sampled_video_not_all_original_frames','identity_document_and_screen_lock_not_checked','no_legal_verdict'])
  for name,data in [('ml1-observations.json',payload),('review-result.json',dict(meta,observations=payload))]:
   (target/name).write_text(json.dumps(data,ensure_ascii=False,indent=2))
  shutil.copy2(folder/'report.html',target/'report.html')
  index.append({'case':target.name,'filename':session['source_name'],'events':len(payload['events']),
                'review_result':target.name+'/review-result.json','ml1_payload':target.name+'/ml1-observations.json',
                'report':target.name+'/report.html','payload_sha256':hashlib.sha256((target/'ml1-observations.json').read_bytes()).hexdigest()})
 (out/'index.local.json').write_text(json.dumps({'analysis_status':'partial','cases':index},ensure_ascii=False,indent=2))
 shutil.copy2(ROOT/'TEAM_HANDOFF.txt',out/'TEAM_HANDOFF.txt')
 (out/'index.html').write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><title>Cashier Guard — локальный прототип</title><style>body{font:20px system-ui;max-width:900px;margin:50px auto;padding:20px}li{margin:24px 0}</style><h1>Cashier Guard: наблюдения для проверки</h1><p>Реальные локальные вычисления. Частичный анализ, без правового вердикта. Это демонстрационные примеры, не оценка общей точности.</p><ul>'+''.join('<li><a href="'+x['report']+'">'+x['filename']+'</a> · наблюдений: '+str(x['events'])+' · <a href="'+x['review_result']+'">JSON для интерфейса</a></li>' for x in index)+'</ul><p>Пустой список наблюдений не означает отсутствие нарушений. Пакет содержит локальные банковские кадры.</p></html>',encoding='utf-8')
 with zipfile.ZipFile(str(out)+'.zip','w',zipfile.ZIP_DEFLATED) as archive:
  for file in out.rglob('*'):
   if file.is_file():archive.write(file,arcname=out.name+'/'+str(file.relative_to(out)))
 print('TEAM_HANDOFF_READY:',out/'index.html')
 print(json.dumps({'cases':[{'case':x['case'],'events':x['events']} for x in index],'zip_bytes':Path(str(out)+'.zip').stat().st_size,'verdicts':0}))

if __name__=='__main__':main()
