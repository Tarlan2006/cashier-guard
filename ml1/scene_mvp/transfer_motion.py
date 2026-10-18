"""Experimental offline handover candidates; uncertainty is retained, never filled."""
import math

def infer_motion(rows,protocol):
    runs=[];active=[]
    for i,row in enumerate(rows):
        if active and (row['relation']!=rows[active[-1]]['relation'] or row['timestamp_sec']-rows[active[-1]]['timestamp_sec']>protocol['max_sample_gap_sec']):runs.append(active);active=[]
        active.append(i)
    if active:runs.append(active)
    stable=[r for r in runs if rows[r[0]]['relation'] in ('cashier_near','client_near') and rows[r[-1]]['timestamp_sec']-rows[r[0]]['timestamp_sec']>=protocol['stable_exclusive_sec']]
    events=[]
    for before,after in zip(stable,stable[1:]):
        a,b=rows[before[-1]],rows[after[0]]
        if a['relation']==b['relation'] or b['timestamp_sec']-a['timestamp_sec']>protocol['max_transition_sec']:continue
        window=rows[before[-1]:after[0]+1]
        if any(window[i+1]['timestamp_sec']-window[i]['timestamp_sec']>protocol['max_sample_gap_sec'] for i in range(len(window)-1)):continue
        if not any(r['relation']=='both_near' for r in window):continue
        unknown=[r for r in window if r['relation']=='unknown']
        if len(unknown)>protocol['max_owner_missing_samples']:continue
        if any(r.get('reason')!='role_owner_not_observed' or not r['all_masks_usable'] or not r['cash_motion_continuous'] for r in unknown):continue
        if any(r['relation'] not in ('cashier_near','client_near','both_near','unknown') or not r['cash_motion_continuous'] for r in window):continue
        scale=max(1,(a['cash_diagonal_px']+b['cash_diagonal_px'])/2)
        displacement=math.dist(a['cash_center_px'],b['cash_center_px'])/scale
        if displacement<protocol['min_displacement_relative_to_object']:continue
        events.append({'type':'cash_handover_motion_candidate','direction':'cashier_to_client' if a['relation']=='cashier_near' else 'client_to_cashier','start_sec':a['timestamp_sec'],'end_sec':rows[after[-1]]['timestamp_sec'],'before_support_sec':[rows[before[0]]['timestamp_sec'],a['timestamp_sec']],'after_support_sec':[b['timestamp_sec'],rows[after[-1]]['timestamp_sec']],'contact_times_sec':[r['timestamp_sec'] for r in window if r['relation']=='both_near'],'uncertain_times_sec':[r['timestamp_sec'] for r in unknown],'object_displacement_relative_to_size':displacement,'status':'candidate_with_tracking_gap' if unknown else 'candidate_needs_review','missing_samples_interpolated':False,'possession_established':False,'legal_violation_established':False,'approved_for_rule_engine':False})
    return events
