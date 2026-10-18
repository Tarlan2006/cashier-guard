"""Prepare door-only zone review from existing confirmed human profiles and frame labels."""
import argparse,base64,copy,hashlib,html,json
from pathlib import Path
from scene_mvp.engine import validate_profile
from run_ollama_trial import ROOT,write_json

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--profiles',type=Path,nargs='+',required=True);args=p.parse_args();links=[]
 for file in args.profiles:
  profile=json.loads(file.read_text());validate_profile(profile)
  if not profile['confirmed']:p.error('Confirmed base profile required')
  source=(ROOT/'local'/profile['source_session']).resolve()
  if not source.is_relative_to((ROOT/'local').resolve()):p.error('Invalid session')
  session=json.loads((source/'session.local.json').read_text())
  if profile['source_video_sha256']!=session['source_video_sha256']:p.error('Video mismatch')
  draft=copy.deepcopy(profile);draft['confirmed']=False;draft['confirmed_at']=None;draft['task']='door_zone_for_experimental_state_classifier';write_json(source/'door-zone-draft.local.json',draft)
  payload=dict(session,initial_profile=draft,initial_roles=draft['roles'],restore_revision='door-'+hashlib.sha256(file.read_bytes()).hexdigest()[:12],required_zones=['cashier_zone','service_zone','door_zone'],initial_zone='door_zone',export_suffix='-door-calibration.json',frames=[dict(f,image='data:image/jpeg;base64,'+base64.b64encode((source/f['file']).read_bytes()).decode()) for f in session['frames']])
  text=(ROOT/'scene_mvp/calibration.html').read_text().replace('__PAYLOAD__',json.dumps(payload,ensure_ascii=False).replace('<','\\u003c'))
  text=text.replace('<h1>Калибровка сцены: зоны и роли</h1>','<h1>Только зона двери: '+html.escape(session['source_name'])+'</h1>')
  a=text.index('<p><b>1.</b>');b=text.index('</p>',a)+4
  text=text[:a]+'<p><b>Осталось одно действие:</b> обведи видимую дверь, включая область, где располагается открытая створка. Проверь границы на кадрах с открытой и закрытой дверью. Остальные зоны, роли и все метки двери уже восстановлены. Внизу подтверди и сохрани JSON. Покадровую разметку повторять не нужно.</p>'+text[b:]
  page=source/'door-calibration.html';page.write_text(text,encoding='utf-8');links.append((session['source_name'],page,len(draft.get('door_frame_labels',[]))))
 out=ROOT/'local/door-calibration-index.html';out.write_text('<!doctype html><meta charset="utf-8"><style>body{font:19px system-ui;max-width:900px;margin:40px auto;padding:20px}li{margin:20px 0}</style><h1>Следующий этап: видимая область двери</h1><p>Роли и состояния двери сохранены. Для каждого видео выдели только дверь и экспортируй JSON. Модель состояния пока не обучена и не включена. Два коротких эпизода дают предварительную проверку, но не подтверждают обобщение.</p><ul>'+''.join('<li><a href="'+html.escape(str(page),quote=True)+'">'+html.escape(name)+'</a> — восстановлено '+str(n)+' меток двери.</li>' for name,page,n in links)+'</ul>',encoding='utf-8')
 print('DOOR_CALIBRATION_INDEX_READY:',out);print(json.dumps({'videos':len(links),'restored_door_labels':sum(n for _,_,n in links),'new_inference':False}))
if __name__=='__main__':main()
