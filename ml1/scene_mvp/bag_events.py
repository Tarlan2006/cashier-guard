"""Combine tracked user-selected object with observed departure, never inferred absence."""
from scene_mvp.engine import center

def iou(a,b):
    inter=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    area=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter
    return inter/area if area>0 else 0.

def attach_review(result,observations,profile):
    kind=profile.get('target_object_kind')
    if not profile.get('object_type_human_confirmed') or kind not in {'bag','cash','documents'}:raise ValueError('Confirmed object reference required')
    region=profile['zones']['object_zone' if profile.get('profile_kind')=='object_scene' else 'bag_zone'];gap=profile.get('max_gap_sec',1);runs=[];active=[];previous=None
    for i,row in enumerate(result['timeline']):
        t=row['timestamp_sec'];bag=dict(observations.get(round(t,3),{'state':'unknown','bbox':None}))
        stationary=False
        if bag['state']=='mask_observed' and bag.get('bbox') is not None:
            c=center(bag['bbox'])
            if previous and t-previous[0]<=gap:
                stationary=max(abs(c[k]-previous[1][k]) for k in (0,1))<=.025
            previous=(t,c)
            bag['near_reference_region']=iou(bag['bbox'],region)>=.1
        else:
            previous=None;bag['near_reference_region']=False
        bag['stationary_between_samples']=stationary;bag['human_target_kind']=kind;row['experimental_object']=bag
        if kind=='bag':row['experimental_bag']=bag
        okay=bag['state']=='mask_observed' and bag['near_reference_region'] and stationary and row['cashier_presence']=='away_observed' and row['departure_supported']
        if active and (not okay or t-result['timeline'][active[-1]]['timestamp_sec']>gap):runs.append(active);active=[]
        if okay:active.append(i)
    if active:runs.append(active)
    candidates=[]
    for run in runs:
        first,last=(result['timeline'][run[k]] for k in (0,-1))
        if last['timestamp_sec']-first['timestamp_sec']<profile.get('stability_sec',1):continue
        candidates.append({'type':kind+'_observed_during_cashier_departure','human_target_kind':kind,'start_sec':first['timestamp_sec'],'end_sec':last['timestamp_sec'],
            'evidence_times_sec':list(dict.fromkeys([result['timeline'][max(0,run[0]-1)]['timestamp_sec'],first['timestamp_sec'],last['timestamp_sec']])),
            'participant_ids':sorted({p for i in run for p in result['timeline'][i]['cashier_ids']}),
            'status':'experimental_review_candidate','source':'edgetam_framewise_human_region_segmentation','rule_id':None,
            'legal_violation_established':False,'approved_for_rule_engine':False,
            'explanation':'Маска находится рядом с подтверждённой областью предмета, а кассир наблюдается вне рабочей зоны после отхода. Тип предмета задан человеком; правильность маски и контекст требуют просмотра.'})
    result.setdefault('experimental_signals',[]).extend(candidates)
    return result
