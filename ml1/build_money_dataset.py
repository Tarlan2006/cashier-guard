"""Keep human cash labels separate from algorithm features and legal labels."""
import datetime,hashlib,json
from pathlib import Path
from run_ollama_trial import ROOT,write_json

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    out=ROOT/'local'/('money-dataset-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir()
    cases=[('X-26','sam2-object-20261017-233247-548254','object-review-20261017-233721-280240/human-mask-review.accepted.local.json',
            'cash_left_during_departure','в х26 на 9 секунде оставила деньги на столе не спрятав в место хранения и вышла из кабинета'),
           ('X-27','sam2-object-20261017-234632-929486','object-review-20261017-234849-977426/human-control-review.accepted.local.json',
            'cash_removed_before_departure',None)]
    labels=[];feature_rows=[];quality=[]
    for name,trial,review_name,label,statement in cases:
        folder=ROOT/'local'/trial;profile=json.loads((folder/'calibration.local.json').read_text());observations=json.loads((folder/'observations.local.json').read_text())
        session=json.loads((ROOT/'local'/profile['source_session']/'session.local.json').read_text())
        if sha(Path(session['source_video']))!=profile['source_video_sha256']:raise ValueError('Cash source bytes changed')
        review_path=ROOT/'local'/review_name;review=json.loads(review_path.read_text())
        matched=[c for c in review['cases'] if c['report_folder']==trial and c['source_video_sha256']==profile['source_video_sha256']]
        if len(matched)!=1 or matched[0]['human_mask_review']!='correct_on_selected_frames':raise ValueError('Cash mask review missing')
        human=matched[0]
        if label=='cash_removed_before_departure' and human.get('human_object_removed_before_departure')!='yes':raise ValueError('Cash removal label missing')
        event={'task':'cash_left_during_cashier_departure','video':name,'source_video_sha256':profile['source_video_sha256'],'source_session':profile['source_session'],
               'split_group':profile['source_video_sha256'],'human_label':label,'human_label_source':'direct_user_conversation' if statement else 'accepted_human_review',
               'human_statement':statement,'human_stated_time_sec':9 if statement else None,'frame_accurate_boundaries':False,
               'review_scope':human.get('review_scope','selected_evidence_frames_only'),'reviewed_times_sec':human['selected_evidence_times_sec'],
               'mask_review_scope':'selected_evidence_frames_only','review_sha256':sha(review_path),'legal_violation_label':None,
               'approved_for_rule_engine':False,'predictions_used_as_labels':False}
        labels.append(event)
        rows=observations['timeline'];known=sum(r.get('experimental_object',{}).get('state')=='mask_observed' for r in rows)
        away=[r for r in rows if r.get('departure_supported') is True]
        lost_at_departure=sum(r.get('experimental_object',{}).get('state')!='mask_observed' for r in away)
        quality.append({'video':name,'observed_object_frames':known,'sampled_frames':len(rows),'object_coverage':known/len(rows),
                        'supported_departure_frames':len(away),'unknown_object_during_departure':lost_at_departure,
                        'absence_inferred_from_lost_mask':False,'automatic_negative_established':False})
        for row in rows:feature_rows.append({'task':'cash_left_during_cashier_departure','split_group':profile['source_video_sha256'],'source_trial':trial,
                                            'timestamp_sec':row['timestamp_sec'],'persons':row.get('persons',[]),'object_observation':row.get('experimental_object',{}),
                                            'frame_label':None,'label_reason':'only_weak_event_or_selected_review_labels_available'})
    transfers=[];seen=set()
    for folder in sorted((ROOT/'local').glob('transfer-labels-*')):
        path=folder/'events.jsonl'
        if not path.exists():continue
        for line in path.read_text().splitlines():
            event=json.loads(line)
            key=(event['source_video_sha256'],tuple(event['reviewed_window_sec']),event['human_label'])
            if key in seen:continue
            if event.get('label_source') not in {'human_review_of_displayed_candidate_interval','human_review_of_sampled_timeline_window'} or event.get('legal_violation_label') is not None:
                raise ValueError('Expected human direction labels without legal verdict')
            seen.add(key);transfers.append({'task':'cash_handover_direction',**event})
    video_labels=[];seen_videos=set()
    for path in sorted((ROOT/'local').glob('transfer-motion-*/human-video-direction.accepted.local.json')):
        data=json.loads(path.read_text())
        if data.get('review_kind')!='video_level_cash_direction' or data.get('confirmed') is not True or data.get('reviewed_window_sec') is not None:
            raise ValueError('Expected explicit video-level direction without invented boundaries')
        key=(data['source_video_sha256'],data['human_label'])
        if key not in seen_videos:video_labels.append(data);seen_videos.add(key)
    statements=video_labels
    video_labels=[v for v in statements if not any(e['source_video_sha256']==v['source_video_sha256'] and e['human_label']==v['human_label'] for e in transfers)]
    for name,rows in [('cash-left-events.jsonl',labels),('cash-left-observations.jsonl',feature_rows),('cash-transfer-events.jsonl',transfers),('cash-transfer-video-labels.jsonl',video_labels),('cash-transfer-video-statements.jsonl',statements)]:
        (out/name).write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows),encoding='utf-8')
    manifest={'schema_version':'money-dataset/1','cash_left_human_cases':len(labels),'cash_left_feature_frames':len(feature_rows),'cash_transfer_human_windows':len(transfers),
              'cash_transfer_video_level_labels':len(video_labels),'raw_video_direction_statements':len(statements),'redundant_video_labels_covered_by_reviewed_windows':len(statements)-len(video_labels),'cash_transfer_video_groups':len({e['source_video_sha256'] for e in transfers+video_labels}),'cash_left_tracking_quality':quality,
              'task_labels_not_merged':True,'cash_classifier_trained':False,'training_dataset_sufficient':False,
              'frames_outside_reviewed_events_are_not_negatives':True,'split_rule':'group all duplicate videos and frames by original_video_sha256',
              'legal_violation_labels_created':False,'approved_for_rule_engine':False}
    write_json(out/'manifest.local.json',manifest)
    print('MONEY_DATASET_READY:',out);print(json.dumps(manifest,ensure_ascii=False))

if __name__=='__main__':main()
