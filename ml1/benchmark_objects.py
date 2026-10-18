"""Frozen local development benchmark. Human classes are scoring-only, never in requests."""
import argparse,base64,collections,datetime,hashlib,html,json,os,shutil,socket,subprocess,threading,time
from pathlib import Path
from run_ollama_trial import ROOT,LOCAL_OLLAMA,request,write_json
KINDS=['banknotes','card','document','other','none','unclear']
PROMPT=('Inspect only this image. Classify the main visible small object: banknotes, card, document, other, none, or unclear. Do not infer its type from the setting. Use none only if no separate target object is visible; use unclear if its type cannot be determined. Describe only distinguishing evidence actually visible; do not invent illegible text or details. Return concise JSON.')
SCHEMA={'type':'object','properties':{'classification':{'type':'string','enum':KINDS},'evidence':{'type':'string','maxLength':120},'confidence':{'type':'string','enum':['low','medium','high']}},'required':['classification','evidence','confidence'],'additionalProperties':False}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cohort',type=Path,required=True);p.add_argument('--model',required=True);p.add_argument('--models-dir',type=Path,required=True);args=p.parse_args();plan=json.loads(args.cohort.read_text());dataset=Path(plan['dataset']);rows=plan['examples']
 if not rows or any(r['split']!='development' or r['object_kind']=='unclear' for r in rows):p.error('Development cohort with definite human labels required')
 with socket.socket() as probe:
  probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
  try:probe.bind(('127.0.0.1',11435))
  except OSError:p.error('Private port occupied')
 folder=ROOT/'local'/('object-benchmark-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));folder.mkdir();server=None;stop=threading.Event();watch=None;start=time.monotonic();results=[]
 status={'status':'starting','model':args.model,'cohort':str(args.cohort.resolve()),'cohort_sha256':hashlib.sha256(args.cohort.read_bytes()).hexdigest(),'num_ctx':2048,'num_batch':32,'cloud_disabled':True,'expected_labels_in_prompt':False}
 try:
  if shutil.disk_usage(folder).free<2*1024**3:raise RuntimeError('Need 2GiB free before loading')
  env={k:v for k,v in os.environ.items() if not k.startswith('OLLAMA_')};env.update(OLLAMA_HOST='127.0.0.1:11435',OLLAMA_NO_CLOUD='1',OLLAMA_MODELS=str(args.models_dir.resolve()),OLLAMA_NUM_PARALLEL='1',OLLAMA_MAX_LOADED_MODELS='1',OLLAMA_DEBUG_LOG_REQUESTS='false',LLAMA_ARG_CACHE_RAM='0')
  with (folder/'server.local.log').open('w') as log:server=subprocess.Popen([str(LOCAL_OLLAMA),'serve'],env=env,stdout=log,stderr=log,start_new_session=True)
  deadline=time.monotonic()+60
  while True:
   try:request(11435,'version',timeout=2);break
   except OSError:
    if server.poll() is not None or time.monotonic()>deadline:raise
    time.sleep(.2)
  if 'Ollama cloud disabled: true' not in (folder/'server.local.log').read_text():raise RuntimeError('Cloud-disabled mode unverified')
  model=next((m for m in request(11435,'tags')['models'] if m['name']==args.model and not m.get('remote_host')),None)
  if not model:raise RuntimeError('Local model not available')
  status['model_digest']=model.get('digest');status['status']='running';write_json(folder/'status.json',status)
  write_json(folder/'protocol.local.json',{'prompt':PROMPT,'schema':SCHEMA,'temperature':0,'seed':1,'context':2048,'batch':32,'num_predict':240,'repeat_penalty':1.1,'sample_selection':'frozen_class_stratified_development_only','independent_requests':True,'statistically_independent_samples':False,'limitations':'small selected cohort, correlated frames, no documents or empty controls'})
  def watchdog():
   while not stop.wait(2):
    if shutil.disk_usage(folder).free<1024**3:
     status['resource_abort']='Internal free space below1GiB';os.killpg(server.pid,15);return
  watch=threading.Thread(target=watchdog,daemon=True);watch.start();print('BENCHMARK_STARTED:',folder,flush=True)
  for i,row in enumerate(rows):
   file=(dataset/row['crop_file']).resolve()
   if not file.is_relative_to(dataset.resolve()) or hashlib.sha256(file.read_bytes()).hexdigest()!=row['crop_sha256']:raise RuntimeError('Crop integrity failure')
   response=request(11435,'generate',{'model':args.model,'prompt':PROMPT,'images':[base64.b64encode(file.read_bytes()).decode()],'format':SCHEMA,'think':False,'stream':False,'keep_alive':0,'options':{'temperature':0,'seed':1,'num_ctx':2048,'num_batch':32,'num_predict':240,'repeat_penalty':1.1}},timeout=180)
   write_json(folder/f'response-{i:02d}.local.json',response)
   if not response.get('done') or response.get('done_reason')=='length':raise RuntimeError('Incomplete response')
   item=json.loads(response['response'])
   if set(item)!=set(SCHEMA['required']) or item['classification'] not in KINDS:raise RuntimeError('Invalid result')
   results.append({'example_id':row['id'],'expected':row['object_kind'],'predicted':item['classification'],'confidence':item['confidence'],'raw_evidence':item['evidence']});write_json(folder/'results.local.json',{'examples':results})
   if request(11435,'ps').get('models'):raise RuntimeError('Model unload not confirmed')
   status['completed_examples']=len(results);write_json(folder/'status.json',status);print('Completed benchmark',len(results),'/',len(rows),flush=True)
  confusion={k:dict(collections.Counter(r['predicted'] for r in results if r['expected']==k)) for k in sorted({r['expected'] for r in results})};correct=sum(r['expected']==r['predicted'] for r in results)
  metrics={'examples':len(results),'correct':correct,'accuracy_on_selected_cohort':correct/len(results),'unclear_predictions':sum(r['predicted']=='unclear' for r in results),'high_confidence_errors':sum(r['confidence']=='high' and r['expected']!=r['predicted'] for r in results),'confusion':confusion,'is_heldout_accuracy':False}
  write_json(folder/'metrics.local.json',metrics);status['status']='completed';print('BENCHMARK_READY:',folder,flush=True);print(json.dumps(metrics),flush=True)
 except Exception as e:
  import traceback
  (folder/'error.local.txt').write_text(traceback.format_exc());status.update(status='failed',error_type=type(e).__name__);print('BENCHMARK_FAILED:',type(e).__name__,flush=True)
 finally:
  stop.set()
  if watch:watch.join(timeout=3)
  if server:
   try:request(11435,'generate',{'model':args.model,'keep_alive':0},timeout=5)
   except Exception:pass
   if server.poll() is None:
    os.killpg(server.pid,15)
    try:server.wait(timeout=5)
    except subprocess.TimeoutExpired:os.killpg(server.pid,9);server.wait()
   status['server_stopped']=True
  status['elapsed_sec']=round(time.monotonic()-start,2);write_json(folder/'status.json',status)
 if status['status']!='completed':raise SystemExit(1)
if __name__=='__main__':main()
