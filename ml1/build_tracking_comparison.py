"""Local visual comparison of prompted framewise segmentation and temporal tracking."""
import argparse,base64,datetime,html,json,statistics
from pathlib import Path
from run_ollama_trial import ROOT,write_json

def load(folder):
 folder=folder.resolve()
 if not folder.is_relative_to((ROOT/'local').resolve()):raise ValueError('Local report required')
 if json.loads((folder/'status.json').read_text())['status']!='completed':raise ValueError('Report incomplete')
 return {key:json.loads((folder/name).read_text()) for key,name in [('summary','summary.local.json'),('result','observations.local.json'),('profile','calibration.local.json')]}

def overlap(a,b):
 if not a or not b:return None
 v=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]));u=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-v
 return v/u if u else 0

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--human-review',type=Path,required=True);p.add_argument('--tracking',nargs='+',type=Path,required=True);args=p.parse_args()
 human=json.loads(args.human_review.read_text());baselines={c['source_session']:c for c in human['cases']}
 out=ROOT/'local'/('tracking-comparison-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir()
 sections=[];table=[];cases=[]
 for folder in args.tracking:
  track=load(folder);profile=track['profile'];base_ref=baselines[profile['source_session']];baseline_folder=ROOT/'local'/base_ref['report_folder'];base=load(baseline_folder)
  assert track['summary']['mode']=='video' and base['summary']['mode']=='framewise'
  assert profile==base['profile'] and track['summary']['focus_crop_px']==base['summary']['focus_crop_px']
  assert track['summary']['anchor_sec']==base['summary']['anchor_sec']
  a=base['result']['timeline'];b=track['result']['timeline'];assert len(a)==len(b)
  for x,y in zip(a,b):assert x['timestamp_sec']==y['timestamp_sec']
  scores=[overlap(x['experimental_object']['bbox'],y['experimental_object']['bbox']) for x,y in zip(a,b)]
  same=[v for v in scores if v is not None]
  selected={min(range(len(a)),key=lambda i:abs(a[i]['timestamp_sec']-t)) for t in base_ref['selected_evidence_times_sec']}
  # Show the largest disagreement and a missing-mask example, without calling either output ground truth.
  differences=sorted(range(len(a)),key=lambda i:-1 if scores[i] is None else scores[i])
  selected.update(differences[:2])
  name=base_ref.get('source_name') or json.loads((ROOT/'local'/profile['source_session']/'session.local.json').read_text())['source_name']
  def intervals(result):return '; '.join(f"{s['start_sec']:.2f}–{s['end_sec']:.2f} с" for s in result.get('experimental_signals',[])) or 'сигнал не выделен'
  record={'source_name':name,'source_session':profile['source_session'],'source_video_sha256':profile['source_video_sha256'],'baseline_report':baseline_folder.name,'tracking_report':folder.name,'human_target_kind':profile['target_object_kind'],'selected_evidence_times_sec':[a[i]['timestamp_sec'] for i in sorted(selected)],'baseline_summary':base['summary'],'tracking_summary':track['summary'],'median_box_iou_between_methods_not_accuracy':statistics.median(same) if same else None,'baseline_review_scope':'selected_evidence_frames_only','baseline_human_review':base_ref['human_mask_review'],'baseline_candidates':base['result'].get('experimental_signals',[]),'tracking_candidates':track['result'].get('experimental_signals',[]),'same_crop_and_anchor':True,'requires_human_tracking_review':track['summary']['mask_observed_frames']>1}
  cases.append(record)
  table.append('<tr><td>'+html.escape(name)+'</td><td>'+str(base['summary']['mask_observed_frames'])+'/'+str(len(a))+' · '+str(base['summary']['elapsed_sec'])+' с</td><td>'+str(track['summary']['mask_observed_frames'])+'/'+str(len(a))+' · '+str(track['summary']['elapsed_sec'])+' с</td></tr>')
  def pair(i):
   images=[]
   for label,src,row in [('Покадровая сегментация',baseline_folder,a[i]),('Отслеживание',folder,b[i])]:
    data=base64.b64encode((src/'overlays'/f'{i:03d}.jpg').read_bytes()).decode()
    text='маска получена' if row['experimental_object']['state']=='mask_observed' else 'маска неизвестна'
    images.append('<article><b>'+label+'</b><p>'+text+'</p><img src="data:image/jpeg;base64,'+data+'"></article>')
   return '<div class="pair"><h3>'+f"{a[i]['timestamp_sec']:.3f}"+' с</h3><div class="grid">'+''.join(images)+'</div></div>'
  remaining=[i for i in range(len(a)) if i not in selected]
  options='<option value="">Выбери после просмотра</option><option value="correct_on_selected_frames">Да, маска верна</option><option value="incorrect_on_selected_frames">Нет / местами неверна</option><option value="unclear">Не могу определить</option>'
  review_control='<label>Маска отслеживания справа покрывает нужный предмет на показанных кадрах? <select id="review-'+str(len(cases)-1)+'">'+options+'</select></label>' if record['requires_human_tracking_review'] else '<p><b>Отслеживание не прошло техническую проверку:</b> маска получена только на опорном кадре. Дополнительная ручная проверка здесь не требуется.</p>'
  sections.append('<section><h2>'+html.escape(name)+'</h2><p>Покадровый сигнал: '+intervals(base['result'])+'. Сигнал отслеживания: '+intervals(track['result'])+'.</p>'+''.join(pair(i) for i in sorted(selected))+review_control+'<details><summary>Остальные кадры — тоже попарно</summary>'+''.join(pair(i) for i in remaining)+'</details></section>')
 payload=json.dumps({'schema_version':1,'review_session':out.name,'cases':cases,'approved_for_rule_engine':False,'tracking_default_enabled':False},ensure_ascii=False).replace('<','\\u003c')
 script='''const data=__DATA__;function saveReview(){const cases=data.cases.map((c,i)=>({...c,human_tracking_mask_review:document.getElementById('review-'+i)?.value??null,review_scope:'selected_evidence_frames_only',reviewed_at:new Date().toISOString()}));if(cases.some(c=>c.requires_human_tracking_review&&!c.human_tracking_mask_review)){document.getElementById('status').textContent='Проверь маску сумки: для документов и денег отслеживание уже отклонено технической проверкой.';return;}const blob=new Blob([JSON.stringify({...data,cases},null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=data.review_session+'-tracking-mask-review.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);document.getElementById('status').textContent='Проверка сохранена. Пришли JSON в чат.';}'''.replace('__DATA__',payload)
 page='<!doctype html><html lang="ru"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'; script-src \'unsafe-inline\'; connect-src \'none\'"><title>Сравнение сегментации и отслеживания</title><style>body{font:18px system-ui;max-width:1200px;margin:30px auto;padding:20px;background:#f5f7fb}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}article,section{padding:16px;background:white}section{margin:30px 0}.pair{border-top:1px solid #ddd;margin:15px 0}img{width:100%;max-height:650px;object-fit:contain}td,th{border:1px solid #ccd5df;padding:12px}table{border-collapse:collapse;width:100%}select,button{font:inherit;margin:15px;padding:12px}summary{cursor:pointer;padding:20px;background:#e9f1fc}</style><h1>Покадровые маски и отслеживание</h1><p>Слева — покадровый режим; справа — видеоотслеживание с одной опорной маской. Модель, исходная рамка, опорный момент и крупный участок одинаковые. Отслеживание ограничено этим участком и выполнено офлайн, в том числе назад по времени. Это не потоковый режим и не слежение по всему изображению.</p><p>Число масок ниже — техническая доступность результата, а не точность. Ранее подтверждены только выбранные кадры покадрового режима. Правильность нового отслеживания проверяется отдельно; рабочий режим не заменён.</p><table><tr><th>Ролик</th><th>Покадрово: маски / кадры, время</th><th>Отслеживание: маски / кадры, время</th></tr>'+''.join(table)+'</table>'+''.join(sections)+'<button onclick="saveReview()">Сохранить проверку отслеживания</button><p id="status" role="status"></p><script>'+script+'</script></html>'
 (out/'report.html').write_text(page,encoding='utf-8');write_json(out/'comparison.local.json',{'schema_version':1,'cases':cases,'approved_for_rule_engine':False,'tracking_default_enabled':False})
 print('TRACKING_COMPARISON_READY:',out/'report.html');print(json.dumps({'cases':len(cases),'selected_pairs':sum(len(c['selected_evidence_times_sec']) for c in cases),'accuracy_measured':False}))

if __name__=='__main__':main()
