"""Evaluate frozen cabinet head on a newly labeled video; never retrain."""
import argparse,base64,datetime,hashlib,html,json,math,time
from pathlib import Path
import cv2,numpy as np
from run_ollama_trial import ROOT,write_json
from scene_mvp.cabinet_model import validate_fixture_data,TARGET
from scene_mvp.neural_features import FrozenDoorFeatures
from scene_mvp.door_model import score,classify,metrics,FEATURE_SPEC
from scene_mvp.door_temporal import episodes

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--profile',type=Path,required=True);args=p.parse_args();profile=json.loads(args.profile.read_text())
 source=(ROOT/'local'/profile['source_session']).resolve()
 if not source.is_relative_to((ROOT/'local').resolve()):p.error('Local session required')
 session=json.loads((source/'session.local.json').read_text());labels=validate_fixture_data(profile,session)
 plan=json.loads((source/'validation-plan.local.json').read_text());modeldir=Path(plan['model_folder']).resolve()
 if not modeldir.is_relative_to((ROOT/'local').resolve()):p.error('Local cabinet model required')
 metafile=modeldir/'model-metadata.local.json';meta=json.loads(metafile.read_text())
 if plan['target_kind']!=TARGET or meta['target_kind']!=TARGET:p.error('Wrong target model')
 if hashlib.sha256(metafile.read_bytes()).hexdigest()!=plan['model_metadata_sha256'] or hashlib.sha256((modeldir/'cabinet-model.npz').read_bytes()).hexdigest()!=plan['model_sha256']:p.error('Frozen model changed')
 sha=session['source_video_sha256']
 if sha!=plan['target_video_sha256'] or sha in {v['sha256'] for v in meta['source_profiles']}:p.error('Video mismatch or training leakage')
 if plan['feature_spec']!=meta['feature_spec'] or meta['feature_spec']['score_cutoff']!=FEATURE_SPEC['score_cutoff']:p.error('Protocol changed')
 if not any(x!='unknown' for x in labels.values()):p.error('No scoreable labels')
 start=time.monotonic();extractor=FrozenDoorFeatures(ROOT/'models/rtdetr_r18vd')
 if any(meta['feature_spec'].get(k)!=v for k,v in extractor.spec.items()):p.error('Representation mismatch')
 model=dict(np.load(modeldir/'cabinet-model.npz',allow_pickle=False));out=ROOT/'local'/('cabinet-validation-result-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir();(out/'crops').mkdir();rows=[];features=[]
 for f in sorted(session['frames'],key=lambda f:f['timestamp_sec']):
  file=(source/f['file']).resolve()
  if not file.is_relative_to(source):p.error('Invalid frame path')
  image=cv2.imread(str(file))
  if image is None:p.error('Missing cached frame')
  h,w=image.shape[:2];b=profile['zones']['safe_zone'];bounds=[math.floor(b[0]*w),math.floor(b[1]*h),math.ceil(b[2]*w),math.ceil(b[3]*h)];crop=image[bounds[1]:bounds[3],bounds[0]:bounds[2]]
  if min(crop.shape[:2])<8:p.error('Cabinet ROI too small')
  features.append(extractor.feature(crop));name=f'crops/{len(rows):03d}.png';cv2.imwrite(str(out/name),crop)
  rows.append({'timestamp_sec':f['timestamp_sec'],'expected':labels[round(f['timestamp_sec'],3)],'crop_file':name})
 scores=score(model,features)
 for row,s,state in zip(rows,scores,classify(scores)):row.update(predicted=state,uncalibrated_open_score=float(s))
 selected=[r for r in rows if r['expected']!='unknown'];m=metrics([r['expected'] for r in selected],[r['predicted'] for r in selected])
 summary={'target_kind':TARGET,'video':session['source_name'],'video_sha256':sha,'independent_new_video':True,'retrained':False,'model_sha256':plan['model_sha256'],'metrics':m,'human_unclear_excluded':len(rows)-len(selected),'predicted_open_runs':episodes(rows,'predicted'),'approved_for_rule_engine':False,'elapsed_sec':round(time.monotonic()-start,2)}
 write_json(out/'metrics.local.json',summary);write_json(out/'predictions.local.json',{'predictions':rows});write_json(out/'calibration.local.json',profile)
 names={'open':'Открыта','closed':'Закрыта','unknown':'Неясно'};examples=''
 for row in selected:
  if row['expected']==row['predicted']:continue
  uri=base64.b64encode((out/row['crop_file']).read_bytes()).decode();examples+='<article><h3>'+str(row['timestamp_sec'])+' с</h3><p>Человек: '+names[row['expected']]+'; модель: '+names[row['predicted']]+'</p><img src="data:image/png;base64,'+uri+'"></article>'
 table=''.join('<tr><td>'+str(r['timestamp_sec'])+'</td><td>'+names[r['expected']]+'</td><td>'+names[r['predicted']]+'</td></tr>' for r in rows)
 text='<!doctype html><html lang="ru"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'"><style>body{font:18px system-ui;max-width:1100px;margin:30px auto;padding:20px}table{border-collapse:collapse}td,th{border:1px solid #aaa;padding:9px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:18px}img{width:100%;max-height:350px;object-fit:contain}</style><h1>Независимая проверка дверцы шкафа: '+html.escape(session['source_name'])+'</h1><p>Модель и пороги зафиксированы до разметки. Переобучения не было. Предсказания при разметке не показывались.</p><p>Совпадений: '+str(m['correct'])+'/'+str(m['frames'])+'; ложных открытий: '+str(m['false_open_frames'])+'; открыта → закрыта: '+str(m['missed_open_frames'])+'; неясно: '+str(m['unknown'])+'.</p><p>Один ролик не устанавливает общую точность. Состояние створки не доказывает наличие денег, состояние замка или нарушение. Автоматическое включение в правила отключено.</p><h2>Ошибки и неопределённость</h2><div class="grid">'+examples+'</div><h2>Хронология</h2><table><tr><th>Время</th><th>Человек</th><th>Модель</th></tr>'+table+'</table></html>'
 (out/'report.html').write_text(text);write_json(out/'status.json',{'status':'completed','approved_for_rule_engine':False});print('CABINET_VALIDATION_REPORT_READY:',out/'report.html');print(json.dumps(summary))

if __name__=='__main__':main()
