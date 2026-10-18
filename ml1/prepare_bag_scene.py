"""Prepare a human-reviewed target bag region and cashier role, no violation labels."""
import argparse,base64,copy,hashlib,json,re,statistics
from pathlib import Path
from run_ollama_trial import ROOT,write_json

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--session',type=Path,required=True);p.add_argument('--probe',type=Path,required=True);args=p.parse_args();source=args.session.resolve();probe=args.probe.resolve()
 if not source.is_relative_to((ROOT/'local').resolve()) or not probe.is_relative_to((ROOT/'local').resolve()):p.error('Local inputs required')
 session=json.loads((source/'session.local.json').read_text());data=json.loads((probe/'proposals.local.json').read_text())
 if data['summary']['video_sha256']!=session['source_video_sha256']:p.error('Probe belongs to another video')
 best=[max(f['proposals'],key=lambda d:d['confidence']) for f in data['frames'] if f['proposals']]
 if not best:p.error('No bag proposals; manual object review needed')
 bbox=[statistics.median(d['bbox'][i] for d in best) for i in range(4)]
 initial=[p for f in session['frames'] if f['timestamp_sec']<=2 for p in f['persons'] if p['id']==1 and not p.get('is_reflection')]
 if not initial:p.error('No initial cashier proposal')
 centers=[[(p['bbox'][0]+p['bbox'][2])/2,(p['bbox'][1]+p['bbox'][3])/2] for p in initial]
 cx,cy=[statistics.median(c[i] for c in centers) for i in range(2)]
 cashier=[max(0,cx-.07),max(0,cy-.07),min(1,cx+.07),min(1,cy+.07)]
 draft={'schema_version':1,'profile_kind':'bag_scene','target_object_kind':'bag','object_type_human_confirmed':False,
        'source_session':session['session_id'],'source_video_sha256':session['source_video_sha256'],'confirmed':False,'confirmed_at':None,
        'zones':{'cashier_zone':cashier,'bag_zone':bbox},'roles':{'cashier_ids':[1],'client_ids':[]},'stability_sec':1,'max_gap_sec':1,
        'proposal_source':'weak_COCO_bag_boxes_and_initial_track_centers; needs_human_review'}
 write_json(source/'bag-calibration-proposal.local.json',draft)
 payload=dict(session,initial_profile=draft,initial_roles=draft['roles'],profile_kind='bag_scene',target_object_kind='bag',
              restore_revision='bag-scene-v1',required_zones=['cashier_zone','bag_zone'],initial_zone='bag_zone',export_suffix='-bag-calibration.json',
              frames=[dict(f,image='data:image/jpeg;base64,'+base64.b64encode((source/f['file']).read_bytes()).decode()) for f in session['frames']])
 text=(ROOT/'scene_mvp/calibration.html').read_text().replace('__PAYLOAD__',json.dumps(payload,ensure_ascii=False).replace('<','\\u003c'))
 text=text.replace('<h1>Калибровка сцены: зоны и роли</h1>','<h1>X-15: кассир и оставленная сумка — проверка входных данных</h1>')
 a=text.index('<aside>');b=text.index('</aside>',a)+8
 text=text[:a]+'<aside><b>Две области:</b> синяя — рабочее положение центра рамки кассира; зелёная — именно нужная сумка, плотно по её границам. Предложения детектора слабые: исправь их, если выбрана другая вещь. Проверь ID кассира на нескольких кадрах; если ID меняется, перечисли все подтверждённые номера. Уход и нарушение здесь не размечаются.</aside>'+text[b:]
 a=text.index('<p><b>1.</b>');b=text.index('</p>',a)+4
 text=text[:a]+'<p><b>1.</b> Проверь/обведи сумку. <b>2.</b> Проверь рабочую зону и ID кассира. <b>3.</b> Подтверди и экспортируй JSON. Дверь и состояния шкафа не нужны.</p>'+text[b:]
 text=re.sub(r'<select id="zone">.*?</select>','<select id="zone"><option value="bag_zone">Сумка — плотно по границам предмета</option><option value="cashier_zone">Рабочая зона центра рамки кассира</option><option value="ignore_zone">Исключить отражение</option></select>',text,count=1,flags=re.S)
 text=text.replace('Проверил зоны на нескольких кадрах и номера ролей. Подтверждаю только калибровку, не нарушения.','Проверил зоны, ID кассира и подтвердил, что в зелёной рамке находится нужная сумка. Это не подтверждение нарушения.')
 text=text.replace("if(payload.initial_zone)$('zone').value=payload.initial_zone;show(0);", "if(payload.initial_zone)$('zone').value=payload.initial_zone;$('door').closest('label').style.display='none';$('rangeControls').style.display='none';$('clients').closest('label').style.display='none';show(frames.findIndex(f=>f.timestamp_sec>=15));")
 (source/'bag-calibrate.html').write_text(text,encoding='utf-8');print('BAG_CALIBRATION_READY:',source/'bag-calibrate.html');print(json.dumps({'frames':len(session['frames']),'confirmed':False,'object_proposals_require_review':True,'violation_labels_used':False}))

if __name__=='__main__':main()
