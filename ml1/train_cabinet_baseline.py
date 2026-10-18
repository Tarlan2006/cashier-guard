"""Fit and cross-video evaluate a local cash-cabinet baseline; never enable production rules."""
import argparse,base64,datetime,hashlib,html,json,math,sys,time
from pathlib import Path
import cv2,numpy as np
from scene_mvp.engine import validate_profile
from scene_mvp.cabinet_model import validate_fixture_data,TARGET
from scene_mvp.door_model import feature,fit,score,classify,metrics,FEATURE_SPEC
from run_ollama_trial import ROOT,write_json

RUN_FOLDER=None
def main():
 global RUN_FOLDER
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--profiles',type=Path,nargs='+',required=True);p.add_argument('--features',choices=['hog','rtdetr-backbone'],default='rtdetr-backbone');p.add_argument('--roi-mode',choices=['annotated','union-exploratory'],default='annotated');args=p.parse_args();start=time.monotonic()
 feature_fn=feature;feature_spec=dict(FEATURE_SPEC);model_name='HOG + balanced L2 logistic regression'
 if args.features=='rtdetr-backbone':
  from scene_mvp.neural_features import FrozenDoorFeatures
  extractor=FrozenDoorFeatures(ROOT/'models/rtdetr_r18vd');feature_fn=extractor.feature;feature_spec=dict(extractor.spec,regularization=FEATURE_SPEC['regularization'],score_cutoff=FEATURE_SPEC['score_cutoff']);model_name='Frozen RT-DETR R18 features + balanced L2 logistic regression'
  print('Loaded verified local frozen backbone on CPU',flush=True)
 documents=[json.loads(file.read_text()) for file in args.profiles]
 for d in documents:
  validate_profile(d)
  if d.get('profile_kind')!='fixture_only' or d.get('fixture_kind')!=TARGET:raise ValueError('Cabinet-only profiles required')
  if not d['confirmed'] or 'safe_zone' not in d['zones']:raise ValueError('Confirmed cabinet zone required')
 rois=[d['zones']['safe_zone'] for d in documents];union_roi=[min(b[0] for b in rois),min(b[1] for b in rois),max(b[2] for b in rois),max(b[3] for b in rois)]
 folder=ROOT/'local'/('cabinet-baseline-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));folder.mkdir();RUN_FOLDER=folder;(folder/'crops').mkdir();groups=[];seen=set();write_json(folder/'status.json',{'status':'running','approved_for_rule_engine':False})
 protocol={'target_kind':TARGET,'features':feature_spec,'validation':'leave_one_whole_video_out','tuning_on_validation':args.roi_mode!='annotated','roi_mode':args.roi_mode,'independent_new_validation':False,'sampling_unit':'video','frame_independence':False,'approved_for_rule_engine':False}
 write_json(folder/'protocol.local.json',protocol)
 for file in args.profiles:
  profile=json.loads(file.read_text());validate_profile(profile)
  if not profile['confirmed'] or 'safe_zone' not in profile['zones']:raise ValueError('Confirmed cabinet zone required')
  session_path=(ROOT/'local'/profile['source_session']).resolve()
  if not session_path.is_relative_to((ROOT/'local').resolve()):raise ValueError('Invalid session path')
  session=json.loads((session_path/'session.local.json').read_text());validate_fixture_data(profile,session);sha=session['source_video_sha256']
  if sha!=profile['source_video_sha256'] or sha in seen:raise ValueError('Mismatched or repeated video')
  seen.add(sha);lookup={round(f['timestamp_sec'],3):f for f in session['frames']};rows=[];times=set()
  for label in profile.get('fixture_frame_labels',[]):
   t=round(label['timestamp_sec'],3)
   if t not in lookup or t in times or label.get('source')!='human_frame_label':raise ValueError('Invalid label time/source')
   times.add(t)
   if label['state']=='unknown':continue
   if label['state'] not in ['closed','open']:raise ValueError('Invalid state')
   f=lookup[t];path=(session_path/f['file']).resolve()
   if not path.is_relative_to(session_path):raise ValueError('Invalid frame path')
   image=cv2.imread(str(path));h,w=image.shape[:2];b=profile['zones']['safe_zone'] if args.roi_mode=='annotated' else union_roi;bounds=[math.floor(b[0]*w),math.floor(b[1]*h),math.ceil(b[2]*w),math.ceil(b[3]*h)];crop=image[bounds[1]:bounds[3],bounds[0]:bounds[2]]
   if min(crop.shape[:2])<8:raise ValueError('Cabinet ROI too small')
   name=f'crops/{len(groups):02d}-{len(rows):03d}.png';cv2.imwrite(str(folder/name),crop)
   rows.append({'timestamp_sec':t,'state':label['state'],'feature':feature_fn(crop),'crop_file':name,'crop_size_px':[crop.shape[1],crop.shape[0]]})
  rows.sort(key=lambda r:r['timestamp_sec'])
  if {r['state'] for r in rows}!={'closed','open'}:raise ValueError('Each video needs both cabinet states')
  groups.append({'video':session['source_name'],'sha256':sha,'rows':rows,'profile_file':str(file.resolve()),'profile_sha256':hashlib.sha256(file.read_bytes()).hexdigest()})
 if len(groups)<2:raise ValueError('At least two distinct videos required')
 folds=[];all_expected=[];all_predicted=[];predictions=[]
 for i,test in enumerate(groups):
  train=[r for j,g in enumerate(groups) if j!=i for r in g['rows']];test_rows=test['rows'];model=fit([r['feature'] for r in train],[r['state']=='open' for r in train]);scores=score(model,[r['feature'] for r in test_rows]);pred=classify(scores);expected=[r['state'] for r in test_rows]
  fold={'test_video':test['video'],'train_videos':[g['video'] for j,g in enumerate(groups) if j!=i],'test_sha256':test['sha256'],'metrics':metrics(expected,pred)};folds.append(fold);all_expected.extend(expected);all_predicted.extend(pred)
  predictions.extend({'video':test['video'],'video_sha256':test['sha256'],'timestamp_sec':r['timestamp_sec'],'expected':r['state'],'predicted':label,'uncalibrated_open_score':float(s),'crop_file':r['crop_file'],'crop_size_px':r['crop_size_px'],'out_of_video_prediction':True} for r,label,s in zip(test_rows,pred,scores))
  print('Completed held-out-video fold',i+1,'/',len(groups),flush=True)
 final_rows=[r for g in groups for r in g['rows']];model=fit([r['feature'] for r in final_rows],[r['state']=='open' for r in final_rows]);np.savez(folder/'cabinet-model.npz',**{k:v for k,v in model.items() if k!='iterations'})
 total=metrics(all_expected,all_predicted);open_episodes=0
 for g in groups:
  previous=None
  for r in g['rows']:
   if r['state']=='open' and previous!='open':open_episodes+=1
   previous=r['state']
 metadata={'schema_version':1,'target_kind':TARGET,'model':model_name,'model_sha256':hashlib.sha256((folder/'cabinet-model.npz').read_bytes()).hexdigest(),'source_profiles':[{k:g[k] for k in ['video','sha256','profile_file','profile_sha256']} for g in groups],'validation':{'folds':folds,'aggregate':total,'open_episodes':open_episodes,'video_count':len(groups)},'approved_for_rule_engine':False,'deployment_status':'experimental_only','reasons':['small_video_and_event_count','frames_within_video_are_correlated','requires_additional_independent_positive_and_negative_episodes'],'feature_spec':feature_spec,'protocol':protocol}
 write_json(folder/'model-metadata.local.json',metadata);
 for i,file in enumerate(args.profiles):write_json(folder/f'profile-{i:02d}.local.json',json.loads(file.read_text()))
 write_json(folder/'predictions.local.json',{'predictions':predictions});write_json(folder/'metrics.local.json',{'folds':folds,'aggregate':total,'video_count':len(groups),'open_episodes':open_episodes})
 names={'open':'Открыта','closed':'Закрыта','unknown':'Неясно'}
 summary=''.join('<tr><td>'+html.escape(f['test_video'])+'</td><td>'+html.escape(', '.join(f['train_videos']))+'</td><td>'+str(f['metrics']['correct'])+'/'+str(f['metrics']['frames'])+'</td><td>'+str(f['metrics']['unknown'])+'</td><td>'+str(f['metrics']['false_open_frames'])+'</td><td>'+str(f['metrics']['missed_open_frames'])+'</td></tr>' for f in folds)
 rows=''.join('<tr><td>'+html.escape(r['video'])+'</td><td>'+str(r['timestamp_sec'])+'</td><td>'+names[r['expected']]+'</td><td>'+names[r['predicted']]+'</td><td>'+str(round(r['uncalibrated_open_score'],3))+'</td></tr>' for r in predictions)
 # Only mistakes/abstentions shown as image examples, all predictions remain in JSON/table.
 examples=''
 for r in predictions:
  if r['expected']==r['predicted']:continue
  uri=base64.b64encode((folder/r['crop_file']).read_bytes()).decode();examples+='<article><h3>'+html.escape(r['video'])+' · '+str(r['timestamp_sec'])+' с</h3><p>Метка: '+names[r['expected']]+'; модель: '+names[r['predicted']]+'</p><img src="data:image/png;base64,'+uri+'"></article>'
 representation_note='<p class="note">Это первый эксперимент модели дверцы шкафа. Подход с замороженными нейросетевыми признаками выбран ранее; веса входной двери не используются. Нейросеть заморожена, обучается отдельная линейная голова. Два ролика не подтверждают общую надёжность.</p>'
 exploratory=('<p class="note"><b>Это дополнительный эксперимент после просмотра исходной проверки.</b> Для обоих видео взято объединение двух областей шкафа. Эти видео уже использовались при выборе подхода: результат не является новой независимой проверкой. Параметры классификатора не менялись.</p>' if args.roi_mode!='annotated' else '')
 (folder/'report.html').write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'"><style>body{font:17px system-ui;max-width:1200px;margin:30px auto;padding:20px}table{border-collapse:collapse}td,th{padding:8px;border:1px solid #aaa}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:18px}article{background:#eef3f8;padding:15px}img{width:100%;max-height:350px;object-fit:contain}.note{background:#fff0ce;padding:16px}</style><h1>Локальная модель дверцы шкафа для денег</h1>'+exploratory+representation_note+'<p>'+html.escape(model_name)+'. Без LLM, GPU и сетевой передачи кадров.</p><p class="note">Модель экспериментальная и не включена в правила. Поочерёдно целое видео отложено для проверки, обучение использовало только другое видео. После оценки отдельная итоговая модель обучена на всех метках; её обучающая точность не выдаётся за независимую проверку. Два коротких видео / '+str(open_episodes)+' эпизода открытия недостаточны для вывода о надёжности. Score не является калиброванной вероятностью.</p><table><tr><th>Проверка</th><th>Обучение</th><th>Совпадения</th><th>Неясно</th><th>Ложное open</th><th>Пропущенное open</th></tr>'+summary+'</table><h2>Ошибки и неопределённые ответы</h2><div class="grid">'+examples+'</div><h2>Все предсказания на отложенных видео</h2><table><tr><th>Видео</th><th>Время</th><th>Человек</th><th>Модель</th><th>Score open</th></tr>'+rows+'</table>',encoding='utf-8')
 write_json(folder/'status.json',{'status':'completed','elapsed_sec':round(time.monotonic()-start,2),'frames':len(predictions),'videos':len(groups),'approved_for_rule_engine':False,'cloud_used':False})
 print('CABINET_BASELINE_REPORT_READY:',folder/'report.html',flush=True);print(json.dumps({'aggregate':total,'video_count':len(groups),'open_episodes':open_episodes,'elapsed_sec':round(time.monotonic()-start,2),'approved_for_rule_engine':False,'target_kind':TARGET}),flush=True)
if __name__=='__main__':
 try:main()
 except Exception as error:
  if RUN_FOLDER is not None:write_json(RUN_FOLDER/'status.json',{'status':'failed','error_type':type(error).__name__,'approved_for_rule_engine':False})
  raise
