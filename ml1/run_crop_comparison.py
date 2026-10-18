"""Compare three spatial views of identical instants, same target marker and neutral prompt."""
import argparse,base64,datetime,html,json,os,shutil,socket,subprocess,sys,time
from pathlib import Path
from run_ollama_trial import ROOT,QWEN_MODEL,LOCAL_OLLAMA,request,write_json
sys.path.insert(0,str(ROOT.parent/'ml2'))
from backend.pipeline.video import VideoReader
from PIL import Image,ImageDraw
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
 folder=ROOT/'local'/('crop-comparison-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));folder.mkdir()
 status={'status':'preparing','model':QWEN_MODEL,'source_name':args.video.name,'cloud_disabled':True,'review_status':'needs_human_review','crop_method':'manual_fixed_camera_geometry_not_hand_detection','expected_class_supplied':False}
 start=time.monotonic();server=None;images=[];details=[]
 try:
  views=[('full',[0,0,1,1]),('medium',[.24,.43,.69,.60]),('tight',[.39,.47,.56,.55])]
  target=[.39,.47,.56,.55]
  with VideoReader(args.video) as reader:
   for t in [21,22]:
    sample=reader.read_at(t);im=Image.fromarray(cv2.cvtColor(sample.frame_bgr,cv2.COLOR_BGR2RGB));w,h=im.size
    for view,roi in views:
     bounds=tuple(round(v*(w if i%2==0 else h)) for i,v in enumerate(roi));crop=im.crop(bounds)
     # Same physical target for all views. Thin marker is not object evidence.
     box=[round(target[0]*w)-bounds[0],round(target[1]*h)-bounds[1],round(target[2]*w)-bounds[0]-1,round(target[3]*h)-bounds[1]-1]
     ImageDraw.Draw(crop).rectangle(box,outline='#ff00ff',width=1)
     name=f'{t}-{view}';path=folder/f'control-{name}.jpg';crop.save(path,quality=98)
     details.append({'case':name,'view':view,'file':path.name,'time_sec':sample.actual_timestamp_sec,'native_crop_size':list(crop.size),'roi_xyxy':roi,'target_roi_xyxy':target,'expected_class_verified':False})
  write_json(folder/'inputs.local.json',{'details':details,'expected_labels_sent_to_model':False,'same_target_marker':True,'resized_before_inference':False})
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
  prompt=('Inspect the small object held by the hand(s) INSIDE the thin magenta rectangle. The rectangle is a location annotation, not a physical object. '
   'Ignore stationary objects outside the rectangle. Classify the target: banknotes, card, document, other, none, or unclear. '
   'Do not infer its type from the setting. Describe only distinguishing evidence actually visible. '
   'If no target object is visible use none. If present but not identifiable use unclear. '
   'Do not invent unreadable text or details. Give concise JSON with visible_evidence, classification, confidence, limitation.')
  write_json(folder/'request.local.json',{'prompt':prompt,'schema':schema(),'independent_requests':True,'context_reset_each_case':True})
  status['status']='running';write_json(folder/'status.json',status);print('CROP_COMPARISON_STARTED:',folder,flush=True)
  results=[]
  for d in details:
   if shutil.disk_usage(folder).free<1024**3:raise RuntimeError('Insufficient free disk')
   response=request(11435,'generate',{'model':QWEN_MODEL,'prompt':prompt,'images':[base64.b64encode((folder/d['file']).read_bytes()).decode()],'format':schema(),'think':False,'stream':False,'keep_alive':0,'options':{'temperature':0,'seed':1,'num_ctx':8192,'num_predict':600,'repeat_penalty':1.1}},timeout=180)
   write_json(folder/f"response-{d['case']}.local.json",response)
   if not response.get('done') or response.get('done_reason')=='length':raise RuntimeError('Incomplete control response')
   item=json.loads(response['response'])
   if set(item)!=set(schema()['required']) or item['classification'] not in KINDS:raise RuntimeError('Invalid control structure')
   results.append({'case':d['case'],'response':item})
   write_json(folder/'results.local.json',{'cases':results,'real_crop_ground_truth_verified':False})
   if request(11435,'ps').get('models'):raise RuntimeError('Model unload not confirmed')
   print('Completed control',len(results),'/',len(details),flush=True)
  kinds={'banknotes':'Банкноты','card':'Карта','document':'Документ','other':'Другое','none':'Предмета нет','unclear':'Неясно'}
  regions={'full':'Полный кадр','medium':'Средний участок рук','tight':'Тесный участок'}
  labels={'classification':'Гипотеза модели','confidence':'Уверенность модели (не калибрована)','visible_evidence':'Видимые основания','limitation':'Ограничения'}
  body=''
  for d,r in zip(details,results):
   uri=base64.b64encode((folder/d['file']).read_bytes()).decode()
   body+=f"<article><h2>Участок {d['case']}</h2><p>{regions[d['view']]}. Размер: {d['native_crop_size']} пикселей.</p><img src='data:image/jpeg;base64,{uri}'>"+''.join('<p><b>'+label+':</b> '+html.escape(kinds.get(r['response'][k],r['response'][k]))+'</p>' for k,label in labels.items())+'</article>'
  (folder/'report.html').write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'"><style>body{font:17px system-ui;max-width:900px;margin:30px auto;padding:20px}article{background:#eef3f8;padding:20px;margin:20px 0}img{width:100%;max-width:450px;image-rendering:auto}</style><h1>Сравнение размеров участка: один предмет</h1><p>Два момента (21 и 22 с), каждый в трёх вариантах: полный, средний, тесный. Тонкая розовая рамка обозначает один и тот же участок предмета во всех вариантах. Проверь попадание предмета в рамку. Каждый запрос независим, текст одинаковый, без ожидаемого типа и примеров признаков. Исходные пиксели не увеличивались перед отправкой; модель использует собственное преобразование изображений. Результаты требуют проверки, уверенность модели не является оценкой точности.</p>'+body,encoding='utf-8')
  status.update(status='completed',detail_count=len(details),elapsed_sec=round(time.monotonic()-start,2));print('CROP_REPORT_READY:',folder/'report.html',flush=True)
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
