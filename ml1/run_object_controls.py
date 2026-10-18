"""Local independent crop controls, neutral prompt; expected labels remain unverified."""
import argparse,base64,datetime,html,json,os,shutil,socket,subprocess,sys,time
from pathlib import Path
from run_ollama_trial import ROOT,QWEN_MODEL,LOCAL_OLLAMA,request,write_json
sys.path.insert(0,str(ROOT.parent/'ml2'))
from backend.pipeline.video import VideoReader
from PIL import Image
import cv2

KINDS=['banknotes','card','document','other','none','unclear']
def schema():
 props={'visible_evidence':{'type':'string','maxLength':240},'classification':{'type':'string','enum':KINDS},'confidence':{'type':'string','enum':['low','medium','high']},'limitation':{'type':'string','maxLength':160}}
 return {'type':'object','properties':props,'required':list(props),'additionalProperties':False}


def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--video',type=Path,required=True)
 args=parser.parse_args()
 with socket.socket() as probe:
  try:probe.bind(('127.0.0.1',11435))
  except OSError:parser.error('Private trial port occupied')
 folder=ROOT/'local'/('object-controls-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));folder.mkdir()
 status={'status':'preparing','model':QWEN_MODEL,'source_name':args.video.name,'cloud_disabled':True,'review_status':'needs_human_review','crop_method':'manual_fixed_camera_geometry_not_hand_detection','expected_class_supplied':False}
 start=time.monotonic();server=None;images=[];details=[]
 try:
  # Geometry comes from the user's supplied scene screenshots, not model output.
  # Candidate labels are for human review only; no real crop is ground truth yet.
  cases=[('A',21,[.39,.47,.56,.55],'held_object_candidate'),
         ('B',21,[.26,.49,.38,.56],'stationary_card_candidate'),
         ('C',21,[.72,.22,.86,.30],'empty_wall_candidate'),
         ('D',22,[.39,.47,.56,.55],'held_object_candidate'),
         ('E',22,[.26,.49,.38,.56],'stationary_card_candidate')]
  with VideoReader(args.video) as reader:
   for name,t,roi,region in cases:
    sample=reader.read_at(t);im=Image.fromarray(cv2.cvtColor(sample.frame_bgr,cv2.COLOR_BGR2RGB));w,h=im.size
    bounds=tuple(round(v*(w if i%2==0 else h)) for i,v in enumerate(roi));crop=im.crop(bounds)
    path=folder/f'control-{name}.jpg';crop.save(path,quality=98)
    details.append({'case':name,'file':path.name,'time_sec':sample.actual_timestamp_sec,'native_crop_size':list(crop.size),'roi_xyxy':roi,'human_review_region':region,'expected_class_verified':False})
  # Blank synthetic image is the only verified negative, independent of video.
  path=folder/'control-F.jpg';Image.new('RGB',(80,68),(173,163,147)).save(path,quality=98)
  details.append({'case':'F','file':path.name,'time_sec':None,'native_crop_size':[80,68],'human_review_region':'synthetic_blank','expected_class_verified':True,'expected_class':'none'})
  write_json(folder/'inputs.local.json',{'details':details,'expected_labels_sent_to_model':False})
  if shutil.disk_usage(folder).free<1024**3:raise RuntimeError('Insufficient free disk')
  env={k:v for k,v in os.environ.items() if not k.startswith('OLLAMA_')}
  env.update(OLLAMA_HOST='127.0.0.1:11435',OLLAMA_NO_CLOUD='1',OLLAMA_MODELS=str(ROOT/'models/ollama'),OLLAMA_NUM_PARALLEL='1',OLLAMA_MAX_LOADED_MODELS='1',OLLAMA_DEBUG_LOG_REQUESTS='false',LLAMA_ARG_CACHE_RAM='0')
  with (folder/'server.local.log').open('w') as log:server=subprocess.Popen([str(LOCAL_OLLAMA),'serve'],env=env,stdout=log,stderr=log,start_new_session=True)
  deadline=time.monotonic()+60
  while True:
   try:request(11435,'version',timeout=2);break
   except OSError:
    if server.poll() is not None or time.monotonic()>deadline:raise
    time.sleep(.2)
  if 'Ollama cloud disabled: true' not in (folder/'server.local.log').read_text():raise RuntimeError('Cloud mode not verified')
  models=request(11435,'tags').get('models',[])
  if not any(m['name']==QWEN_MODEL and not m.get('remote_host') for m in models):raise RuntimeError('Local model unavailable')
  prompt=('Inspect only the supplied image. Classify the main visible small object, if any: banknotes, card, document, other, none, or unclear. '
   'Do not infer an object from the setting. Describe only distinguishing evidence actually visible. '
   'If no separate object is visible use none. If an object is present but its type cannot be determined use unclear. '
   'Do not invent unreadable text or details. Give concise JSON with visible_evidence, classification, confidence, limitation.')
  write_json(folder/'request.local.json',{'prompt':prompt,'schema':schema(),'independent_requests':True,'context_reset_each_case':True})
  status['status']='running';write_json(folder/'status.json',status);print('CONTROLS_STARTED:',folder,flush=True)
  results=[]
  for d in details:
   if shutil.disk_usage(folder).free<1024**3:raise RuntimeError('Insufficient free disk')
   response=request(11435,'generate',{'model':QWEN_MODEL,'prompt':prompt,'images':[base64.b64encode((folder/d['file']).read_bytes()).decode()],'format':schema(),'think':False,'stream':False,'keep_alive':0,'options':{'temperature':0,'seed':1,'num_ctx':4096,'num_predict':400,'repeat_penalty':1.1}},timeout=180)
   write_json(folder/f"response-{d['case']}.local.json",response)
   if not response.get('done') or response.get('done_reason')=='length':raise RuntimeError('Incomplete control response')
   item=json.loads(response['response'])
   if set(item)!=set(schema()['required']) or item['classification'] not in KINDS:raise RuntimeError('Invalid control structure')
   results.append({'case':d['case'],'response':item})
   write_json(folder/'results.local.json',{'cases':results,'real_crop_ground_truth_verified':False})
   if request(11435,'ps').get('models'):raise RuntimeError('Model unload not confirmed')
   print('Completed control',len(results),'/',len(details),flush=True)
  kinds={'banknotes':'Банкноты','card':'Карта','document':'Документ','other':'Другое','none':'Предмета нет','unclear':'Неясно'}
  regions={'held_object_candidate':'Участок предмета в руках — проверь попадание в рамку','stationary_card_candidate':'Предполагаемая карта на столе — тип нужно подтвердить','empty_wall_candidate':'Предполагаемый пустой участок стены — проверь кадр','synthetic_blank':'Синтетический пустой участок, подтверждённый контроль'}
  labels={'classification':'Гипотеза модели','confidence':'Уверенность модели (не калибрована)','visible_evidence':'Видимые основания','limitation':'Ограничения'}
  body=''
  for d,r in zip(details,results):
   uri=base64.b64encode((folder/d['file']).read_bytes()).decode()
   body+=f"<article><h2>Участок {d['case']}</h2><p>{regions[d['human_review_region']]}. Размер: {d['native_crop_size']} пикселей.</p><img src='data:image/jpeg;base64,{uri}'>"+''.join('<p><b>'+label+':</b> '+html.escape(kinds.get(r['response'][k],r['response'][k]))+'</p>' for k,label in labels.items())+'</article>'
  (folder/'report.html').write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'"><style>body{font:17px system-ui;max-width:900px;margin:30px auto;padding:20px}article{background:#eef3f8;padding:20px;margin:20px 0}img{width:100%;max-width:450px;image-rendering:auto}</style><h1>Нейтральная контрольная проверка предметов</h1><p>Каждый участок подан отдельно с одинаковым нейтральным запросом. Без общего вида, банковского контекста, примеров признаков и предыдущих ответов. Имена участков и ожидаемые типы модели не передавались. Реальные участки выбраны вручную по геометрии: сначала проверь, что в них попал нужный объект. Это шесть проб, а не оценка точности на датасете.</p>'+body,encoding='utf-8')
  status.update(status='completed',detail_count=len(details),elapsed_sec=round(time.monotonic()-start,2));print('CONTROL_REPORT_READY:',folder/'report.html',flush=True)
 except Exception as e:
  import traceback
  (folder/'error.local.txt').write_text(traceback.format_exc());status.update(status='failed',error_type=type(e).__name__);print('CONTROLS_FAILED:',type(e).__name__,flush=True)
 finally:
  if server:
   try:request(11435,'generate',{'model':QWEN_MODEL,'keep_alive':0},timeout=5)
   except Exception:pass
   server.terminate()
   try:server.wait(timeout=5)
   except subprocess.TimeoutExpired:server.kill();server.wait()
   status['server_stopped']=True
  write_json(folder/'status.json',status)
 if status['status']!='completed':raise SystemExit(1)
if __name__=='__main__':main()
