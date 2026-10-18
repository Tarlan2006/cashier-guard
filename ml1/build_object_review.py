"""Create one local review page from completed object experiments; never fit models."""
import argparse,base64,datetime,html,json
from pathlib import Path
from run_ollama_trial import ROOT,write_json

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--reports',nargs='+',type=Path,required=True);p.add_argument('--inspect-tracking',action='store_true');args=p.parse_args()
 out=ROOT/'local'/('object-review-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir()
 import cv2
 rows=[];sections=[];records=[]
 names={'bag':'сумка','cash':'деньги','documents':'документы'}
 presence={'present':'в рабочей зоне','away_observed':'вне рабочей зоны','unknown':'не наблюдается / неясно'}
 for report in args.reports:
  report=report.resolve()
  if not report.is_relative_to((ROOT/'local').resolve()):p.error('Local report required')
  status=json.loads((report/'status.json').read_text())
  if status['status']!='completed':p.error('Completed report required')
  summary=json.loads((report/'summary.local.json').read_text());result=json.loads((report/'observations.local.json').read_text());profile=json.loads((report/'calibration.local.json').read_text())
  source=(ROOT/'local'/profile['source_session']).resolve()
  if not source.is_relative_to((ROOT/'local').resolve()):p.error('Local source required')
  session=json.loads((source/'session.local.json').read_text())
  if session['source_video_sha256']!=profile['source_video_sha256']:p.error('Source mismatch')
  timeline=result['timeline'];kind=summary['human_target_kind'];title=session['source_name']+' — '+names[kind];signals=result.get('experimental_signals',[])
  intervals='; '.join(f"{s['start_sec']:.2f}–{s['end_sec']:.2f} с" for s in signals) or 'сигнал не выделен'
  rows.append('<tr><td>'+html.escape(title)+'</td><td>'+intervals+'</td><td>'+str(summary['frames'])+'</td><td>'+str(summary['elapsed_sec'])+' с</td></tr>')
  anchor=min(range(len(timeline)),key=lambda i:abs(timeline[i]['timestamp_sec']-summary['anchor_sec']))
  chosen={anchor,max(0,anchor-1)}
  for s in signals:
   first=min(range(len(timeline)),key=lambda i:abs(timeline[i]['timestamp_sec']-s['start_sec']))
   last=min(range(len(timeline)),key=lambda i:abs(timeline[i]['timestamp_sec']-s['end_sec']))
   chosen.update([max(0,first-1),first,last,min(len(timeline)-1,last+1)])
  if not signals:chosen.update([0,len(timeline)//2,len(timeline)-1])
  if args.inspect_tracking:
   unknown=[i for i,row in enumerate(timeline) if row['experimental_object']['state']=='unknown']
   if unknown:chosen.add(unknown[0])
   after_anchor=[i for i in unknown if i>anchor]
   if after_anchor:chosen.update([max(0,after_anchor[0]-1),after_anchor[0],min(len(timeline)-1,after_anchor[0]+1)])
   for departure in result.get('signals',[]):
    if departure['type']=='workplace_departure':
     for t in [departure['start_sec'],departure['end_sec']]:chosen.add(min(range(len(timeline)),key=lambda i:abs(timeline[i]['timestamp_sec']-t)))
   zone=profile['zones']['object_zone' if profile.get('profile_kind')=='object_scene' else 'bag_zone']
   cx,cy=[(zone[k]+zone[k+2])/2 for k in (0,1)]
   def displacement(i):
    b=timeline[i]['experimental_object'].get('bbox')
    return max(abs((b[0]+b[2])/2-cx),abs((b[1]+b[3])/2-cy)) if b else -1
   chosen.add(max(range(len(timeline)),key=displacement))
  cards=[]
  for i in sorted(chosen):
   row=timeline[i];frame=session['frames'][i];image=cv2.imread(str(report/'overlays'/f'{i:03d}.jpg'));h,w=image.shape[:2]
   def box(b,color,label):
    x1,y1,x2,y2=[round(v*scale) for v,scale in zip(b,[w,h,w,h])]
    cv2.rectangle(image,(x1,y1),(x2,y2),color,2);cv2.putText(image,label,(x1,max(15,y1-4)),cv2.FONT_HERSHEY_SIMPLEX,.42,color,1,cv2.LINE_AA)
   box(profile['zones']['cashier_zone'],(210,50,210),'WORK ZONE')
   for person in frame['persons']:
    if person['id'] in profile['roles']['cashier_ids']:box(person['bbox'],(0,175,255),'ID '+str(person['id']))
   ok,encoded=cv2.imencode('.jpg',image)
   if not ok:raise RuntimeError('Review image encode failed')
   data=base64.b64encode(encoded.tobytes()).decode()
   cards.append('<article><b>'+f"{row['timestamp_sec']:.3f}"+' с'+(' · опорный кадр' if i==anchor else '')+'</b><img src="data:image/jpeg;base64,'+data+'"><p>Кассир: '+presence[row['cashier_presence']]+'</p></article>')
  record={'source_name':session['source_name'],'source_session':session['session_id'],'source_video_sha256':session['source_video_sha256'],'report_folder':report.name,'human_target_kind':kind,'selected_evidence_times_sec':[timeline[i]['timestamp_sec'] for i in sorted(chosen)],'candidates':signals,'summary':summary}
  records.append(record)
  n=len(records)-1
  sections.append('<section><h2>'+html.escape(title)+'</h2><p>Результат: '+intervals+'. Зелёная заливка — маска модели; синяя рамка — предмет; розовая — рабочая зона; жёлтая — трек выбранного кассира.</p><div class="grid">'+''.join(cards)+'</div><label>Зелёная маска на показанных кадрах покрывает нужный предмет? <select id="review-'+str(n)+'"><option value="">Выбери после просмотра</option><option value="correct_on_selected_frames">Да</option><option value="incorrect_on_selected_frames">Нет / местами неверно</option><option value="unclear">Не могу определить</option></select></label><details><summary>Все кадры этого ролика</summary><iframe title="'+html.escape(title,quote=True)+'" srcdoc="'+html.escape((report/'report.html').read_text(),quote=True)+'"></iframe></details></section>')
  write_json(out/(report.name+'-result.local.json'),record)
 payload=json.dumps({'schema_version':1,'review_session':out.name,'privacy':'local_only','cases':records},ensure_ascii=False).replace('<','\\u003c')
 script='''const data=__DATA__;
function saveReview(){const cases=data.cases.map((c,i)=>({...c,human_mask_review:document.getElementById('review-'+i).value,review_scope:'selected_evidence_frames_only',reviewed_at:new Date().toISOString()}));if(cases.some(c=>!c.human_mask_review)){document.getElementById('status').textContent='Выбери ответ для каждого ролика.';return;}const blob=new Blob([JSON.stringify({...data,cases,approved_for_rule_engine:false},null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=data.review_session+'-mask-review.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);document.getElementById('status').textContent='Проверка сохранена. Пришли JSON в чат.';}
'''.replace('__DATA__',payload)
 page='<!doctype html><html lang="ru"><meta charset="utf-8"><title>Сумка, документы, деньги — результаты</title><style>body{font:18px system-ui;max-width:1300px;margin:30px auto;padding:20px;background:#f5f7fb}table{border-collapse:collapse;width:100%}td,th{padding:12px;border:1px solid #ccd5df;text-align:left}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}article{background:white;padding:12px}img{width:100%}section{margin:36px 0;padding:18px;background:#eaf0f7}select,button{font:inherit;padding:12px;margin:12px}iframe{width:100%;height:950px;border:0}summary{padding:15px;cursor:pointer}</style><h1>Результаты трёх локальных запусков</h1><p>Одинаковая модель и пороги, без обучения на этих роликах. Тип предмета и рамка заданы человеком. Маска может выделять фон: это ещё не доказательство присутствия предмета или нарушения. Отсутствие сигнала не доказывает отсутствие нарушения.</p><table><tr><th>Ролик</th><th>Эпизод для проверки</th><th>Кадры</th><th>Время обработки</th></tr>'+''.join(rows)+'</table><p>Это проверка выбранных кадров, не измерение общей точности. Потеря трека кассира остаётся неизвестностью. Каждый раздел и все изображения встроены в эту страницу.</p>'+''.join(sections)+'<button onclick="saveReview()">Сохранить проверку трёх роликов</button><p id="status" role="status"></p><script>'+script+'</script></html>'
 if args.inspect_tracking:
  page=page.replace('Результаты трёх локальных запусков','SAM 2.1: отслеживание по всему кадру')
  page=page.replace('Каждый раздел и все изображения встроены в эту страницу.','Выборка охватывает весь ролик: 2 кадра/с, не каждый исходный кадр. В разделе «Все кадры этого ролика» есть воспроизведение масок. Каждый раздел и все изображения встроены в эту страницу.')
 page=page.replace('Сохранить проверку трёх роликов','Сохранить проверку')
 (out/'report.html').write_text(page,encoding='utf-8');write_json(out/'batch-results.local.json',{'schema_version':1,'cases':records,'approved_for_rule_engine':False,'human_visual_review_completed':False})
 print('OBJECT_REVIEW_READY:',out/'report.html');print(json.dumps({'cases':len(records),'selected_evidence_frames':sum(len(c['selected_evidence_times_sec']) for c in records),'automatic_accuracy_claimed':False}))

if __name__=='__main__':main()
