"""Run calibrated observations on cached tracks; emits review candidates, never legal verdicts."""
import argparse,base64,datetime,hashlib,html,json,sys
from pathlib import Path
from scene_mvp.engine import analyze
from run_ollama_trial import ROOT,write_json
from scene_mvp.experimental_door import infer as infer_door,attach_review
from scene_mvp.experimental_visitors import attach_review as attach_visitors

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--session',type=Path,required=True);p.add_argument('--calibration',type=Path);p.add_argument('--experimental-door-model',type=Path);p.add_argument('--experimental-visitors',action='store_true');args=p.parse_args();source=args.session.resolve()
 if not source.is_relative_to((ROOT/'local').resolve()):p.error('Use local scene session')
 session=json.loads((source/'session.local.json').read_text());calibration=args.calibration or source/'calibration-draft.local.json';profile=json.loads(calibration.read_text())
 if profile.get('source_session')!=session['session_id']:p.error('Calibration and track session differ')
 ids={p['id'] for f in session['frames'] for p in f['persons']}
 if any(i not in ids for values in profile.get('roles',{}).values() for i in values):p.error('Role ID absent from source tracks')
 times={round(f['timestamp_sec'],3) for f in session['frames']};door={}
 for label in profile.get('door_frame_labels',[]):
  t=round(label['timestamp_sec'],3)
  if t not in times or t in door:p.error('Door labels must match unique sampled moments')
  door[t]={'state':label['state'],'source':label['source']}
 # In model mode, human door labels are not passed to scene analysis.
 result=analyze(session['frames'],profile,session['source_video_sha256'],{} if args.experimental_door_model else door)
 if args.experimental_door_model:
  model_dir=args.experimental_door_model.resolve()
  if not model_dir.is_relative_to((ROOT/'local').resolve()):p.error('Use local experimental door model')
  observations,provenance=infer_door(session,source,profile,model_dir,ROOT/'models/rtdetr_r18vd')
  attach_review(result,observations,profile.get('stability_sec',1),profile.get('max_gap_sec',1))
  result['experimental_door_provenance']=provenance
 if args.experimental_visitors:attach_visitors(result,profile)
 folder=ROOT/'local'/('scene-result-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));folder.mkdir();write_json(folder/'calibration.local.json',profile);write_json(folder/'observations.local.json',result)
 write_json(folder/'status.json',{'status':'completed','analysis_status':result['status'],'source_session':str(source),'source_video_sha256':session['source_video_sha256'],'calibration_sha256':hashlib.sha256(calibration.read_bytes()).hexdigest(),'engine_sha256':hashlib.sha256((ROOT/'scene_mvp/engine.py').read_bytes()).hexdigest(),'cloud_inference_used':False,'vlm_used':False,'production_ml1_contract_modified':False})
 esc=html.escape;names={'workplace_departure':'Отход от рабочего места','multiple_visitors_in_service_zone':'Несколько посетителей в зоне обслуживания','door_open_while_cashier_away':'Открытая дверь при наблюдаемом отходе кассира','additional_visitor_near_service_zone':'Второй посетитель рядом с зоной обслуживания'}
 by_time={round(f['timestamp_sec'],3):f for f in session['frames']}
 def picture(t):
  frame=by_time.get(round(t,3))
  if not frame:return ''
  uri=base64.b64encode((source/frame['file']).read_bytes()).decode()
  return '<div><h4>'+str(round(t,3))+' с</h4><img src="data:image/jpeg;base64,'+uri+'"></div>'
 cards=''
 for signal in result['signals']+result.get('experimental_signals',[]):
  cards+='<article><h2>'+esc(('Эксперимент: ' if signal.get('status')=='experimental_review_candidate' else '')+names[signal['type']])+'</h2><p>'+str(signal['start_sec'])+'–'+str(signal['end_sec'])+' с · ID '+esc(', '.join(map(str,signal['participant_ids'])))+'</p><p>'+esc(signal['explanation'])+'</p><p><b>Кандидат для проверки, не установленное нарушение.</b></p><div class="grid">'+''.join(picture(t) for t in signal['evidence_times_sec'])+'</div></article>'
 if args.experimental_door_model:
  provenance=result['experimental_door_provenance']
  cards='<p class="note"><b>Экспериментальная дверь:</b> ответы локальной модели; человеческие метки двери не использованы. Автоматические правовые выводы отключены. '+('Этот ролик участвовал в обучении модели двери: здесь проверяется интеграция, не точность.' if provenance['video_seen_in_training'] else 'Ролик не участвовал в обучении модели двери.')+'</p>'+cards
 if args.experimental_visitors:cards='<p class="note">Эксперимент приближения: учитывается частичное пересечение рамки посетителя с подтверждённой зоной (от 10% площади рамки, не менее 1 с). Это не распознавание начала обслуживания или передачи предмета. Порог выбран при разработке; нужна проверка на отрицательном примере.</p>'+cards
 presence={'present':'Наблюдается на рабочем месте','away_observed':'Наблюдается вне рабочей зоны','unknown':'Не установлено'}
 if args.experimental_door_model:
  # Presentation only; preserve the original door channel in saved JSON.
  display_result=json.loads(json.dumps(result))
  for row in display_result['timeline']:row['door']=dict(row['experimental_door'],state={'open':'Открыта · модель','closed':'Закрыта · модель','unknown':'Неясно · модель'}[row['experimental_door']['state']])
 else:display_result=result
 rows=''.join('<tr><td>'+str(round(r['timestamp_sec'],3))+'</td><td>'+presence[r['cashier_presence']]+'</td><td>'+str(r['visitor_count'] if r['visitor_count'] is not None else 'Не установлено')+'</td><td>'+esc(r['door']['state'])+'</td></tr>' for r in display_result['timeline'])
 notice=('Калибровка не подтверждена: события отключены. Сначала выдели и проверь зоны камеры.' if result['status']=='needs_calibration' else 'Анализ частичный. Количество посетителей — наблюдаемые треки, не доказательство обслуживания. Дверь показана с указанием источника; неясный ответ не означает закрытую дверь. Пустой список сигналов не подтверждает отсутствие нарушений.')
 (folder/'report.html').write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'"><style>body{font:17px system-ui;max-width:1200px;margin:30px auto;padding:20px}article{background:#eef3f8;padding:20px;margin:20px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:20px}img{width:100%}td,th{padding:8px;border:1px solid #aaa}table{border-collapse:collapse}.note{padding:18px;background:#fff1cf}</style><h1>Наблюдения → события → сигналы</h1><p>'+esc(session['source_name'])+'</p><p class="note">'+notice+'</p><p>Источник: локальные RT-DETR-треки и проверяемая геометрия. LLM не используется. 1 с — технический порог устойчивости, не банковский норматив. Допуск к границе зоны: 0,015 размера кадра по каждой оси, если в профиле не задан другой. Подтверждённые пользователем ID с детекцией не ниже 0,5 учитываются до автоматического подтверждения трекера; отражения, неопределённые треки и предсказанные без наблюдения рамки по-прежнему исключены. Деньги, пересчёт, идентификация клиента и блокировка экрана не проверяются.</p><p><a href="'+esc(str(source/'calibrate.html'),quote=True)+'">Страница калибровки</a></p><h2>Сигналы: '+str(len(result['signals']))+'; экспериментальных: '+str(len(result.get('experimental_signals',[])))+'</h2>'+cards+'<h2>Хронология</h2><table><tr><th>Время</th><th>Кассир</th><th>Наблюдаемые посетители</th><th>Дверь</th></tr>'+rows+'</table>',encoding='utf-8')
 print('SCENE_REPORT_READY:',folder/'report.html',flush=True);print(json.dumps({'analysis_status':result['status'],'timeline_frames':len(result['timeline']),'review_candidates':len(result['signals']),'experimental_review_candidates':len(result.get('experimental_signals',[])),'legal_verdicts':0}))
if __name__=='__main__':main()
