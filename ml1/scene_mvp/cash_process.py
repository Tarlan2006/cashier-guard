"""Cash-process calibration and geometry candidates, without invented semantics."""
import math
from scene_mvp.engine import valid_box

SPEC={'version':'cash-process-zones/1','minimum_mask_fraction':.0002,'zone_mask_overlap':.25,
      'minimum_dwell_sec':1.,'maximum_sample_gap_sec':.75,'cash_type_source':'human_seed',
      'zone_overlap_establishes_machine_use':False,'zone_overlap_establishes_storage':False,
      'lost_mask_establishes_storage':False,'cabinet_state_model_enabled':False}


def validate_case(case,protocol):
    if case.get('confirmed') is not True:raise ValueError('Confirmed case required')
    for key in ['source_session','source_video_sha256']:
        if case.get(key)!=protocol[key]:raise ValueError('Source binding mismatch')
    for name in ['machine_zone','safe_zone','cash_seed']:valid_box(case.get('zones',{}).get(name))
    t=case.get('cash_anchor_sec')
    if type(t) not in (int,float) or not math.isfinite(t) or not any(abs(t-x)<.001 for x in protocol['sample_times_sec']):raise ValueError('Cash seed must bind to a sampled frame')
    if case.get('human_cash_type_confirmed') is not True:raise ValueError('Human cash seed confirmation required')
    if case.get('same_cash_batch') not in ['yes','no','unclear']:raise ValueError('Cash batch binding required')
    for field in ['counter_use_observation','cash_storage_observation','storage_closure_observation']:
        if case.get(field,'unknown') not in ['observed','not_observed','unclear','unknown']:raise ValueError('Unknown process observation')
    if case.get('process_coverage','unknown') not in ['complete','incomplete','unclear','unknown']:raise ValueError('Unknown coverage')
    span=case.get('counter_use_window_sec')
    if case.get('counter_use_observation')=='observed':
        if not isinstance(span,list) or len(span)!=2 or any(type(x) not in (int,float) or not math.isfinite(x) for x in span) or not 0<=span[0]<span[1]<=protocol['duration_sec']:raise ValueError('Counter window required')
    elif span is not None:raise ValueError('Counter interval without observation')
    for field,observation in [('cash_storage_time_sec','cash_storage_observation'),('storage_closure_time_sec','storage_closure_observation')]:
        time=case.get(field)
        if case.get(observation)=='observed' and (type(time) not in (int,float) or not math.isfinite(time) or not 0<=time<protocol['duration_sec']):raise ValueError('Observed storage/closure time required')
        if case.get(observation)!='observed' and time is not None:raise ValueError('Time without storage observation')
    if case.get('same_cash_batch')=='yes':
        stored=case.get('cash_storage_time_sec');closed=case.get('storage_closure_time_sec')
        if span and stored is not None and stored<span[1]:raise ValueError('Marked storage-after-count precedes counter end; review cash-batch binding')
        if stored is not None and closed is not None and closed<stored:raise ValueError('Closure precedes storage')
    return case


def candidates(timeline,spec=SPEC):
    result=[]
    for zone in ['machine','safe']:
        active=[];last=None
        def finish():
            if active and active[-1]-active[0]>=spec['minimum_dwell_sec']:
                result.append({'type':'cash_mask_overlaps_'+zone+'_zone','start_sec':active[0],'end_sec':active[-1],
                    'evidence_times_sec':list(dict.fromkeys([active[0],active[len(active)//2],active[-1]])),
                    'status':'geometry_review_candidate','cash_counter_use_established':False,
                    'cash_storage_established':False,'legal_violation_established':False})
        for row in timeline:
            t=row['timestamp_sec']
            if type(t) not in (int,float) or not math.isfinite(t) or t<0 or last is not None and t<=last:raise ValueError('Ordered finite times required')
            if active and t-last>spec['maximum_sample_gap_sec']:finish();active=[]
            okay=row['state']=='mask_observed' and row.get(zone+'_overlap_fraction',0)>=spec['zone_mask_overlap']
            if okay:active.append(t)
            else:finish();active=[]
            last=t
        finish()
    return sorted(result,key=lambda r:(r['start_sec'],r['type']))


def human_sequence(case):
    """Evaluate human time labels for the retained-cash tail, not the whole bag procedure."""
    same=case.get('same_cash_batch')=='yes';complete=case.get('process_coverage')=='complete'
    counter=case.get('counter_use_observation','unknown');stored=case.get('cash_storage_observation','unknown');closed=case.get('storage_closure_observation','unknown')
    result={'counter_state':'not_annotated','storage_state':'not_annotated','storage_closure_state':'not_annotated',
        'visible_sequence_state':'incomplete_evidence','storage_lock_status':'not_established','review_candidates':[],
        'evidence_basis':'human_visual_review','full_collection_operation_validated':False,
        'banknote_count_accuracy_established':False,'legal_violation_label':None,'approved_for_rule_engine':False}
    if counter=='observed':result['counter_state']='cash_counter_use_seen' if same else 'same_client_operation_not_bound'
    elif counter=='not_observed':result['counter_state']='cash_counter_use_not_observed'
    elif counter=='unclear':result['counter_state']='unknown'
    if stored=='observed':
        if not same:result['storage_state']='same_client_operation_not_bound'
        elif counter=='observed' and case['cash_storage_time_sec']>=case['counter_use_window_sec'][1]:result['storage_state']='cash_stored_after_count_seen'
        else:result['storage_state']='placement_seen_count_order_not_established'
    elif stored=='not_observed':result['storage_state']='cash_storage_not_observed'
    elif stored=='unclear':result['storage_state']='unknown'
    if closed=='observed':
        result['storage_closure_state']='storage_closed_after_placement_seen' if same and stored=='observed' and case['storage_closure_time_sec']>=case['cash_storage_time_sec'] else 'closure_seen_placement_order_not_established'
    elif closed=='not_observed':result['storage_closure_state']='storage_closure_not_observed'
    elif closed=='unclear':result['storage_closure_state']='unknown'
    if same and complete:
        for field,observation in [('cash_counter_use',counter),('cash_storage_placement',stored),('cash_storage_closure',closed)]:
            if observation=='not_observed':result['review_candidates'].append({'code':field+'_not_observed','requires_human_review':True,'legal_violation_established':False})
    if result['review_candidates']:result['visible_sequence_state']='visual_procedure_review_candidate'
    elif result['counter_state']=='cash_counter_use_seen' and result['storage_state']=='cash_stored_after_count_seen' and result['storage_closure_state']=='storage_closed_after_placement_seen':result['visible_sequence_state']='count_storage_tail_supported_by_human_review'
    return result
