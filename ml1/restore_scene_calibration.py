"""Restore a user draft and propose zones from role-track centers, without confirming them."""
import argparse,base64,copy,hashlib,json,shutil,statistics
from pathlib import Path
from scene_mvp.engine import validate_profile
from run_ollama_trial import ROOT,write_json

def proposal(people):
 centers=[((p['bbox'][0]+p['bbox'][2])/2,(p['bbox'][1]+p['bbox'][3])/2) for p in people]
 xs=sorted(c[0] for c in centers);ys=sorted(c[1] for c in centers)
 padx=max(.04,statistics.median(p['bbox'][2]-p['bbox'][0] for p in people)*.45);pady=max(.04,statistics.median(p['bbox'][3]-p['bbox'][1] for p in people)*.45)
 q1=round((len(xs)-1)*.1);q9=round((len(xs)-1)*.9)
 return [max(0,xs[q1]-padx),max(0,ys[q1]-pady),min(1,xs[q9]+padx),min(1,ys[q9]+pady)]
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--session',type=Path,required=True);p.add_argument('--draft',type=Path,required=True);args=p.parse_args();source=args.session.resolve()
 if not source.is_relative_to((ROOT/'local').resolve()):p.error('Local session required')
 session=json.loads((source/'session.local.json').read_text());draft=json.loads(args.draft.read_text());validate_profile(draft)
 if draft.get('source_session')!=session['session_id'] or draft['source_video_sha256']!=session['source_video_sha256']:p.error('Draft does not belong to this session')
 times={round(f['timestamp_sec'],3) for f in session['frames']};labels=draft.get('door_frame_labels',[])
 if len({round(x['timestamp_sec'],3) for x in labels})!=len(labels) or any(round(x['timestamp_sec'],3) not in times or x['state'] not in ['open','closed','unknown'] or x['source']!='human_frame_label' for x in labels):p.error('Invalid door labels')
 shutil.copy2(args.draft,source/('imported-draft-'+hashlib.sha256(args.draft.read_bytes()).hexdigest()[:12]+'.local.json'))
 restored=copy.deepcopy(draft);restored['confirmed']=False;restored['confirmed_at']=None;proposed=[]
 for role,zone in [('cashier_ids','cashier_zone'),('client_ids','service_zone')]:
  if zone in restored['zones']:continue
  ids=restored['roles'].get(role,[]);people=[p for f in session['frames'] for p in f['persons'] if p['id'] in ids and p.get('track_confirmed') and not p.get('is_reflection')]
  if people:restored['zones'][zone]=proposal(people);proposed.append(zone)
 restored['zone_proposals']={'source':'centers_and_median_body_size_of_user_confirmed_role_tracks','zones':proposed,'human_confirmed':False}
 validate_profile(restored);write_json(source/'restored-profile.local.json',restored)
 payload=dict(session,initial_roles=restored['roles'],restore_revision=hashlib.sha256(args.draft.read_bytes()).hexdigest()[:12],initial_profile=restored,frames=[dict(f,image='data:image/jpeg;base64,'+base64.b64encode((source/f['file']).read_bytes()).decode()) for f in session['frames']])
 text=(ROOT/'scene_mvp/calibration.html').read_text().replace('__PAYLOAD__',json.dumps(payload,ensure_ascii=False).replace('<','\\u003c'));(source/'calibrate.html').write_text(text,encoding='utf-8')
 print(json.dumps({'restored_door_labels':len(labels),'proposed_zones':proposed,'confirmed':restored['confirmed'],'original_export_preserved':True}))
 print('RESTORED_CALIBRATION_READY:',source/'calibrate.html')
if __name__=='__main__':main()
