"""Keep model-proposed and human-added windows separate from legal labels."""
import copy,math

LABELS={'cashier_to_client','client_to_cashier','no_transfer','unclear'}

def deduplicate_windows(events):
    """One event when a human confirms and manually repeats the same window."""
    merged={}
    provenance=('event_id','label_source','candidate_selection_source','boundary_source','model_hypothesis','human_agrees_with_direction')
    for raw in events:
        key=(raw['source_video_sha256'],*raw['reviewed_window_sec'])
        if key in merged and merged[key]['human_label']!=raw['human_label']:
            raise ValueError('Conflicting human answers for the same video/window')
        if key not in merged:
            event=copy.deepcopy(raw);event['review_evidence']=[];event['review_entry_count']=0;merged[key]=event
        event=merged[key];event['review_evidence'].append({k:raw.get(k) for k in provenance});event['review_entry_count']+=1
        event['uncertain_tracking_times_sec']=sorted(set(event['uncertain_tracking_times_sec'])|set(raw['uncertain_tracking_times_sec']))
    return list(merged.values())

def window(start,end):
    if any(type(t) not in (float,int) or not math.isfinite(t) for t in (start,end)) or start<0 or end<start:
        raise ValueError('Invalid window')

def label_record(source,session_name,index,start,end,label,proposal=None):
    return {'event_id':session_name+':'+str(index),'source_session':source['source_session'],
            'source_video_sha256':source['source_video_sha256'],'split_group':source['source_video_sha256'],
            'reviewed_window_sec':[start,end],'human_label':label,
            'handover_confirmed':True if label in {'cashier_to_client','client_to_cashier'} else False if label=='no_transfer' else None,
            'model_hypothesis':proposal['direction'] if proposal else None,
            'human_agrees_with_direction':label==proposal['direction'] if proposal else None,
            'boundary_source':'algorithm_candidate_window_not_frame_accurate_human_boundaries' if proposal else 'human_approximate_window_on_sampled_timeline',
            'frame_accurate_boundaries':False,'uncertain_tracking_times_sec':proposal.get('uncertain_times_sec',[]) if proposal else [],
            'label_source':'human_review_of_displayed_candidate_interval' if proposal else 'human_review_of_sampled_timeline_window',
            'candidate_selection_source':'model_proposal' if proposal else 'explicit_human_window',
            'independent_evaluation':False,'legal_violation_label':None,'approved_for_rule_engine':False}

def validate_direction_review(review,source,session_name):
    if review.get('confirmed') is False:raise ValueError('Direction review is a draft')
    if review.get('schema_version')!=1 or review.get('review_kind')!='transfer_direction_review' or review.get('review_session')!=session_name:
        raise ValueError('Wrong review kind/session')
    for key in ('source_trial','source_session','source_video_sha256'):
        if review.get(key)!=source[key]:raise ValueError('Review source mismatch: '+key)
    scope=review.get('review_scope')
    if scope not in {'displayed_candidate_intervals_only','sampled_timeline_human_windows_and_candidate_intervals'} or review.get('approved_for_rule_engine') is not False:
        raise ValueError('Review scope/approval mismatch')
    candidates=source['transfer_candidates']
    if review.get('transfer_candidates')!=candidates:raise ValueError('Copied predictions changed')
    answers=review.get('human_event_reviews')
    if not isinstance(answers,list) or len(answers)!=len(candidates):raise ValueError('Answer count mismatch')
    events=[]
    for i,(answer,candidate) in enumerate(zip(answers,candidates)):
        if {k:v for k,v in answer.items() if k!='human_direction'}!=candidate:raise ValueError('Reviewed candidate changed')
        label=answer.get('human_direction')
        if label not in LABELS:raise ValueError('Unknown human answer')
        start,end=candidate['start_sec'],candidate['end_sec'];window(start,end)
        events.append(label_record(source,session_name,i,start,end,label,candidate))
    additional=review.get('human_additional_event_reviews',[])
    if not isinstance(additional,list) or len(additional)>100:raise ValueError('Invalid manual windows')
    if additional:
        if scope!='sampled_timeline_human_windows_and_candidate_intervals' or review.get('confirmed') is not True:
            raise ValueError('Confirmed sampled-timeline review required for manual windows')
        times=[r['timestamp_sec'] for r in source.get('timeline',[])]
        if not times:raise ValueError('Source timeline required for manual windows')
        seen=set()
        for i,answer in enumerate(additional):
            if answer.get('source')!='human_selected_sampled_timeline_window' or answer.get('frame_accurate_boundaries') is not False:
                raise ValueError('Invalid manual window provenance')
            label=answer.get('human_direction');start,end=answer.get('start_sec'),answer.get('end_sec');window(start,end)
            if label not in LABELS or start<min(times) or end>max(times) or end<=start:raise ValueError('Manual window outside sampled timeline')
            key=(start,end,label)
            if key in seen:raise ValueError('Duplicate manual window')
            seen.add(key);event=label_record(source,session_name,'manual-'+str(i),start,end,label)
            event['uncertain_tracking_times_sec']=[r['timestamp_sec'] for r in source['timeline'] if start<=r['timestamp_sec']<=end and r.get('relation')=='unknown']
            events.append(event)
    return events
