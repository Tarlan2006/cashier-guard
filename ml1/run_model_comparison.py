"""Compare a new local model on EXACT saved images and prompt; no extraction or regeneration."""
import argparse,base64,datetime,html,json,os,shutil,socket,subprocess,sys,time
from pathlib import Path
from run_ollama_trial import ROOT,QWEN_MODEL,LOCAL_OLLAMA,request,write_json

KINDS=['banknotes','card','document','other','none','unclear']
def schema():
 props={'visible_evidence':{'type':'string','maxLength':240},'classification':{'type':'string','enum':KINDS},'confidence':{'type':'string','enum':['low','medium','high']},'limitation':{'type':'string','maxLength':160}}
 return {'type':'object','properties':props,'required':list(props),'additionalProperties':False}


def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--inputs',type=Path,required=True)
 parser.add_argument('--model',default='qwen3-vl:4b-instruct')
 parser.add_argument('--models-dir',type=Path,default=ROOT/'models/ollama')
 parser.add_argument('--context',type=int,default=2048)
 parser.add_argument('--batch',type=int,default=64)
 parser.add_argument('--prepare-only',action='store_true')
 args=parser.parse_args()
 source=args.inputs.resolve()
 if not source.is_relative_to((ROOT/'local').resolve()):parser.error('Inputs must remain local')
 upstream=json.loads((source/'status.json').read_text())
 if upstream['status']!='completed':parser.error('Completed baseline required')
 details=json.loads((source/'inputs.local.json').read_text())['details']
 if not details:parser.error('No baseline images')
 saved_request=json.loads((source/'request.local.json').read_text());prompt=saved_request['prompt']
 if saved_request['schema']!=schema():parser.error('Baseline schema differs')
 import hashlib
 fingerprints=[]
 for d in details:
  file=(source/d['file']).resolve()
  if not file.is_relative_to(source) or not file.is_file():parser.error('Invalid saved image')
  fingerprints.append({'file':d['file'],'sha256':hashlib.sha256(file.read_bytes()).hexdigest()})
 if args.prepare_only:
  write_json(source/'next-model-plan.local.json',{'model':args.model,'input_fingerprints':fingerprints,'same_prompt':True,'same_schema':True,'expected_labels_supplied':False})
  print('PREPARED_IDENTICAL_INPUT_COMPARISON:',len(details),'images; no inference or download')
  return
 model=args.model
 with socket.socket() as probe:
  probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
  try:probe.bind(('127.0.0.1',11435))
  except OSError:parser.error('Private trial port occupied')
 folder=ROOT/'local'/('model-comparison-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));folder.mkdir()
 status={'status':'preparing','model':model,'source_name':upstream['source_name'],'cloud_disabled':True,'review_status':'needs_human_review','crop_method':'manual_fixed_camera_geometry_not_hand_detection','expected_class_supplied':False,'models_dir':str(args.models_dir.resolve()),'baseline_source':str(source),'num_ctx':args.context,'num_batch':args.batch}
 start=time.monotonic();server=None
 try:
  for d in details:shutil.copy2(source/d['file'],folder/d['file'])
  write_json(folder/'inputs.local.json',{'details':details,'baseline_source':str(source),'input_fingerprints':fingerprints,'expected_labels_sent_to_model':False})
  if shutil.disk_usage(folder).free<1024**3:raise RuntimeError('Insufficient free disk')
  env={k:v for k,v in os.environ.items() if not k.startswith('OLLAMA_')}
  env.update(OLLAMA_HOST='127.0.0.1:11435',OLLAMA_NO_CLOUD='1',OLLAMA_MODELS=str(args.models_dir.resolve()),OLLAMA_NUM_PARALLEL='1',OLLAMA_MAX_LOADED_MODELS='1',OLLAMA_DEBUG_LOG_REQUESTS='false',LLAMA_ARG_CACHE_RAM='0')
  with (folder/'server.local.log').open('w') as log:server=subprocess.Popen([str(LOCAL_OLLAMA),'serve'],env=env,stdout=log,stderr=log,start_new_session=True)
  deadline=time.monotonic()+60
  while True:
   try:request(11435,'version',timeout=2);break
   except OSError:
    if server.poll() is not None or time.monotonic()>deadline:raise
    time.sleep(.2)
  if 'Ollama cloud disabled: true' not in (folder/'server.local.log').read_text():raise RuntimeError('Cloud mode not verified')
  models=request(11435,'tags').get('models',[])
  if not any(m['name']==model and not m.get('remote_host') for m in models):raise RuntimeError('Local model unavailable')
  write_json(folder/'request.local.json',{'prompt':prompt,'schema':schema(),'independent_requests':True,'context_reset_each_case':True})
  status['status']='running';write_json(folder/'status.json',status);print('CROP_COMPARISON_STARTED:',folder,flush=True)
  results=[]
  for d in details:
   if shutil.disk_usage(folder).free<1024**3:raise RuntimeError('Insufficient free disk')
   response=request(11435,'generate',{'model':model,'prompt':prompt,'images':[base64.b64encode((folder/d['file']).read_bytes()).decode()],'format':schema(),'think':False,'stream':False,'keep_alive':0,'options':{'temperature':0,'seed':1,'num_ctx':args.context,'num_batch':args.batch,'num_predict':600,'repeat_penalty':1.1}},timeout=180)
   write_json(folder/f"response-{d['case']}.local.json",response)
   if not response.get('done') or response.get('done_reason')=='length':raise RuntimeError('Incomplete control response')
   item=json.loads(response['response'])
   if set(item)!=set(schema()['required']) or item['classification'] not in KINDS:raise RuntimeError('Invalid control structure')
   results.append({'case':d['case'],'response':item})
   write_json(folder/'results.local.json',{'cases':results,'real_crop_ground_truth_verified':False})
   if request(11435,'ps').get('models'):raise RuntimeError('Model unload not confirmed')
   print('Completed control',len(results),'/',len(details),flush=True)
  if len(results)!=len(fingerprints):raise RuntimeError('Result count mismatch')
  kinds={'banknotes':'Банкноты','card':'Карта','document':'Документ','other':'Другое','none':'Предмета нет','unclear':'Неясно'}
  regions={'full':'Полный кадр','medium':'Средний участок рук','tight':'Тесный участок'}
  labels={'classification':'Гипотеза модели','confidence':'Уверенность модели (не калибрована)','visible_evidence':'Видимые основания','limitation':'Ограничения'}
  body=''
  for d,r in zip(details,results):
   uri=base64.b64encode((folder/d['file']).read_bytes()).decode()
   body+=f"<article><h2>Участок {d['case']}</h2><p>{regions[d['view']]}. Размер: {d['native_crop_size']} пикселей.</p><img src='data:image/jpeg;base64,{uri}'>"+''.join('<p><b>'+label+':</b> '+html.escape(kinds.get(r['response'][k],r['response'][k]))+'</p>' for k,label in labels.items())+'</article>'
  (folder/'report.html').write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'"><style>body{font:17px system-ui;max-width:900px;margin:30px auto;padding:20px}article{background:#eef3f8;padding:20px;margin:20px 0}img{width:100%;max-width:450px;image-rendering:auto}</style><h1>Проверка следующей модели на сохранённых кадрах</h1><p>Два момента (21 и 22 с), каждый в трёх вариантах: полный, средний, тесный. Тонкая розовая рамка обозначает один и тот же участок предмета во всех вариантах. Проверь попадание предмета в рамку. Каждый запрос независим, текст одинаковый, без ожидаемого типа и примеров признаков. Исходные пиксели не увеличивались перед отправкой; модель использует собственное преобразование изображений. Изображения и запрос взяты без изменений из предыдущего эксперимента. Результаты требуют проверки, уверенность модели не является оценкой точности.</p>'+body,encoding='utf-8')
  if upstream.get('input_scope_description'):
   report_path=folder/'report.html';text=report_path.read_text();begin=text.index('<p>Два момента');end=text.index('</p>',begin)+4
   text=text[:begin]+'<p>'+html.escape(upstream['input_scope_description'])+'</p>'+text[end:]
   report_path.write_text(text)
  status.update(status='completed',detail_count=len(details),elapsed_sec=round(time.monotonic()-start,2));print('CROP_REPORT_READY:',folder/'report.html',flush=True)
 except Exception as e:
  import traceback
  (folder/'error.local.txt').write_text(traceback.format_exc());status.update(status='failed',error_type=type(e).__name__);print('CONTROLS_FAILED:',type(e).__name__,flush=True)
 finally:
  if server:
   try:request(11435,'generate',{'model':model,'keep_alive':0},timeout=5)
   except Exception:pass
   server.terminate()
   try:server.wait(timeout=5)
   except subprocess.TimeoutExpired:server.kill();server.wait()
   status['server_stopped']=True
  write_json(folder/'status.json',status)
 if status['status']!='completed':raise SystemExit(1)
if __name__=='__main__':main()
