"""Consolidate local object probes without promoting model guesses to ground truth."""
import argparse,datetime,json,html
from pathlib import Path
from run_ollama_trial import ROOT,write_json

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--trials',type=Path,nargs='+',required=True)
 args=parser.parse_args();rows=[]
 for supplied in args.trials:
  p=supplied.resolve()
  if not p.is_relative_to((ROOT/'local').resolve()):parser.error('Use local experiments')
  status=json.loads((p/'status.json').read_text())
  if status['status']!='completed':parser.error('Only completed trials')
  result=json.loads((p/'results.local.json').read_text())
  if 'cases' in result:
   observations=[{'case':x['case'],**x['response']} for x in result['cases']]
  else:
   observations=[{'case':k,**v} for k,v in result.items() if k.startswith('frame_') or k=='sequence']
  rows.append({'folder':str(p),'model':status['model'],'observations':observations,'input_scope':status.get('source_inputs',status.get('baseline_source'))})
 kinds={o['classification'] for row in rows for o in row['observations']}
 folder=ROOT/'local'/('object-experiment-review-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));folder.mkdir()
 report={'scope':{'video':'X-1.mov','time_range_sec':[21,22],'independent_examples':False,'note':'Repeated views of one short episode; not a dataset accuracy estimate'},
 'automated_observation':{'object_kind':'unclear','review_status':'not_established','usable_as_cash_specific_evidence':False,'reason_codes':['inconsistent_class_across_views_and_models','corrected_crop_still_ambiguous','self_reported_confidence_not_calibrated']},
 'human_annotation':{'object_kind':'banknotes','source':'user_explicit_corrections_in_chat','provided_to_evaluation_prompts':False,'is_model_prediction':False},
 'distinct_raw_class_count':len(kinds),'experiments':rows}
 write_json(folder/'review.local.json',report)
 names={'banknotes':'Банкноты','card':'Карта','document':'Документ','other':'Другое','none':'Предмета нет','unclear':'Неясно'}
 body=''
 for row in rows:
  cells=''.join('<tr><td>'+html.escape(o['case'])+'</td><td>'+html.escape(names[o['classification']])+'</td><td>'+html.escape(o.get('confidence','—'))+'</td></tr>' for o in row['observations'])
  body+='<h2>'+html.escape(row['model'])+'</h2><p>'+html.escape(Path(row['folder']).name)+'</p><table border="1" cellpadding="8"><tr><th>Проба</th><th>Гипотеза</th><th>Уверенность модели</th></tr>'+cells+'</table>'
 (folder/'report.html').write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><style>body{font:17px system-ui;max-width:1000px;margin:30px auto;padding:20px}table{border-collapse:collapse}p{overflow-wrap:anywhere}.note{background:#fff1d6;padding:20px}</style><h1>Итог эксперимента с типом предмета</h1><p class="note"><b>Автоматический вывод: тип предмета не установлен.</b> Ответы моделей противоречат друг другу при изменении кадра и обрезки. Они не подтверждают наличие карты и не должны служить доказательством денежных нарушений.</p><p><b>Разметка пользователя: банкноты.</b> Хранится отдельно, не выдаётся за предсказание и не передавалась в запросы этих проверок.</p><p>Повторные виды одного эпизода 21–22 с. Это не независимая выборка для оценки точности. Новое обучение или подбор запроса по этому же эпизоду не подтвердят обобщение на другие видео.</p>'+body,encoding='utf-8')
 print('REVIEW_REPORT_READY:',folder/'report.html')
 print(json.dumps({'completed_experiments':len(rows),'automated_object_type_established':False,'new_model_inference':False}))
if __name__=='__main__':main()
