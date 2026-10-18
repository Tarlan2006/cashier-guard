"""Partial body-box approach to a reviewed service region; not service recognition."""
SPEC={'version':1,'minimum_person_box_overlap':.1,'source':'experimental_service_region_overlap'}

def overlap(box,zone):
    area=(box[2]-box[0])*(box[3]-box[1])
    intersection=max(0,min(box[2],zone[2])-max(box[0],zone[0]))*max(0,min(box[3],zone[3])-max(box[1],zone[1]))
    return intersection/area if area>0 else 0.

def attach_review(result,profile):
    if result['status']!='partial' or not profile['confirmed']:raise ValueError('Confirmed scene required')
    zone=profile['zones']['service_zone'];runs=[];active=[]
    for i,row in enumerate(result['timeline']):
        people=[p for p in row['persons'] if p['role'] in ('client','client_candidate')]
        inside={p['id'] for p in people if p['in_service_zone']}
        nearby={p['id'] for p in people if not p['in_service_zone'] and overlap(p['bbox'],zone)>=SPEC['minimum_person_box_overlap']}
        nearby-=inside
        row['experimental_visitor_approach']={'source':SPEC['source'],'inside_ids':sorted(inside),'nearby_ids':sorted(nearby),
            'overlap_ratios':{str(p['id']):overlap(p['bbox'],zone) for p in people},'service_started_established':False}
        okay=bool(inside and nearby and row['cashier_presence']=='present')
        if active and (not okay or row['timestamp_sec']-result['timeline'][active[-1]]['timestamp_sec']>profile.get('max_gap_sec',1)):
            runs.append(active);active=[]
        if okay:active.append(i)
    if active:runs.append(active)
    signals=[]
    for run in runs:
        first,last=(result['timeline'][run[k]] for k in (0,-1))
        if last['timestamp_sec']-first['timestamp_sec']<profile.get('stability_sec',1):continue
        signals.append({'type':'additional_visitor_near_service_zone','start_sec':first['timestamp_sec'],'end_sec':last['timestamp_sec'],
            'evidence_times_sec':list(dict.fromkeys([result['timeline'][max(0,run[0]-1)]['timestamp_sec'],first['timestamp_sec'],last['timestamp_sec']])),
            'participant_ids':sorted({identifier for i in run for key in ('inside_ids','nearby_ids') for identifier in result['timeline'][i]['experimental_visitor_approach'][key]}),
            'status':'experimental_review_candidate','source':SPEC['source'],'rule_id':None,'legal_violation_established':False,
            'service_started_established':False,'approved_for_rule_engine':False,
            'explanation':'Один посетитель находится в зоне обслуживания, рамка другого частично пересекает эту зону, кассир наблюдается на рабочем месте. Начало обслуживания и передача предмета не установлены.'})
    result.setdefault('experimental_signals',[]).extend(signals)
    result['experimental_visitor_protocol']=dict(SPEC,stability_sec=profile.get('stability_sec',1),max_gap_sec=profile.get('max_gap_sec',1),validation_status='development_only_requires_independent_negative_clip')
    return result
