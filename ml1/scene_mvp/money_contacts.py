"""Exploratory ordered hand/cash proximity; gaps never establish object continuity."""
import math

PROTOCOL={'version':'money-contact-context/1','near_relative_to_cash_size':.2,'far_relative_to_cash_size':.5,
          'max_transition_sec':3.,'max_sample_gap_sec':.75,'maximum_missing_cash_samples':1,
          'minimum_after_support_sec':.5,'minimum_mask_pixels':16,'minimum_area_relative_to_seed':.1,
          'maximum_area_relative_to_seed':8.,'maximum_mask_iou':.65,'expected_direction_used':False,
          'direction_established':False,'legal_verdict':False,'approved_for_rule_engine':False}

def candidates(rows,protocol=PROTOCOL):
    events=[];seen=set();roles=('cashier','client')
    for i,start in enumerate(rows):
        near=[role for role in roles if start['hand_proximity'][role]=='near']
        if not start['cash_observed'] or len(near)!=1:continue
        sender=near[0];receiver=roles[1] if sender==roles[0] else roles[0]
        # Require known separation at the first endpoint. Later missing hands remain unknown.
        if start['hand_proximity'][receiver]!='far':continue
        for j in range(i+1,len(rows)):
            end=rows[j]
            if end['timestamp_sec']-start['timestamp_sec']>protocol['max_transition_sec']:break
            if not end['cash_observed'] or end['hand_proximity'][receiver]!='near':continue
            segment=rows[i:j+1]
            if any(b['timestamp_sec']-a['timestamp_sec']>protocol['max_sample_gap_sec'] for a,b in zip(segment,segment[1:])):break
            missing=[r['timestamp_sec'] for r in segment if not r['cash_observed']]
            if len(missing)>protocol['maximum_missing_cash_samples']:break
            if any(r.get('identity_collision') for r in segment):break
            support=[j];n=j+1
            while n<len(rows) and rows[n]['timestamp_sec']-rows[n-1]['timestamp_sec']<=protocol['max_sample_gap_sec'] and rows[n]['cash_observed'] and rows[n]['hand_proximity'][receiver]=='near' and not rows[n].get('identity_collision'):
                support.append(n);n+=1
            if rows[support[-1]]['timestamp_sec']-end['timestamp_sec']<protocol['minimum_after_support_sec']:continue
            direction=sender+'_to_'+receiver;key=(direction,end['timestamp_sec'])
            if key in seen:break
            seen.add(key)
            events.append({'type':'ordered_hand_cash_proximity_context_candidate','direction':direction,
                           'start_sec':start['timestamp_sec'],'end_sec':rows[support[-1]]['timestamp_sec'],
                           'before_contact_sec':start['timestamp_sec'],'after_contact_sec':end['timestamp_sec'],
                           'uncertain_times_sec':[r['timestamp_sec'] for r in segment if not r['cash_observed'] or 'unknown' in r['hand_proximity'].values()],
                           'missing_cash_times_sec':missing,'cash_mask_coverage_continuous':not missing,'cash_identity_continuity_established':False,
                           'continuity_status':'tracked_masks_only_not_identity_proof' if not missing else 'not_established_due_to_lost_cash_mask',
                           'other_hand_observed_at_end':end['hand_proximity'][sender]!='unknown',
                           'direction_established':False,'possession_established':False,'human_review_required':True,
                           'status':'exploratory_context_only','missing_samples_interpolated':False,'legal_violation_established':False,'approved_for_rule_engine':False})
            break
    return events
