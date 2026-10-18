"""Review whole-video windows with observed person IDs; no cloud inference."""
import argparse,base64,datetime,html,json,os,socket,subprocess,time,copy
import shutil
from pathlib import Path
from run_ollama_trial import ROOT,QWEN_MODEL,LOCAL_OLLAMA,request,write_json

KINDS=['banknotes','card','document','other','unclear']
PHASES=['no_visible_transfer','offered','simultaneous_contact','received','unclear']

def make_schema(count,ids,frame_ids=None,temporal=False):
 moment={'type':'object','properties':{'hands':{'type':'string','maxLength':180},
     'object_kind':{'type':'string','enum':KINDS},
     'holder_ids':{'type':'array','maxItems':3,'items':{'type':'string','enum':ids+['desk','unclear']}}},
     'required':['hands','object_kind','holder_ids'],'additionalProperties':False}
 transfer={'type':'object','properties':{
     'from_id':{'type':'string','enum':ids+['unclear']},'to_id':{'type':'string','enum':ids+['unclear']},
     'phase':{'type':'string','enum':PHASES},'object_kind':{'type':'string','enum':KINDS},
     'evidence':{'type':'string','maxLength':300},'uncertainty':{'type':'string','maxLength':200}},
     'required':['from_id','to_id','phase','object_kind','evidence','uncertainty'],'additionalProperties':False}
 if temporal:
  moment['properties']['motion']={'type':'object','properties':{actor:{'type':'string','enum':['approaching_exchange','contact','withdrawing_from_exchange','stationary','occluded','unclear']} for actor in ids},'required':ids,'additionalProperties':False}
  moment['properties']['moving_object_position']={'type':'string','maxLength':100}
  moment['properties']['separate_stationary_objects']={'type':'string','maxLength':100}
  moment['required']+=['motion','moving_object_position','separate_stationary_objects']
 properties={}
 for i in range(count):
  item=copy.deepcopy(moment)
  if frame_ids is not None:item['properties']['holder_ids']['items']['enum']=frame_ids[i]+['desk','unclear']
  properties[f'frame_{i}']=item
 properties['transfer']=transfer
 return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}


def check_observation_consistency(data,frame_ids):
 """Reject impossible IDs and flag unsupported ownership chronology, not visual truth."""
 for i,allowed in enumerate(frame_ids):
  if any(x not in allowed+['desk','unclear'] for x in data[f'frame_{i}']['holder_ids']):
   raise ValueError('A holder ID was not observed in that frame')
 transfer=data['transfer'];a,b=transfer['from_id'],transfer['to_id']
 union={x for row in frame_ids for x in row}
 if a not in union|{'unclear'} or b not in union|{'unclear'}:raise ValueError('Unobserved transfer participant')
 warnings=[]
 if transfer['phase']=='received':
  states=[set(data[f'frame_{i}']['holder_ids']) for i in range(len(frame_ids))]
  supported=(a!=b and a!='unclear' and b!='unclear' and any(
      a in states[i] and b not in states[i] and b in states[j] and a not in states[j]
      for i in range(len(states)) for j in range(i+1,len(states))))
  if not supported:warnings.append('received_without_distinct_before_after_ownership')
 return warnings


def report(folder,status,frames,results,source):
 esc=html.escape
 focused=status.get('input_scope')=='focused_segment'
 heading='Короткая проверка рабочей области' if focused else 'Участники и передача по ролику'
 memory_note=('Передано предварительное описание предыдущего окна; оно может содержать ошибки.'
              if status.get('memory_enabled',True) else 'Окна анализируются независимо: описания предыдущих окон не передаются.')
 role_note='Роли участников пользователем не подтверждены.'
 actors={'unclear':'Неясно','desk':'Стол'}
 mapping_path=source/'user-role-map.local.json'
 if mapping_path.is_file():
  mapping=json.loads(mapping_path.read_text())
  if not mapping.get('client_mapping_needs_clarification',True):
   role_note=(f'Пользователь проверил роли: ID {mapping["cashier_id"]} — кассир; ID {mapping["client_id"]} — клиент. '
              'Это расшифровка номеров для проверки выводов, а не подтверждение передачи или точности всех треков.')
   actors.update({f'ID {mapping["cashier_id"]}':f'ID {mapping["cashier_id"]} (кассир)',
                  f'ID {mapping["client_id"]}':f'ID {mapping["client_id"]} (клиент)'})
   labeled=sum('Human-reviewed role labels:' in json.loads(p.read_text()).get('prompt','') for p in folder.glob('window-*.local.json'))
   role_note+=f' Подтверждённые роли были переданы в {labeled} из {len(results)} запросов; остальные окна использовали автоматические кандидаты.'
 names={'banknotes':'Банкноты','card':'Карта','document':'Документ','other':'Другой предмет','unclear':'Неясно',
        'no_visible_transfer':'Передача не видна','offered':'Предмет протягивают','simultaneous_contact':'Одновременное касание','received':'Получение предмета'}
 cards=[]
 navigation=' · '.join(f'<a href="#window-{round(r["start_sec"]*1000)}">{r["start_sec"]:g}–{r["end_sec"]:g} с</a>' for r in results)
 for result in results:
  decoded=json.loads(result['response']);transfer=decoded['transfer'];pictures=[]
  for i,index in enumerate(result['frame_indices']):
   f=frames[index];moment=decoded[f'frame_{i}']
   uri='data:image/jpeg;base64,'+base64.b64encode((source/f['file']).read_bytes()).decode('ascii')
   motion_names={'approaching_exchange':'К месту передачи','contact':'Контакт','withdrawing_from_exchange':'Возврат руки от места передачи','stationary':'Без заметного движения','occluded':'Закрыта от камеры','unclear':'Неясно'}
   motion_text=(''.join(f'<p>{esc(actors.get(a,a))}: {esc(motion_names.get(m,m))}</p>' for a,m in moment.get('motion',{}).items())
       +f'<p>Движущийся предмет: {esc(moment.get("moving_object_position",""))}<br>Отдельные неподвижные предметы: {esc(moment.get("separate_stationary_objects",""))}</p>' if 'motion' in moment else '')
   pictures.append(f'<section><h3>{f["timestamp_sec"]:.3f} с</h3><img src="{uri}" alt="Кадр с номерами участников">'
       f'<p>{esc(moment["hands"])}</p>{motion_text}<p>Предмет: {esc(names[moment["object_kind"]])}<br>Держит/касается: {esc(", ".join(actors.get(x,x) for x in moment["holder_ids"]))}</p></section>')
  direction=(names[transfer['phase']] if transfer['phase']=='no_visible_transfer' else
             actors.get(transfer['from_id'],transfer['from_id'])+' → '+actors.get(transfer['to_id'],transfer['to_id'])+' · '+names[transfer['phase']])
  warning=(' <p class="note"><strong>Заявленное получение не подтверждается последовательностью владельцев в ответах модели. Направление не установлено этой проверкой.</strong></p>'
           if result.get('consistency_warnings') else '')
  cards.append(f'<article id="window-{round(result["start_sec"]*1000)}"><h2>{result["start_sec"]:.3f}–{result["end_sec"]:.3f} с</h2><p><strong>Предположение модели: {esc(direction)}</strong></p>'
      +warning+f'<p>Тип предмета: {esc(names[transfer["object_kind"]])}</p><p>Основания: {esc(transfer["evidence"])}</p><p>Неясно: {esc(transfer["uncertainty"])}</p><div class="grid">'+''.join(pictures)+'</div></article>')
 (folder/'report.html').write_text(f'''<!doctype html><html lang="ru"><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Весь ролик: номера участников и передача</title>
<style>body{{font:16px system-ui;max-width:1400px;margin:30px auto;padding:0 20px;background:#f5f7fb;color:#17212b}}article{{background:white;padding:20px;border-radius:12px;margin:20px 0}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:15px}}img{{width:100%;height:auto}}p{{line-height:1.5;overflow-wrap:anywhere}}.note{{background:#fff0ce;padding:20px;border-radius:12px}}</style>
<h1>{heading}</h1><p>{esc(status['source_name'])} · {esc(status['model'])} · {status.get('elapsed_sec',0):.1f} с обработки</p>
<p class="note">{esc(status.get('view_note','Исходные кадры с номерами детектора, без коллажа.'))}
Шаг выбранных кадров: {status.get('sample_interval_sec',.5):g} с. Окна перекрываются одним моментом.
ID — временный номер трека. Роли из детектора — только кандидаты; неизвестные роли не заменены догадками Qwen.
{memory_note}
Все ответы требуют ручной проверки: программа не установила факт передачи или нарушения.
Выбранные кадры могут пропустить короткие действия. Ошибки трекинга тоже могут влиять на направление.</p>
<p class="note">{esc(role_note)}</p>
<p>Перейти к окну: {navigation}</p>
<p><a href="{esc(str(source/'report.html'),quote=True)}">Отчёт детектора и трекинга</a></p>
{''.join(cards)}</html>''',encoding='utf-8')


def temporal_instructions():
 return (' TEMPORAL MOTION AUDIT: Compare each hand with its position in the PREVIOUS image. '
         'An extended hand is a position, not evidence of reaching. Approaching_exchange means movement toward the contact area; '
         'withdrawing_from_exchange means movement away from that area back toward the same person. '
         'The first image has no previous image: use unclear for motion. Motion labels describe visible displacement, not intention. '
         'Do not describe withdrawal as reaching for a different stationary object. '
         'For each actor provide motion; separately describe moving_object_position and separate_stationary_objects. '
         'Follow ONE moving object through before/contact/after, keeping any stationary desk card separate. '
         'If its appearance or continuity is obscured, object_kind must be unclear; do not fill gaps using the bank setting. '
         'Received requires distinct earlier sender-only and later receiver-only holder_ids for the SAME object. '
         'If this window begins after release or ends during contact, do not invent missing ownership. ')


def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--tracks',type=Path,required=True)
 parser.add_argument('--resume',type=Path,help='Resume completed windows from this local trial')
 parser.add_argument('--memory',action=argparse.BooleanOptionalAction,default=False,
                     help='Experimental prior-description memory; disabled by default')
 parser.add_argument('--temporal',action='store_true',help='Audit relative motion and separate stationary objects')
 parser.add_argument('--window-size',type=int,default=5,choices=range(3,8))
 args=parser.parse_args();source=args.tracks.resolve()
 if not source.is_relative_to((ROOT/'local').resolve()):parser.error('Use local tracking output only')
 upstream=json.loads((source/'status.json').read_text())
 if upstream['status']!='completed':parser.error('Tracking trial incomplete')
 frames=json.loads((source/'frames.local.json').read_text())['frames']
 if len(frames)<2:parser.error('Not enough observed moments')
 for f in frames:
  path=(source/f['file']).resolve()
  if not path.is_relative_to(source) or not path.is_file():parser.error('Invalid local frame path')
 port=11435
 with socket.socket() as probe:
  probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
  try:probe.bind(('127.0.0.1',port))
  except OSError:parser.error('Trial port occupied')
 folder=args.resume.resolve() if args.resume else ROOT/'local'/('tracked-video-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'))
 if not folder.is_relative_to((ROOT/'local').resolve()):parser.error('Resume must be under local/')
 folder.mkdir(parents=True,exist_ok=bool(args.resume))
 status={'status':'running','phase':'starting_server','source_name':upstream['source_name'],'model':QWEN_MODEL,
         'tracks_folder':str(source),'timeline_frames':len(frames),'completed_windows':0,'cloud_disabled':True,
         'review_status':'needs_human_review'}
 status.update(input_scope=upstream.get('input_scope','whole_video_samples'),
               sample_interval_sec=upstream.get('sample_interval_sec',.5),
               view_note=upstream.get('view_note','Исходные кадры с номерами детектора, без коллажа.'))
 status['memory_enabled']=args.memory
 status['temporal_audit']=args.temporal
 status['window_size']=args.window_size
 start=time.monotonic();server=None;results=[]
 prior_elapsed=0
 if args.resume:
  previous_status=json.loads((folder/'status.json').read_text())
  if previous_status['tracks_folder']!=str(source) or previous_status['model']!=QWEN_MODEL:parser.error('Resume input mismatch')
  if previous_status.get('temporal_audit',False)!=args.temporal or previous_status.get('window_size',5)!=args.window_size:parser.error('Resume analysis settings mismatch')
  if previous_status.get('server_stopped') is not True:parser.error('Stop the prior server before resuming')
  results=json.loads((folder/'results.local.json').read_text())['windows']
  prior_elapsed=previous_status.get('elapsed_sec',0)
  write_json(folder/'previous-attempt-status.local.json',previous_status)
  status.update(completed_windows=len(results),metrics=previous_status.get('metrics',[]),resumed=True)
 status['prompt_cache_ram_mib']=0
 status['unload_between_windows']=True
 write_json(folder/'status.json',status);print('Trial directory:',folder,flush=True)
 try:
  env={k:v for k,v in os.environ.items() if not k.startswith('OLLAMA_')}
  env.update({'OLLAMA_HOST':f'127.0.0.1:{port}','OLLAMA_NO_CLOUD':'1','OLLAMA_MODELS':str(ROOT/'models/ollama'),
              'OLLAMA_NUM_PARALLEL':'1','OLLAMA_MAX_LOADED_MODELS':'1','OLLAMA_DEBUG_LOG_REQUESTS':'false',
              'LLAMA_ARG_CACHE_RAM':'0'})
  with (folder/'server.local.log').open('a') as log:server=subprocess.Popen([str(LOCAL_OLLAMA),'serve'],env=env,stdout=log,stderr=log,start_new_session=True)
  status['server_pid']=server.pid
  deadline=time.monotonic()+60
  while True:
   try:status['ollama_version']=request(port,'version',timeout=2)['version'];break
   except OSError:
    if server.poll() is not None or time.monotonic()>deadline:raise
    time.sleep(.2)
  if 'Ollama cloud disabled: true' not in (folder/'server.local.log').read_text():raise RuntimeError('Cloud-disabled mode not confirmed')
  model=next((x for x in request(port,'tags')['models'] if x['name']==QWEN_MODEL),None)
  if model is None or model.get('remote_host'):raise RuntimeError('Local model missing')
  info=request(port,'show',{'model':QWEN_MODEL})
  if 'vision' not in info.get('capabilities',[]) or info.get('remote_host'):raise RuntimeError('Local vision model required')
  status['phase']='whole_video_windows';previous='No previous window.'
  if results:
   previous=json.dumps({'last_time_sec':results[-1]['end_sec'],'transfer_hypothesis':json.loads(results[-1]['response'])['transfer']})
  windows=list(range(0,len(frames)-1,args.window_size-1));status['window_count']=len(windows)
  for n,begin in enumerate(windows):
   if n<len(results) and n<status.get('completed_windows',0):
    # Existing results are contiguous; later iterations grow this list.
    continue
   if shutil.disk_usage(folder).free<1024**3:raise RuntimeError('Less than 1 GiB free; pause before another model load')
   indices=list(range(begin,min(begin+args.window_size,len(frames))));window=[frames[i] for i in indices]
   ids=sorted({f'ID {p["id"]}' for f in window for p in f['persons']})
   if not ids:ids=['unassigned_person']
   facts=[]
   frame_ids=[]
   for i,f in enumerate(window):
    persons=[{'id':f'ID {p["id"]}','bbox_xyxy':p['bbox'],'role_candidate':p['role'],
              'track_confirmed':p.get('track_confirmed',False),'reflection_hypothesis':p.get('is_reflection',False)} for p in f['persons']]
    facts.append({'image':i+1,'time_sec':round(f['timestamp_sec'],3),'detector_observations':persons})
    frame_ids.append([p['id'] for p in persons])
   prompt=('These are chronological security-camera images of a bank cash desk. Each image is ONE distinct moment, with the same natural camera view. '
      'Colored boxes and ID labels are detector annotations, not physical objects. IDs are tentative video-local track associations, not identities. '
      'Use the supplied IDs to distinguish people. Role candidates may be wrong; do not independently assign job roles. '
      'Focus on hands and the SAME physical object across the sequence. A stationary card/document on the desk is different from a bundle moving between hands. '
      'Do not identify banknotes or a card from the bank setting alone. If unresolved, use unclear. '
      'Direction requires before/contact/after ownership evidence; reaching alone does not establish receipt. '
      'Do not infer intent, wrongdoing, unreadable details or movement of stationary equipment. '
      'For every frame_i give one short hands observation, object_kind, holder_ids. Then give transfer from_id,to_id,phase,object_kind,evidence,uncertainty. '
      'Use concise JSON. If several distinct exchanges occur in this short window, mark the single summary unclear and explain the ambiguity. '
      '\nDETECTOR OBSERVATIONS:\n'+json.dumps(facts))
   if args.temporal:prompt+=temporal_instructions()
   if args.memory:
    prompt+='\nUNVERIFIED PREVIOUS WINDOW HYPOTHESIS:\n'+previous+'\nEND PREVIOUS HYPOTHESIS. It may be wrong; current images take precedence. '
   role_file=source/'user-role-map.local.json'
   if role_file.is_file():
    role_map=json.loads(role_file.read_text())
    if not role_map.get('client_mapping_needs_clarification',True):
     status['user_confirmed_roles']={'cashier_id':role_map['cashier_id'],'client_id':role_map['client_id']}
     prompt+=f' Human-reviewed role labels: ID {role_map["cashier_id"]} is the cashier; ID {role_map["client_id"]} is the customer. These labels do not establish object identity or a transfer.'
   response=request(port,'generate',{'model':QWEN_MODEL,'prompt':prompt,
      'images':[base64.b64encode((source/f['file']).read_bytes()).decode('ascii') for f in window],
      'format':make_schema(len(window),ids,frame_ids,args.temporal),'think':False,'stream':False,'keep_alive':'60s',
      'options':{'temperature':0,'seed':1,'repeat_penalty':1.1,'num_predict':2304 if args.temporal else 1536,'num_ctx':8192}},timeout=300)
   request(port,'generate',{'model':QWEN_MODEL,'keep_alive':0},timeout=30)
   if any(m.get('name')==QWEN_MODEL for m in request(port,'ps').get('models',[])):
    raise RuntimeError('Model unload between windows was not confirmed')
   write_json(folder/f'window-{n:02d}.local.json',{'prompt':prompt,'response':response.get('response',''),
      'frame_indices':indices,'done_reason':response.get('done_reason'),'review_status':'needs_human_review'})
   if not response.get('done') or response.get('done_reason')=='length':raise RuntimeError('Incomplete window response')
   decoded=json.loads(response['response']);schema=make_schema(len(window),ids,frame_ids,args.temporal)
   if set(decoded)!=set(schema['required']):raise RuntimeError('Invalid window structure')
   consistency_warnings=check_observation_consistency(decoded,frame_ids)
   results.append({'start_sec':window[0]['timestamp_sec'],'end_sec':window[-1]['timestamp_sec'],
                   'frame_indices':indices,'response':response['response'],'consistency_warnings':consistency_warnings})
   previous=json.dumps({'last_time_sec':round(window[-1]['timestamp_sec'],3),'transfer_hypothesis':decoded['transfer']},ensure_ascii=False)
   write_json(folder/'results.local.json',{'windows':results,'review_status':'needs_human_review'})
   status['completed_windows']=len(results);status['elapsed_sec']=round(prior_elapsed+time.monotonic()-start,3)
   status.setdefault('metrics',[]).append({k:response.get(k) for k in ('total_duration','prompt_eval_count','eval_count','done_reason')})
   write_json(folder/'status.json',status)
   print(f'Completed whole-video window {len(results)}/{len(windows)}',flush=True)
  status.update(status='completed',phase='finished',elapsed_sec=round(prior_elapsed+time.monotonic()-start,3))
  report(folder,status,frames,results,source);print('REPORT_READY:',folder/'report.html',flush=True)
 except Exception as error:
  import traceback
  status.update(status='failed',error_type=type(error).__name__)
  (folder/'error.local.txt').write_text(traceback.format_exc());print('Trial failed:',type(error).__name__,flush=True)
 finally:
  if server:
   try:request(port,'generate',{'model':QWEN_MODEL,'keep_alive':0},timeout=5)
   except Exception:pass
   server.terminate()
   try:server.wait(timeout=5)
   except subprocess.TimeoutExpired:server.kill();server.wait()
   status['server_stopped']=True
  status['elapsed_sec']=round(prior_elapsed+time.monotonic()-start,3);write_json(folder/'status.json',status)
 if status['status']!='completed':raise SystemExit(1)


if __name__=='__main__':main()
