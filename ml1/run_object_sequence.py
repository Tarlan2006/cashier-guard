"""One local chronological object audit, no expected class or transfer direction supplied."""
import argparse,base64,datetime,html,json,os,shutil,socket,subprocess,threading,time
from pathlib import Path
from run_ollama_trial import ROOT,LOCAL_OLLAMA,request,write_json
from run_model_comparison import schema as item_schema,KINDS

def sequence_schema():
 item=item_schema();props={f'frame_{i}':item for i in range(3)}
 props['sequence']={'type':'object','properties':{'classification':{'type':'string','enum':KINDS},'same_object_continuity':{'type':'string','enum':['supported','unclear','different_objects']},'temporal_evidence':{'type':'string','maxLength':300},'contradictions_or_missing_detail':{'type':'string','maxLength':240}},'required':['classification','same_object_continuity','temporal_evidence','contradictions_or_missing_detail'],'additionalProperties':False}
 return {'type':'object','properties':props,'required':list(props),'additionalProperties':False}

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--inputs',type=Path,required=True)
 parser.add_argument('--contact-sheet',action='store_true')
 parser.add_argument('--models-dir',type=Path,required=True)
 args=parser.parse_args();source=args.inputs.resolve()
 if not source.is_relative_to((ROOT/'local').resolve()):parser.error('Use local inputs')
 details=json.loads((source/'inputs.local.json').read_text())['details']
 if len(details)!=3:parser.error('Three inputs required')
 with socket.socket() as probe:
  probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
  try:probe.bind(('127.0.0.1',11435))
  except OSError:parser.error('Private port occupied')
 model='qwen3-vl:4b-instruct'
 context=2048 if args.contact_sheet else 4096
 folder=ROOT/'local'/('object-sequence-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));folder.mkdir()
 status={'status':'preparing','model':model,'cloud_disabled':True,'models_dir':str(args.models_dir.resolve()),'num_ctx':context,'num_batch':32,'contact_sheet':args.contact_sheet,'review_status':'needs_human_review','source_inputs':str(source),'expected_class_supplied':False}
 server=None;watch=None;stop=threading.Event();start=time.monotonic()
 try:
  import hashlib
  for d in details:
   p=(source/d['file']).resolve()
   if not p.is_relative_to(source) or not p.is_file():raise ValueError('Invalid local image')
   shutil.copy2(p,folder/d['file']);d['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
  image_paths=[folder/d['file'] for d in details]
  if args.contact_sheet:
   from PIL import Image,ImageDraw,ImageFont
   opened=[Image.open(p).convert('RGB') for p in image_paths];width=sum(im.width for im in opened);height=max(im.height for im in opened)+24
   sheet=Image.new('RGB',(width,height),'white');draw=ImageDraw.Draw(sheet);left=0
   for i,(im,d) in enumerate(zip(opened,details)):
    sheet.paste(im,(left,24));draw.text((left+5,3),f"{i+1}: {d['time_sec']} s",fill='black');left+=im.width
   sheet.save(folder/'sequence-sheet.jpg',quality=98);image_paths=[folder/'sequence-sheet.jpg']
  write_json(folder/'inputs.local.json',{'details':details,'model_image_files':[p.name for p in image_paths],'contact_sheet':args.contact_sheet})
  if shutil.disk_usage(folder).free<2*1024**3:raise RuntimeError('Need 2 GiB free before loading')
  env={k:v for k,v in os.environ.items() if not k.startswith('OLLAMA_')}
  env.update(OLLAMA_HOST='127.0.0.1:11435',OLLAMA_NO_CLOUD='1',OLLAMA_MODELS=str(args.models_dir.resolve()),OLLAMA_NUM_PARALLEL='1',OLLAMA_MAX_LOADED_MODELS='1',OLLAMA_DEBUG_LOG_REQUESTS='false',LLAMA_ARG_CACHE_RAM='0')
  with (folder/'server.local.log').open('w') as log:server=subprocess.Popen([str(LOCAL_OLLAMA),'serve'],env=env,stdout=log,stderr=log,start_new_session=True)
  deadline=time.monotonic()+60
  while True:
   try:request(11435,'version',timeout=2);break
   except OSError:
    if server.poll() is not None or time.monotonic()>deadline:raise
    time.sleep(.2)
  if 'Ollama cloud disabled: true' not in (folder/'server.local.log').read_text():raise RuntimeError('Cloud-disabled mode unverified')
  if not any(m['name']==model and not m.get('remote_host') for m in request(11435,'tags').get('models',[])):raise RuntimeError('Local model missing')
  def watchdog():
   while not stop.wait(2):
    free=shutil.disk_usage(folder).free
    status['minimum_free_bytes']=min(status.get('minimum_free_bytes',free),free)
    if free<1024**3:
     status['resource_abort']='Internal disk free below 1 GiB'
     os.killpg(server.pid,15)
     return
  watch=threading.Thread(target=watchdog,daemon=True);watch.start()
  prompt=('These three images show the SAME camera area at '+str([d['time_sec'] for d in details])+' seconds, in chronological order. '
   'Inspect the hand-held object within the thin magenta location rectangle. The rectangle is an annotation, not an object. '
   'Keep any separate stationary desk object distinct. Do not infer the target type from the setting. '
   'For each frame describe visible_evidence, classification, confidence, limitation. Class options: banknotes/card/document/other/none/unclear. '
   'Then assess the sequence as a whole: classification, same_object_continuity, temporal_evidence, contradictions_or_missing_detail. '
   'Use changes actually visible across images, without inventing details, unreadable text or missing actions. '
   'Do not assume an earlier classification is correct. If continuity or distinguishing details are insufficient, state unclear. '
   'Do not infer transfer direction or wrongdoing. Return concise JSON, with complete short sentences.')
  if args.contact_sheet:
   prompt=prompt.replace('These three images show','The ONE supplied image contains THREE chronological panels from LEFT to RIGHT showing').replace('For each frame describe','Panel labels 1,2,3 correspond to frame_0,frame_1,frame_2. These are distinct times, not multiple views of one instant. For each frame describe')
   prompt+=' Keep each evidence and limitation under 12 words; summarize uncertainty without repeating sentences.'
  write_json(folder/'request.local.json',{'prompt':prompt,'schema':sequence_schema(),'images':[d['file'] for d in details]})
  status['status']='running';write_json(folder/'status.json',status);print('SEQUENCE_STARTED:',folder,flush=True)
  response=request(11435,'generate',{'model':model,'prompt':prompt,'images':[base64.b64encode(p.read_bytes()).decode() for p in image_paths],'format':sequence_schema(),'think':False,'stream':False,'keep_alive':0,'options':{'temperature':0,'seed':1,'repeat_penalty':1.1,'num_ctx':context,'num_batch':32,'num_predict':650 if args.contact_sheet else 1100}},timeout=300)
  write_json(folder/'response.local.json',response)
  if not response.get('done') or response.get('done_reason')=='length':raise RuntimeError('Incomplete response')
  data=json.loads(response['response'])
  if set(data)!=set(sequence_schema()['required']):raise RuntimeError('Invalid response keys')
  for i in range(3):
   if set(data[f'frame_{i}'])!=set(item_schema()['required']):raise RuntimeError('Invalid frame keys')
  write_json(folder/'results.local.json',data)
  kinds={'banknotes':'Банкноты','card':'Карта','document':'Документ','other':'Другое','none':'Предмета нет','unclear':'Неясно'}
  rows='';body=''
  labels={'visible_evidence':'Видимые признаки','classification':'Гипотеза типа','confidence':'Уверенность (не калибрована)','limitation':'Ограничения'}
  for i,d in enumerate(details):
   item=data[f'frame_{i}'];rows+=f"<tr><td>{d['time_sec']} с</td><td>{html.escape(kinds[item['classification']])}</td><td>{html.escape(item['confidence'])}</td></tr>"
   uri=base64.b64encode((folder/d['file']).read_bytes()).decode();body+=f"<article><h2>{d['time_sec']} с</h2><img src='data:image/jpeg;base64,{uri}'>"+''.join('<p><b>'+label+':</b> '+html.escape(kinds.get(item[k],item[k]))+'</p>' for k,label in labels.items())+'</article>'
  seq=data['sequence'];summary='<h2>Гипотеза по последовательности: '+html.escape(kinds[seq['classification']])+'</h2><p>Непрерывность предмета: '+html.escape(seq['same_object_continuity'])+'</p><p>Основания во времени: '+html.escape(seq['temporal_evidence'])+'</p><p>Противоречия / недостающие детали: '+html.escape(seq['contradictions_or_missing_detail'])+'</p>'
  if args.contact_sheet:
   uri=base64.b64encode((folder/'sequence-sheet.jpg').read_bytes()).decode();summary='<h2>Фактический вход модели: три разных момента слева направо</h2><img style="max-width:100%" src="data:image/jpeg;base64,'+uri+'">'+summary
  (folder/'report.html').write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'"><style>body{font:17px system-ui;max-width:1000px;margin:30px auto;padding:20px}article{background:#eef3f8;padding:20px;margin:20px 0}img{width:100%;max-width:600px}</style><h1>Предмет в последовательности: Qwen 4B</h1><p>Три средних участка одним запросом. Модель хранится на флешке; кадры и ответы — на Mac. Рамка задана вручную. Ожидаемый тип не сообщался. Направление передачи не проверяется. Все выводы требуют ручной проверки.</p>'+summary+'<table border="1" cellpadding="10"><tr><th>Момент</th><th>Гипотеза</th><th>Уверенность модели</th></tr>'+rows+'</table>'+body,encoding='utf-8')
  status.update(status='completed',frame_count=3);print('SEQUENCE_REPORT_READY:',folder/'report.html',flush=True)
 except Exception as e:
  import traceback
  (folder/'error.local.txt').write_text(traceback.format_exc());status.update(status='failed',error_type=type(e).__name__);print('SEQUENCE_FAILED:',type(e).__name__,flush=True)
 finally:
  stop.set()
  if watch:watch.join(timeout=3)
  if server:
   try:request(11435,'generate',{'model':model,'keep_alive':0},timeout=5)
   except Exception:pass
   if server.poll() is None:
    os.killpg(server.pid,15)
    try:server.wait(timeout=5)
    except subprocess.TimeoutExpired:os.killpg(server.pid,9);server.wait()
   status['server_stopped']=True
  status['elapsed_sec']=round(time.monotonic()-start,2);write_json(folder/'status.json',status)
 if status['status']!='completed':raise SystemExit(1)
if __name__=='__main__':main()
