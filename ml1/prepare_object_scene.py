"""One human target box and reviewed cashier role; no action labels or cloud calls."""
import argparse,base64,json,re,statistics
from pathlib import Path
from run_ollama_trial import ROOT,write_json
from scene_mvp.engine import validate_profile

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--session',type=Path,required=True);p.add_argument('--kind',choices=['bag','cash','documents'],required=True);p.add_argument('--reference-calibration',type=Path)
 args=p.parse_args();source=args.session.resolve()
 if not source.is_relative_to((ROOT/'local').resolve()):p.error('Local session required')
 session=json.loads((source/'session.local.json').read_text());frames=session['frames']
 candidates={}
 for f in frames:
  if f['timestamp_sec']>2:continue
  for person in f['persons']:
   if person.get('is_reflection') or person.get('uncertain') or not person.get('observed'):continue
   candidates.setdefault(person['id'],[]).append(person['bbox'])
 # Nearest foreground person is only a geometry proposal, never a verified role.
 role=max(candidates,key=lambda k:statistics.median((b[1]+b[3])/2 for b in candidates[k])) if candidates else None
 zones={};roles={'cashier_ids':[] if role is None else [role],'client_ids':[]}
 if role is not None:
  cx,cy=[statistics.median((b[i]+b[i+2])/2 for b in candidates[role]) for i in (0,1)]
  zones['cashier_zone']=[max(0,cx-.07),max(0,cy-.07),min(1,cx+.07),min(1,cy+.07)]
 draft={'schema_version':1,'profile_kind':'object_scene','target_object_kind':args.kind,'object_type_human_confirmed':False,
        'source_session':session['session_id'],'source_video_sha256':session['source_video_sha256'],'confirmed':False,
        'zones':zones,'roles':roles,'stability_sec':1,'max_gap_sec':1,'object_anchor_sec':None,
        'proposal_source':'initial_foreground_track_geometry_requires_human_review'}
 if args.reference_calibration:
  ref=json.loads(args.reference_calibration.read_text());validate_profile(ref)
  if ref.get('profile_kind')!='object_scene' or ref.get('target_object_kind')!=args.kind or not ref['confirmed']:p.error('Confirmed same-kind reference required')
  draft['zones']['object_zone']=list(ref['zones']['object_zone'])
  draft['object_region_proposal_from_video_sha256']=ref['source_video_sha256']
  draft['proposal_source']+='; object_box_from_another_video_is_unconfirmed_geometry_only'
 write_json(source/'object-calibration-proposal.local.json',draft)
 encoded=[]
 for f in frames:
  path=(source/f['file']).resolve()
  if not path.is_relative_to(source):p.error('Frame outside local session')
  encoded.append(dict(f,image='data:image/jpeg;base64,'+base64.b64encode(path.read_bytes()).decode()))
 payload=dict(session,frames=encoded,initial_profile=draft,initial_roles=roles,profile_kind='object_scene',target_object_kind=args.kind,
              required_zones=['cashier_zone','object_zone'],require_object_anchor=True,allow_object_anchor_button=True,initial_zone='object_zone',restore_revision='object-scene-v2',export_suffix='-object-calibration.json')
 text=(ROOT/'scene_mvp/calibration.html').read_text().replace('__PAYLOAD__',json.dumps(payload,ensure_ascii=False).replace('<','\\u003c'))
 label={'bag':'Сумка','cash':'Деньги','documents':'Документ / журнал'}[args.kind]
 text=text.replace('<h1>Калибровка сцены: зоны и роли</h1>','<h1>'+session['source_name']+' · '+label+'</h1>')
 text=re.sub(r'<aside>.*?</aside>','<aside><b>Одна рамка предмета, а не разметка каждого кадра.</b> Найди момент, где нужный предмет отчётливо виден, и обведи его плотно. Для документов выбери один журнал или одну стопку, не весь стол. Затем проверь синюю зону центра рамки кассира и его ID на нескольких кадрах. Предложенный ID и синяя область ещё не подтверждены. Не включай отражение в роль кассира. Уход, нарушение и состояния двери здесь не размечаются.</aside>',text,count=1,flags=re.S)
 text=re.sub(r'<p><b>1.</b>.*?</p>','<p><b>1.</b> Зелёная рамка — предмет на кадре, где он виден. <b>2.</b> Синяя область — обычное рабочее положение центра рамки кассира. <b>3.</b> Проверь ID, поставь подтверждение внизу и сохрани JSON.</p>',text,count=1,flags=re.S)
 text=re.sub(r'<select id="zone">.*?</select>','<select id="zone"><option value="object_zone">'+label+' — плотно по границам</option><option value="cashier_zone">Рабочая зона центра рамки кассира</option><option value="ignore_zone">Исключить отражение</option></select>',text,count=1,flags=re.S)
 text=text.replace('Проверил зоны на нескольких кадрах и номера ролей. Подтверждаю только калибровку, не нарушения.','Проверил предмет, рабочую зону и ID кассира. Подтверждаю только входные данные, не нарушение.')
 if args.reference_calibration:text=text.replace('Найди момент, где нужный предмет отчётливо виден, и обведи его плотно.','Зелёная рамка перенесена из другого ролика только как предложение. Найди кадр, где нужный предмет отчётливо виден. Если рамка верна, нажми «Предмет в рамке на этом кадре»; иначе обведи предмет заново.')
 text=text.replace("show(0);", "$('door').closest('label').style.display='none';$('door').closest('label').nextElementSibling.style.display='none';$('rangeControls').style.display='none';$('clients').closest('label').style.display='none';show(0);")
 (source/'object-calibrate.html').write_text(text,encoding='utf-8')
 print('OBJECT_CALIBRATION_READY:',source/'object-calibrate.html')
 print(json.dumps({'frames':len(frames),'human_target_kind':args.kind,'confirmed':False,'action_labels_used':False}))

if __name__=='__main__':main()
