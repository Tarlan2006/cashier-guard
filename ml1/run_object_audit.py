"""Local-only appearance audit. Manual geometry crop; no hand detector or transfer inference."""
import argparse,base64,datetime,html,json,os,shutil,socket,subprocess,sys,time
from pathlib import Path
from run_ollama_trial import ROOT,QWEN_MODEL,LOCAL_OLLAMA,request,write_json
sys.path.insert(0,str(ROOT.parent/'ml2'))
from backend.pipeline.video import VideoReader
from PIL import Image
import cv2

KINDS=['banknotes','card','document','other','unclear']
def schema():
 props={k:{'type':'string','maxLength':180} for k in ['visible_shape','visible_layers','flexibility_evidence','printed_pattern','occlusion_or_blur','difference_from_stationary_desk_object']}
 props['classification']={'type':'string','enum':KINDS}
 props['confidence']={'type':'string','enum':['low','medium','high']}
 props['distinguishing_visual_evidence']={'type':'string','maxLength':240}
 item={'type':'object','properties':props,'required':list(props),'additionalProperties':False}
 return {'type':'object','properties':{f'detail_{i}':item for i in range(3)},'required':[f'detail_{i}' for i in range(3)],'additionalProperties':False}

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--video',type=Path,required=True)
 parser.add_argument('--times',type=float,nargs=3,default=[21,21.5,22])
 parser.add_argument('--roi',type=float,nargs=4,default=[.24,.43,.69,.60])
 args=parser.parse_args()
 if sorted(args.times)!=args.times:parser.error('Times must be chronological')
 x1,y1,x2,y2=args.roi
 if not(0<=x1<x2<=1 and 0<=y1<y2<=1):parser.error('Invalid normalized ROI')
 with socket.socket() as probe:
  try:probe.bind(('127.0.0.1',11435))
  except OSError:parser.error('Private trial port occupied')
 folder=ROOT/'local'/('object-audit-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));folder.mkdir()
 status={'status':'preparing','model':QWEN_MODEL,'source_name':args.video.name,'cloud_disabled':True,'review_status':'needs_human_review','roi_xyxy':args.roi,'crop_method':'manual_fixed_camera_geometry_not_hand_detection','expected_class_supplied':False}
 start=time.monotonic();server=None;images=[];details=[]
 try:
  with VideoReader(args.video) as reader:
   for i,t in enumerate(args.times):
    sample=reader.read_at(t);im=Image.fromarray(cv2.cvtColor(sample.frame_bgr,cv2.COLOR_BGR2RGB));w,h=im.size
    if i==0:
     overview=folder/'overview.jpg';im.save(overview,quality=95);images.append(overview)
    bounds=(round(x1*w),round(y1*h),round(x2*w),round(y2*h));crop=im.crop(bounds)
    path=folder/f'detail-{i}.jpg';crop.save(path,quality=98);images.append(path)
    details.append({'file':path.name,'time_sec':sample.actual_timestamp_sec,'native_crop_size':list(crop.size),'pixel_bounds':bounds})
  write_json(folder/'inputs.local.json',{'overview_time':args.times[0],'details':details,'roi_xyxy':args.roi})
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
  prompt=('Appearance-only audit of a bank desk security video. Image 1 is the overview. Images 2, 3, 4 are native-pixel crops of the SAME desk area at '+str(args.times)+' seconds; they are not new people or camera angles. '
   'For detail_0 through detail_2 inspect the object held near the lower seated person\'s hands, separately from any stationary rectangular desk object. '
   'Do NOT infer transfer direction, roles or wrongdoing. Do NOT classify from the banking context. '
   'Describe visible shape, number of layers (single/multiple/not visible), evidence of bending or rigidity, printed pattern without inventing symbols or reading illegible text, and occlusion/blur. '
   'Multiple thin overlapping sheets or fanned edges may support banknotes; a single rigid-looking rectangle alone cannot distinguish a card from an occluded banknote. '
   'Choose banknotes/card/document/other only when distinguishing visual evidence supports it; otherwise unclear. '
   'A nearby stationary desk card does not determine the identity of the held object. If the held object is not visible, use unclear. '
   'Return concise structured JSON. Each crop must be assessed independently; do not propagate a guessed label.')
  write_json(folder/'request.local.json',{'prompt':prompt,'schema':schema(),'image_files':[p.name for p in images]})
  status['status']='running';write_json(folder/'status.json',status);print('OBJECT_AUDIT_STARTED:',folder,flush=True)
  response=request(11435,'generate',{'model':QWEN_MODEL,'prompt':prompt,'images':[base64.b64encode(p.read_bytes()).decode() for p in images],'format':schema(),'think':False,'stream':False,'keep_alive':0,'options':{'temperature':0,'seed':1,'num_ctx':8192,'num_predict':1400,'repeat_penalty':1.1}},timeout=300)
  write_json(folder/'response.local.json',response)
  if not response.get('done') or response.get('done_reason')=='length':raise RuntimeError('Incomplete response')
  result=json.loads(response['response'])
  if set(result)!=set(schema()['required']):raise RuntimeError('Invalid response keys')
  warnings=[]
  for key,item in result.items():
   if set(item)!=set(schema()['properties'][key]['required']):raise RuntimeError('Invalid detail keys')
   if item['classification'] not in KINDS:raise RuntimeError('Invalid object kind')
   if item['classification']!='unclear' and item['confidence']=='low':warnings.append(key+': low-confidence classification is not established')
  write_json(folder/'review.local.json',{'warnings':warnings,'review_status':'needs_human_review','classification_is_ground_truth':False})
  labels={'visible_shape':'Форма','visible_layers':'Слои и края','flexibility_evidence':'Изгиб / жёсткость','printed_pattern':'Видимый рисунок','occlusion_or_blur':'Перекрытие / размытие','difference_from_stationary_desk_object':'Отличие от предмета на столе','classification':'Гипотеза типа','confidence':'Уверенность модели (не калибрована)','distinguishing_visual_evidence':'Отличительные признаки'}
  kinds={'banknotes':'Банкноты','card':'Карта','document':'Документ','other':'Другое','unclear':'Неясно'}
  def img(p):return '<img src="data:image/jpeg;base64,'+base64.b64encode(p.read_bytes()).decode()+'">'
  body=''
  for i,d in enumerate(details):
   item=result[f'detail_{i}'];body+='<article><h2>'+str(d['time_sec'])+' с</h2>'+img(folder/d['file'])+'<p>Исходный размер участка: '+str(d['native_crop_size'])+' пикселей. Детали не восстановлены увеличением.</p>'+''.join('<p><b>'+html.escape(label)+':</b> '+html.escape(kinds.get(item[k],item[k]))+'</p>' for k,label in labels.items())+'</article>'
  (folder/'report.html').write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'"><style>body{font:17px system-ui;max-width:1000px;margin:30px auto;padding:20px}article{background:#eef3f8;padding:20px;margin:20px 0}img{width:100%;max-width:700px}p{overflow-wrap:anywhere}</style><h1>Отдельная проверка предмета</h1><p>Локальная Qwen 2B. Тип предмета заранее не сообщён. Это гипотезы модели, требующие проверки. Ручной участок камеры; автоматического поиска рук здесь нет. Направление передачи не анализируется.</p><h2>Общий вид</h2>'+img(overview)+body,encoding='utf-8')
  status.update(status='completed',detail_count=3,elapsed_sec=round(time.monotonic()-start,2));print('OBJECT_REPORT_READY:',folder/'report.html',flush=True)
 except Exception as e:
  import traceback
  (folder/'error.local.txt').write_text(traceback.format_exc());status.update(status='failed',error_type=type(e).__name__);print('OBJECT_AUDIT_FAILED:',type(e).__name__,flush=True)
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
