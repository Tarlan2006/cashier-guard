"""Prepare three independent human visual prompts; no expected transfer direction."""
import argparse,base64,hashlib,json
from pathlib import Path
from run_ollama_trial import ROOT,write_json
from scene_mvp.engine import validate_profile

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--session',type=Path,required=True);p.add_argument('--roles-calibration',type=Path,required=True);args=p.parse_args()
 folder=args.session.resolve()
 if not folder.is_relative_to((ROOT/'local').resolve()):p.error('Local source session required')
 session=json.loads((folder/'session.local.json').read_text());profile=json.loads(args.roles_calibration.read_text());validate_profile(profile)
 if not profile['confirmed'] or profile['source_video_sha256']!=session['source_video_sha256'] or profile['source_session']!=session['session_id']:p.error('Confirmed same-session roles required')
 roles=profile['roles']
 if len(roles.get('cashier_ids',[]))!=1 or len(roles.get('client_ids',[]))!=1:p.error('One reviewed cashier and client required')
 if not set(roles['cashier_ids']+roles['client_ids'])<={person['id'] for f in session['frames'] for person in f['persons']}:p.error('Roles absent from tracks')
 frames=[]
 for f in session['frames']:
  path=(folder/f['file']).resolve()
  if not path.is_relative_to(folder):p.error('Frame outside source')
  frames.append(dict(f,image='data:image/jpeg;base64,'+base64.b64encode(path.read_bytes()).decode()))
 payload=dict(session,frames=frames,roles=roles,roles_source={'kind':'prior_human_same_video_same_session','calibration_sha256':hashlib.sha256(args.roles_calibration.read_bytes()).hexdigest()})
 template=(ROOT/'scene_mvp/transfer_calibration.html').read_text();(folder/'transfer-calibrate.html').write_text(template.replace('__PAYLOAD__',json.dumps(payload,ensure_ascii=False).replace('<','\\u003c')),encoding='utf-8')
 write_json(folder/'transfer-plan.local.json',{'schema_version':1,'source_session':session['session_id'],'source_video_sha256':session['source_video_sha256'],'roles':roles,'required_targets':['cash','cashier_hand','client_hand'],'seed_frames_can_differ':True,'transfer_direction_supplied':False,'violation_labels_used':False,'confirmed_targets':False})
 print('TRANSFER_CALIBRATION_READY:',folder/'transfer-calibrate.html');print(json.dumps({'frames':len(frames),'roles_reused_from_same_video':True,'target_boxes_prefilled':False,'expected_direction_used':False}))

if __name__=='__main__':main()
