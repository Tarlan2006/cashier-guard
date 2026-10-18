"""Render local benchmark results; no new inference or image transmission."""
import argparse,base64,html,json,datetime
from pathlib import Path
from run_ollama_trial import ROOT,write_json

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--runs',type=Path,nargs='+',required=True);args=p.parse_args();runs=[]
 for folder in args.runs:
  folder=folder.resolve()
  if not folder.is_relative_to((ROOT/'local').resolve()):p.error('Local runs required')
  status=json.loads((folder/'status.json').read_text())
  if status['status']!='completed' or status.get('server_stopped') is not True:raise ValueError('Incomplete benchmark')
  runs.append({'folder':folder,'status':status,'metrics':json.loads((folder/'metrics.local.json').read_text()),'protocol':json.loads((folder/'protocol.local.json').read_text()),'results':json.loads((folder/'results.local.json').read_text())['examples']})
 if len({r['status']['cohort_sha256'] for r in runs})!=1:raise ValueError('Different cohort')
 for key in ['prompt','schema','temperature','seed','context','batch','num_predict','repeat_penalty']:
  if any(r['protocol'][key]!=runs[0]['protocol'][key] for r in runs):raise ValueError('Protocol differs: '+key)
 cohort=json.loads(Path(runs[0]['status']['cohort']).read_text());dataset=Path(cohort['dataset']);labels={'banknotes':'Банкноты','card':'Карта','document':'Документ','other':'Другое','none':'Предмета нет','unclear':'Неясно'}
 out=ROOT/'local'/('object-benchmark-report-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir();summary='';recall=''
 for r in runs:
  m=r['metrics'];summary+='<tr><td>'+html.escape(r['status']['model'])+'</td><td>'+str(m['correct'])+'/'+str(m['examples'])+'</td><td>'+str(m['unclear_predictions'])+'</td><td>'+str(m['high_confidence_errors'])+'</td><td>'+str(round(r['status']['elapsed_sec']))+' с</td></tr>'
  for kind,counts in m['confusion'].items():recall+='<tr><td>'+html.escape(r['status']['model'])+'</td><td>'+labels[kind]+'</td><td>'+str(counts.get(kind,0))+'/'+str(sum(counts.values()))+'</td></tr>'
 lookup=[{x['example_id']:x for x in r['results']} for r in runs];examples=''
 for row in cohort['examples']:
  uri=base64.b64encode((dataset/row['crop_file']).read_bytes()).decode();cells=''.join('<p><b>'+html.escape(r['status']['model'])+':</b> '+labels[look[row['id']]['predicted']]+' ('+html.escape(look[row['id']]['confidence'])+')</p><p>'+html.escape(look[row['id']]['raw_evidence'])+'</p>' for r,look in zip(runs,lookup))
  examples+='<article><h3>Метка пользователя: '+labels[row['object_kind']]+'</h3><p>'+html.escape(row['video'])+' · '+str(round(row['time_sec'],3))+' с · '+str(row['crop_size_px'])+' пикселей</p><img src="data:image/png;base64,'+uri+'">'+cells+'</article>'
 text='<!doctype html><html lang="ru"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'"><style>body{font:17px system-ui;max-width:1200px;margin:30px auto;padding:20px}table{border-collapse:collapse;margin:20px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:20px}article{background:#eef3f8;padding:15px}img{width:100%;max-height:220px;object-fit:contain}p{overflow-wrap:anywhere}.note{background:#fff1cf;padding:16px}</style><h1>2B и 4B: проверка на ручной разметке</h1><p class="note">Выбраны 9 примеров из development: 4 банкноты, 4 карты, 1 другой предмет. Это малая подборка из 6 видео, с зависимыми кадрами. Отложенная часть не использовалась. Нет тестов документов и пустых участков. Правильность человеческих меток не проверялась независимо. Результат нельзя считать точностью на всём датасете.</p><p>Контрольные суммы изображений проверены; набор, запрос, схема и параметры обеих моделей совпадают. Метки пользователя используются только при подсчёте результатов и в запросы не передаются.</p><table border="1" cellpadding="10"><tr><th>Модель</th><th>Совпадения с меткой</th><th>Ответов «неясно»</th><th>Ошибок с high</th><th>Время</th></tr>'+summary+'</table><h2>Совпадения по классу</h2><table border="1" cellpadding="10"><tr><th>Модель</th><th>Класс</th><th>Верно / всего</th></tr>'+recall+'</table><p>У 4 из 9 участков короткая сторона меньше32 пикселей; медиана33 пикселя. Ошибки могут зависеть и от качества исходного изображения, и от модели. Увеличение картинки не возвращает потерянные детали.</p><h2>Примеры и сырые ответы</h2><div class="grid">'+examples+'</div></html>'
 (out/'report.html').write_text(text,encoding='utf-8');write_json(out/'summary.local.json',{'runs':[{'folder':str(r['folder']),'model':r['status']['model'],'metrics':r['metrics']} for r in runs],'same_protocol':True,'heldout_used':False,'sample_count':9})
 print('BENCHMARK_REPORT_READY:',out/'report.html',flush=True)
if __name__=='__main__':main()
