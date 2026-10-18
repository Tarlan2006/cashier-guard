"""Evaluate a frozen door model on a new user-labeled whole video; no retraining."""
import argparse,base64,datetime,hashlib,html,json,math,time
from pathlib import Path
import cv2,numpy as np
from scene_mvp.engine import validate_profile
from scene_mvp.neural_features import FrozenDoorFeatures
from scene_mvp.door_model import score,classify,metrics,FEATURE_SPEC
from run_ollama_trial import ROOT,write_json
from scene_mvp.door_sequence_report import temporal_plan,write_report as write_temporal_report

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--profile',type=Path,required=True);args=p.parse_args();profile=json.loads(args.profile.read_text());validate_profile(profile)
 if not profile['confirmed'] or 'door_zone' not in profile['zones']:p.error('Confirmed door zone required')
 source=(ROOT/'local'/profile['source_session']).resolve()
 if not source.is_relative_to((ROOT/'local').resolve()):p.error('Invalid source session')
 session=json.loads((source/'session.local.json').read_text());plan=json.loads((source/'validation-plan.local.json').read_text());model_dir=Path(plan['model_folder']).resolve()
 if not model_dir.is_relative_to((ROOT/'local').resolve()):p.error('Invalid model path')
 meta_file=model_dir/'model-metadata.local.json';meta=json.loads(meta_file.read_text())
 if hashlib.sha256(meta_file.read_bytes()).hexdigest()!=plan['model_metadata_sha256'] or hashlib.sha256((model_dir/'door-model.npz').read_bytes()).hexdigest()!=plan['model_sha256']:p.error('Frozen model changed')
 sha=session['source_video_sha256']
 if sha!=profile['source_video_sha256'] or sha!=plan['target_video_sha256'] or sha in {s['sha256'] for s in meta['source_profiles']}:p.error('Validation video mismatch or training leakage')
 if meta['feature_spec'].get('score_cutoff')!=FEATURE_SPEC['score_cutoff']:p.error('Threshold changed')
 if 'temporal' in plan and plan['temporal']!=temporal_plan():p.error('Frozen temporal protocol changed')
 frames={round(f['timestamp_sec'],3):f for f in session['frames']};labels={}
 for label in profile.get('door_frame_labels',[]):
  t=round(label['timestamp_sec'],3)
  if t in labels or t not in frames or label['state'] not in ['open','closed','unknown'] or label.get('source')!='human_frame_label':p.error('Invalid label')
  labels[t]=label['state']
 if set(labels)!=set(frames):p.error('Every sampled moment needs a label, including explicitly unclear ones')
 selected=[t for t in sorted(frames) if labels[t]!='unknown']
 if not selected:p.error('No visually identifiable ground truth')
 start=time.monotonic();out=ROOT/'local'/('door-validation-result-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir();(out/'crops').mkdir();extractor=FrozenDoorFeatures(ROOT/'models/rtdetr_r18vd')
 if extractor.spec['weights_sha256']!=meta['feature_spec']['weights_sha256']:p.error('Representation changed')
 model=dict(np.load(model_dir/'door-model.npz',allow_pickle=False));features=[];records=[]
 # Infer every sampled frame, including human-unclear frames. Labels must not
 # decide which observations the causal state machine receives.
 for t in sorted(frames):
  frame=frames[t];file=(source/frame['file']).resolve()
  if not file.is_relative_to(source):p.error('Invalid frame path')
  image=cv2.imread(str(file));h,w=image.shape[:2];b=profile['zones']['door_zone'];bounds=[math.floor(b[0]*w),math.floor(b[1]*h),math.ceil(b[2]*w),math.ceil(b[3]*h)];crop=image[bounds[1]:bounds[3],bounds[0]:bounds[2]]
  if min(crop.shape[:2])<8:p.error('Door crop too small')
  features.append(extractor.feature(crop));name=f'crops/{len(records):03d}.png';cv2.imwrite(str(out/name),crop);records.append({'timestamp_sec':t,'expected':labels[t],'crop_file':name})
 scores=score(model,features);pred=classify(scores)
 for row,s,label in zip(records,scores,pred):row.update(predicted=label,uncalibrated_open_score=float(s))
 scored=[r for r in records if r['expected']!='unknown']
 result=metrics([r['expected'] for r in scored],[r['predicted'] for r in scored])
 summary={'video':session['source_name'],'video_sha256':sha,'model_sha256':plan['model_sha256'],'independent_new_video':True,'retrained':False,'scored_frames':len(selected),'human_unclear_excluded':len(frames)-len(selected),'metrics':result,'approved_for_rule_engine':False,'elapsed_sec':round(time.monotonic()-start,2)}
 write_json(out/'metrics.local.json',summary);write_json(out/'predictions.local.json',{'predictions':records});write_json(out/'calibration.local.json',profile)
 if 'temporal' in plan:
  temporal_summary=write_temporal_report(records,out,independent=True,source=str(source))
  summary['temporal']=temporal_summary
  write_json(out/'metrics.local.json',summary)
 names={'open':'Открыта','closed':'Закрыта','unknown':'Неясно'};rows=''.join('<tr><td>'+str(r['timestamp_sec'])+'</td><td>'+names[r['expected']]+'</td><td>'+names[r['predicted']]+'</td></tr>' for r in records);examples=''
 for r in records:
  if r['expected']==r['predicted']:continue
  uri=base64.b64encode((out/r['crop_file']).read_bytes()).decode();examples+='<article><h3>'+str(r['timestamp_sec'])+' с</h3><p>Человек: '+names[r['expected']]+'; модель: '+names[r['predicted']]+'</p><img src="data:image/png;base64,'+uri+'"></article>'
 (out/'report.html').write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'"><style>body{font:18px system-ui;max-width:1100px;margin:30px auto;padding:20px}td,th{padding:8px;border:1px solid #aaa}table{border-collapse:collapse}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:18px}img{width:100%;max-height:320px;object-fit:contain}article{background:#eef3f8;padding:15px}</style><h1>Независимая проверка двери: '+html.escape(session['source_name'])+'</h1><p>Модель, признаки и пороги зафиксированы до разметки этого видео. Обучение на нём не выполнялось. Предсказания при разметке не показывались.</p><p>Совпадения: '+str(result['correct'])+'/'+str(result['frames'])+'; неясно: '+str(result['unknown'])+'; ложное open: '+str(result['false_open_frames'])+'; пропущенное open: '+str(result['missed_open_frames'])+'.</p><p>Это один независимый ролик с зависимыми кадрами, не достаточное подтверждение общей надёжности. Автоматическое включение в правила не выполняется. Неразличимые человеческие метки исключены из оценки: '+str(summary['human_unclear_excluded'])+'.</p><h2>Ошибки и неопределённость</h2><div class="grid">'+examples+'</div><h2>Все ответы</h2><table><tr><th>Время</th><th>Метка</th><th>Модель</th></tr>'+rows+'</table>',encoding='utf-8')
 write_json(out/'status.json',{'status':'completed','approved_for_rule_engine':False,'retrained':False});print('DOOR_VALIDATION_REPORT_READY:',out/'report.html',flush=True);print(json.dumps(summary),flush=True)
if __name__=='__main__':main()
