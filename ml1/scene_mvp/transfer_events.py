"""Conservative transfer hypotheses from object/hand proximity; missing is unknown."""
import math
from scene_mvp.engine import valid_box

TARGETS=('cash','cashier_hand','client_hand')
def require_two_party_context(context,session):
 if context is None:return
 if context.get('source_session')!=session['session_id'] or context.get('source_video_sha256')!=session['source_video_sha256']:raise ValueError('Scene context source mismatch')
 if context.get('client_present') is False:raise ValueError('Human confirmed no client: two-party prompted handover is not applicable; no automatic negative-test success is implied')

def validate(profile,session):
 if profile.get('schema_version')!=1 or profile.get('profile_kind')!='hand_transfer_scene' or profile.get('confirmed') is not True:raise ValueError('Confirmed hand transfer prompts required')
 if profile.get('source_session')!=session['session_id'] or profile.get('source_video_sha256')!=session['source_video_sha256']:raise ValueError('Video/session mismatch')
 if profile.get('transfer_direction_supplied') is not False:raise ValueError('Expected direction must not be supplied')
 roles=profile.get('roles',{});ids={p['id'] for f in session['frames'] for p in f['persons']}
 if any(len(roles.get(k,[]))!=1 or type(roles[k][0]) is not int or roles[k][0] not in ids for k in ('cashier_ids','client_ids')) or roles['cashier_ids']==roles['client_ids']:raise ValueError('Distinct reviewed roles required')
 if set(profile.get('targets',{}))!=set(TARGETS):raise ValueError('Exactly three visual targets required')
 corrections=profile.get('cash_corrections',[])
 if not isinstance(corrections,list) or len(corrections)>8:raise ValueError('Invalid cash corrections')
 for target in list(profile['targets'].values())+corrections:
  valid_box(target['bbox']);t=target['timestamp_sec']
  if type(t) not in (int,float) or not math.isfinite(t) or t<0 or not any(abs(f['timestamp_sec']-t)<.001 for f in session['frames']):raise ValueError('Anchor must match source frame')
  if target.get('source')!='human_box_on_visible_target':raise ValueError('Human visual prompt required')
  points=target.get('points',[])
  if not isinstance(points,list) or len(points)>64:raise ValueError('Invalid point prompts')
  for point in points:
   xy=point.get('xy');label=point.get('label')
   if not isinstance(xy,list) or len(xy)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in xy):raise ValueError('Invalid point coordinates')
   if type(label) is not int or label not in (0,1) or point.get('source')!='human_click_on_visible_target_or_distractor':raise ValueError('Invalid point source/label')
   if label==1 and not(target['bbox'][0]<=xy[0]<=target['bbox'][2] and target['bbox'][1]<=xy[1]<=target['bbox'][3]):raise ValueError('Positive point must be in target box')
 cash_times=[profile['targets']['cash']['timestamp_sec']]+[t['timestamp_sec'] for t in corrections]
 if len(set(cash_times))!=len(cash_times):raise ValueError('Cash correction frames must differ')

def infer(rows,stability=.5,max_gap=.75,max_transition=3.):
 # Exclusive proximity is evidence for a hypothesis, not proof of possession.
 runs=[];active=[];last_state=None
 for i,row in enumerate(rows):
  state=row['relation']
  if active and (state!=last_state or row['timestamp_sec']-rows[active[-1]]['timestamp_sec']>max_gap):runs.append(active);active=[]
  active.append(i);last_state=state
 if active:runs.append(active)
 stable=[r for r in runs if rows[r[0]]['relation'] in {'cashier_near','client_near'} and rows[r[-1]]['timestamp_sec']-rows[r[0]]['timestamp_sec']>=stability]
 events=[]
 for before,after in zip(stable,stable[1:]):
  first,last=rows[before[-1]],rows[after[0]]
  if first['relation']==last['relation'] or last['timestamp_sec']-first['timestamp_sec']>max_transition:continue
  between=rows[before[-1]:after[0]+1]
  if any(r['relation'] in {'unknown','ambiguous','neither_near'} for r in between):continue
  if any(between[k+1]['timestamp_sec']-between[k]['timestamp_sec']>max_gap for k in range(len(between)-1)):continue
  a,b=first['cash_center_px'],last['cash_center_px'];scale=max(1,(first['cash_diagonal_px']+last['cash_diagonal_px'])/2)
  movement=math.hypot(a[0]-b[0],a[1]-b[1])/scale
  if movement<.25:continue
  events.append({'type':'cash_transfer_proximity_candidate','direction':'cashier_to_client' if first['relation']=='cashier_near' else 'client_to_cashier',
                 'start_sec':first['timestamp_sec'],'end_sec':rows[after[-1]]['timestamp_sec'],'evidence_times_sec':[rows[before[0]]['timestamp_sec'],last['timestamp_sec'],rows[after[-1]]['timestamp_sec']],
                 'object_displacement_relative_to_size':movement,'status':'experimental_review_candidate','possession_established':False,'legal_violation_established':False,'approved_for_rule_engine':False})
 return events
