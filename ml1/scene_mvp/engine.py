"""Conservative geometry and temporal events. Missing observations are unknown."""
import math

ZONES={'cashier_zone','service_zone','exit_zone','door_zone','desk_zone','safe_zone','ignore_zone','bag_zone','object_zone'}
SIGNALS={'workplace_departure','multiple_visitors_in_service_zone','door_open_while_cashier_away'}
def valid_box(box):
 if not isinstance(box,list) or len(box)!=4 or any(type(x) not in (int,float) or not math.isfinite(x) for x in box):raise ValueError('Invalid box')
 if not 0<=box[0]<box[2]<=1 or not 0<=box[1]<box[3]<=1:raise ValueError('Normalized nonempty box required')
 return box

def validate_profile(profile):
 if profile.get('schema_version')!=1:raise ValueError('Unsupported profile')
 if not isinstance(profile.get('confirmed'),bool):raise ValueError('Confirmation flag required')
 sha=profile.get('source_video_sha256','')
 if len(sha)!=64 or any(x not in '0123456789abcdef' for x in sha):raise ValueError('Video SHA-256 required')
 zones=profile.get('zones',{})
 for name,box in zones.items():
  if name not in ZONES:raise ValueError('Unknown zone')
  if name=='ignore_zone':
   if not isinstance(box,list):raise ValueError('Ignore boxes required')
   for item in box:valid_box(item)
  else:valid_box(box)
 kind=profile.get('profile_kind','scene')
 if kind not in {'scene','door_only','fixture_only','bag_scene','object_scene'}:raise ValueError('Invalid profile kind')
 if kind=='fixture_only' and profile.get('fixture_kind')!='cash_storage_cabinet':raise ValueError('Invalid fixture kind')
 if kind=='bag_scene' and profile.get('target_object_kind')!='bag':raise ValueError('Bag target required')
 if kind=='object_scene' and profile.get('target_object_kind') not in {'bag','cash','documents'}:raise ValueError('Invalid object target')
 if kind in {'bag_scene','object_scene'} and profile['confirmed'] and profile.get('object_type_human_confirmed') is not True:raise ValueError('Human confirmation of target object required')
 if kind=='object_scene' and profile['confirmed']:
  anchor=profile.get('object_anchor_sec')
  if type(anchor) not in (int,float) or not math.isfinite(anchor) or anchor<0:raise ValueError('Visible object anchor time required')
  if not profile.get('roles',{}).get('cashier_ids'):raise ValueError('Human-reviewed cashier ID required')
 required=['cashier_zone','object_zone'] if kind=='object_scene' else ['cashier_zone','bag_zone'] if kind=='bag_scene' else ['safe_zone'] if kind=='fixture_only' else ['door_zone'] if kind=='door_only' else ['cashier_zone','service_zone']
 if profile['confirmed'] and not all(name in zones for name in required):raise ValueError('Required zones missing')
 roles=profile.get('roles',{})
 if any(k not in {'cashier_ids','client_ids'} or not isinstance(v,list) or any(type(i)!=int for i in v) for k,v in roles.items()):raise ValueError('Invalid role IDs')
 if set(roles.get('cashier_ids',[]))&set(roles.get('client_ids',[])):raise ValueError('Conflicting role IDs')
 margin=profile.get('zone_margin',.015)
 if type(margin) not in (int,float) or not math.isfinite(margin) or not 0<=margin<=.1:raise ValueError('Invalid zone margin')
 for name in ['stability_sec','max_gap_sec']:
  value=profile.get(name,1.0)
  if type(value) not in (int,float) or not math.isfinite(value) or value<=0:raise ValueError('Invalid time threshold')
 return profile

def center(box):return [(box[0]+box[2])/2,(box[1]+box[3])/2]
def contains(box,point):return box[0]<=point[0]<=box[2] and box[1]<=point[1]<=box[3]
def stable_contains(box,point,previous=None,margin=.015):
 if contains(box,point):return True
 outside=max(box[0]-point[0],point[0]-box[2],box[1]-point[1],point[1]-box[3],0)
 if outside>margin:return False
 return previous

def clean_person(p,zones,reviewed_ids=()):
 reviewed=p.get('id') in reviewed_ids and p.get('confidence',0)>=.5
 if p.get('observed',True) is False or p.get('is_reflection') or p.get('uncertain',False):return False
 if not p.get('track_confirmed',False) and not reviewed:return False
 if not p.get('counted',True) and not (reviewed and not p.get('track_confirmed',False)):return False
 try:c=center(valid_box(p['bbox']))
 except (ValueError,KeyError):return False
 return not any(contains(box,c) for box in zones.get('ignore_zone',[]))

def analyze(frames,profile,video_sha256,door_observations=None):
 validate_profile(profile)
 if profile.get('profile_kind','scene') not in {'scene','bag_scene','object_scene'}:raise ValueError('A fixture-only profile cannot run workplace rules')
 if profile['source_video_sha256']!=video_sha256:raise ValueError('Profile belongs to a different video; recalibrate or explicitly verify reuse')
 if not profile['confirmed']:
  return {'schema_version':1,'status':'needs_calibration','signals':[],'timeline':[],'coverage':{'calibration':False},'reasons':['camera_zones_not_human_confirmed'],'is_legal_verdict':False}
 zones=profile['zones'];roles=profile.get('roles',{});cashiers=set(roles.get('cashier_ids',[]));clients=set(roles.get('client_ids',[]));history={};timeline=[]
 stability=profile.get('stability_sec',1.0);gap=profile.get('max_gap_sec',1.0);margin=profile.get('zone_margin',.015)
 ordered=sorted(frames,key=lambda f:f.get('actual_timestamp_sec',f['timestamp_sec']))
 seen_times=set();role_candidates={};known_cashier_zones={};role_started={};departed=set();last_time=None
 for frame in ordered:
  t=frame.get('actual_timestamp_sec',frame['timestamp_sec'])
  if not isinstance(t,(int,float)) or not math.isfinite(t) or t<0 or t in seen_times:raise ValueError('Invalid or duplicate frame time')
  seen_times.add(t)
  if last_time is not None and t-last_time>gap:known_cashier_zones.clear();role_started.clear();departed.clear()
  last_time=t;people=[p for p in frame.get('persons',[]) if clean_person(p,zones,cashiers|clients)];observations=[];visible_cashiers=[];visitors=[];transition=False
  unique=[]
  for person in sorted(people,key=lambda p:p.get('confidence',0),reverse=True):
   a=person['bbox']
   def duplicate(other):
    b=other['bbox'];intersection=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]));union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection
    return intersection/union>.7
   if not any(duplicate(other) for other in unique):unique.append(person)
  people=unique
  for p in people:
   identifier=p['id'];c=center(p['bbox']);in_cashier=contains(zones['cashier_zone'],c);in_service=contains(zones['service_zone'],c) if 'service_zone' in zones else False
   if identifier in cashiers:role='cashier';source='user_confirmed_track'
   elif identifier in clients:role='client';source='user_confirmed_track'
   elif identifier in role_candidates:role=role_candidates[identifier];source='stable_zone_candidate'
   elif in_cashier!=in_service and (in_cashier or in_service):
    candidate='cashier_candidate' if in_cashier else 'client_candidate';prior=role_started.get(identifier)
    if prior is None or prior[0]!=candidate or t-prior[2]>gap:role_started[identifier]=(candidate,t,t)
    else:role_started[identifier]=(candidate,prior[1],t)
    if t-role_started[identifier][1]>=stability:role_candidates[identifier]=candidate
    role=role_candidates.get(identifier,'unknown');source='stable_zone_candidate'
   else:
    role='unknown';source='unknown';role_started.pop(identifier,None)
   if role in {'cashier','cashier_candidate'}:
    old=known_cashier_zones.get(identifier)
    previous=old[0] if old and t-old[1]<=gap else None
    in_cashier=stable_contains(zones['cashier_zone'],c,previous,margin)
    visible_cashiers.append((identifier,in_cashier))
    if old and t-old[1]>gap:departed.discard(identifier)
    if in_cashier:departed.discard(identifier)
    if old and old[0] is True and in_cashier is False and t-old[1]<=gap:
     transition=True;departed.add(identifier)
    known_cashier_zones[identifier]=(in_cashier,t)
   if role in {'client','client_candidate'} and in_service:visitors.append(identifier)
   observations.append({'id':identifier,'role':role,'role_source':source,'center':c,'bbox':p['bbox'],'in_cashier_zone':in_cashier,'in_service_zone':in_service,'track_confirmation_source':'human_reviewed_video_track' if identifier in cashiers|clients and not p.get('track_confirmed',False) else 'automatic_tracker','in_exit_zone':contains(zones['exit_zone'],c) if 'exit_zone' in zones else None})
  # No detection is never interpreted as evidence of absence.
  presence=('present' if any(inside for _,inside in visible_cashiers) else 'away_observed' if any(inside is False for _,inside in visible_cashiers) else 'unknown')
  door=(door_observations or {}).get(round(t,3),{'state':'unknown','source':'not_observed'})
  if door.get('state') not in {'open','closed','unknown'}:raise ValueError('Invalid door state')
  if door.get('state')!='unknown' and door.get('source')!='human_frame_label':raise ValueError('Unvalidated door inference is not accepted')
  timeline.append({'timestamp_sec':t,'cashier_presence':presence,'cashier_departure_transition':transition,'departure_supported':any(identifier in departed and not inside for identifier,inside in visible_cashiers),'cashier_ids':[i for i,_ in visible_cashiers],'visitor_ids':sorted(set(visitors)),'visitor_count':len(set(visitors)) if people else None,'door':door,'persons':observations,'frame_file':frame.get('file')})
 signals=[]
 def intervals(kind,predicate):
  start=None;last=None;indices=[]
  def finish():
   if start is not None and last-start>=stability:
    signals.append({'type':kind,'start_sec':start,'end_sec':last,'evidence_times_sec':list(dict.fromkeys([timeline[max(0,indices[0]-1)]['timestamp_sec'],timeline[indices[0]]['timestamp_sec'],timeline[indices[-1]]['timestamp_sec']])),'participant_ids':sorted({actor for i in indices for actor in timeline[i]['visitor_ids' if kind=='multiple_visitors_in_service_zone' else 'cashier_ids']}),'status':'review_candidate','rule_id':None,'legal_violation_established':False})
  for i,row in enumerate(timeline):
   t=row['timestamp_sec'];okay=predicate(row)
   if last is not None and t-last>gap:finish();start=None;indices=[]
   if okay:
    if start is None:start=t
    indices.append(i);last=t
   else:finish();start=None;last=None;indices=[]
  finish()
 intervals('workplace_departure',lambda r:r['cashier_presence']=='away_observed' and r['departure_supported'])
 intervals('multiple_visitors_in_service_zone',lambda r:r['visitor_count'] is not None and r['visitor_count']>=2)
 intervals('door_open_while_cashier_away',lambda r:r['cashier_presence']=='away_observed' and r['departure_supported'] and r['door']['state']=='open')
 explanations={'workplace_departure':'Трек, связанный с кассиром, наблюдался вне рабочей зоны. Это не доказывает выход из помещения или нарушение.', 'multiple_visitors_in_service_zone':'В зоне обслуживания одновременно наблюдались не менее двух кандидатов в клиенты. Начало обслуживания второго клиента не установлено.', 'door_open_while_cashier_away':'На размеченных кадрах дверь открыта, а кассир наблюдается вне рабочей зоны. Требуется проверка регламента и эпизода.'}
 for signal in signals:signal['explanation']=explanations[signal['type']]
 known=sum(r['cashier_presence']!='unknown' for r in timeline);door_known=sum(r['door']['state']!='unknown' for r in timeline)
 return {'schema_version':1,'status':'partial','signals':signals,'timeline':timeline,'coverage':{'calibration':True,'cashier_observed_frames':known,'door_labeled_frames':door_known,'total_frames':len(timeline),'cash_object_recognition':False,'hand_transfer_recognition':False,'screen_lock_recognition':False,'zone_margin':margin,'manually_confirmed_initial_track_frames':sum(p['track_confirmation_source']=='human_reviewed_video_track' for row in timeline for p in row['persons'])},'reasons':['absence_not_inferred_from_missing_detection','door_state_requires_frame_labels','money_and_screen_state_not_enabled','not_a_legal_verdict'],'is_legal_verdict':False}
