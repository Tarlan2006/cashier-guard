"""Export human-assisted procedure evidence separately from automatic detections."""
import hashlib,json
from pathlib import Path
from run_ollama_trial import ROOT,write_json
from scene_mvp.document_procedure import SPEC,analyze
from scene_mvp.cash_custody import STORAGE_TAIL,SPEC as CUSTODY_SPEC,WORKFLOWS,workflow_policy


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def build_and_save():
    dataset=Path(json.loads((ROOT/'local/identity-dataset-current.local.json').read_text())['dataset'])
    labels_path=dataset/'video-observations.jsonl';docs=[json.loads(s) for s in labels_path.read_text().splitlines()]
    catalog_path=ROOT/'outputs/forte_scenarios_from_pdf.json';catalog=json.loads(catalog_path.read_text())
    if sha(Path(catalog['source_pdf']))!=catalog['source_pdf_sha256']:raise ValueError('Scenario source PDF changed')
    catalog_by_sha={r['video_sha256']:r for r in reversed(catalog['records'])}
    orders={}
    for path in sorted((ROOT/'local').glob('document-cash-order-*/human-order-review.accepted.local.json')):
        order=json.loads(path.read_text())
        if order.get('confirmed') is True:orders[order['source_video_sha256']]=order
    events={}
    for path in sorted((ROOT/'local').glob('transfer-labels-*/events.jsonl')):
        for line in path.read_text().splitlines():
            event=json.loads(line);key=(event['source_video_sha256'],event['human_label'],tuple(event['reviewed_window_sec']))
            if event.get('handover_confirmed') is True:events[key]=event
    cases=[]
    for doc in docs:
        digest=doc['source_video_sha256'];order=orders.get(digest)
        matching=[e for e in events.values() if e['source_video_sha256']==digest]
        cash=next((e for e in matching if e['human_label']=='client_to_cashier'),matching[0] if matching else None)
        if order:
            cash={'source_video_sha256':digest,'human_label':order['human_direction'],
                  'handover_confirmed':True if order['human_direction'] in ['client_to_cashier','cashier_to_client'] else None,
                  'reviewed_window_sec':order['cash_handover_window_sec'],'label_source':'human_native_video_event_windows'}
        result=analyze(doc,cash,order)
        workflow='client_cash_receipt' if cash and cash.get('human_label')=='client_to_cashier' else 'cashier_to_client_handover' if cash and cash.get('human_label')=='cashier_to_client' else 'unknown_cash_operation'
        reference=catalog_by_sha[digest]
        cases.append({'source_name':doc['source_name'],'cash_workflow_policy':workflow_policy(workflow),'scenario_reference_ids':reference['same_video_reference_ids'],
            'scenario_reference_time_sec':reference['reference_timestamp_sec'],'source_pdf_risk':reference['risk_annotation'],
            'source_pdf_annotation':reference['annotation_type'],'document_evidence':{
                'source_kind':'human_native_video_review','physical_document_observation':doc['physical_document_observation'],
                'presentation_window_sec':doc['presentation_window_sec'],'complete_operation_visible':doc['complete_operation_visible']},
            'cash_evidence':None if cash is None else {
                'human_label':cash['human_label'],'handover_confirmed':cash['handover_confirmed'],
                'cash_handover_window_sec':None if order and order.get('cash_window_scope')=='combined_document_and_cash' else cash['reviewed_window_sec'],
                'document_cash_combined_window_sec':cash['reviewed_window_sec'] if order and order.get('cash_window_scope')=='combined_document_and_cash' else None,
                'precise_cash_handover_start_sec':None,
                'human_relative_order':order.get('human_relative_order') if order else None},
            'counter_evidence':None if not order else {'observation':order['counter_use_observation'],'window_sec':order['counter_use_window_sec'],
                                                       'manual_count_observation':order['manual_count_observation']},
            'storage_evidence':None if not order else {'cash_storage_after_count_observation':order.get('cash_storage_after_count_observation','unknown'),
                'cash_storage_closed_after_placement_observation':order.get('cash_storage_closed_after_placement_observation','unknown'),
                'storage_stage_coverage':order.get('storage_stage_coverage','unknown')},
            'result':result})
    # A passed/held document clip cannot be applied to every client in a multi-client video.
    pointer=ROOT/'local/document-tracking-current.local.json'
    if pointer.exists():
        tracking=Path(json.loads(pointer.read_text())['trial']);review_path=tracking/'human-track-review.accepted.local.json'
        if review_path.exists():
            reviewed=json.loads(review_path.read_text());p=json.loads((tracking/'protocol.local.json').read_text());digest=p['source_video_sha256']
            if digest not in {c['result']['source_video_sha256'] for c in cases}:
                reference=catalog_by_sha[digest]
                cases.append({'source_name':reference['filename'],'cash_workflow_policy':workflow_policy('unknown_cash_operation'),'scenario_reference_ids':reference['same_video_reference_ids'],
                    'source_pdf_annotation':reference['annotation_type'],'document_evidence':{'source_kind':'human_sampled_clip_review',
                       'human_claimed_object_kind':reviewed.get('human_claimed_object_kind'),
                       'human_observed_actions':reviewed.get('human_observed_actions',[]),'confirmed_visible_anchor_sec':p['anchor_sec'],
                       'complete_operation_visible':'unknown','action_intervals_not_annotated':True},
                    'cash_evidence':None,'counter_evidence':None,'storage_evidence':None,
                    'result':{'source_video_sha256':digest,'document_state':'document_clip_not_bound_to_one_client_cash_operation',
                        'counter_state':'not_annotated','storage_state':'not_annotated','storage_closure_state':'not_annotated',
                        'storage_lock_status':'not_established','visible_sequence_state':'incomplete_evidence','review_candidates':[],
                        'identity_verification_status':'unknown_no_bank_record','legal_violation_label':None,'approved_for_rule_engine':False}})
    output={'schema_version':SPEC['version'],'prototype_kind':'human_assisted_visual_procedure_analysis','spec':SPEC,
        'cash_custody_tail_steps':STORAGE_TAIL,'cash_workflow_policy_catalog':'outputs/forte_cash_workflows.json',
        'source_pdf_sha256':catalog['source_pdf_sha256'],'source_catalog_sha256':sha(catalog_path),
        'identity_labels_sha256':sha(labels_path),'automatic_end_to_end_detector_validated':False,
        'counter_policy_is_user_workflow_not_statutory_assertion':True,'approved_for_rule_engine':False,'cases':cases}
    path=ROOT/'outputs/forte_document_cash_counter_sequence.json';write_json(path,output)
    write_json(ROOT/'outputs/forte_cash_workflows.json',{'schema_version':CUSTODY_SPEC['version'],'spec':CUSTODY_SPEC,
        'scenario_source_catalog':'outputs/forte_scenarios_from_pdf.json','source_pdf_sha256':catalog['source_pdf_sha256'],
        'workflow_steps_are_user_policy_not_pdf_transcription':True,'workflows':[workflow_policy(k) for k in WORKFLOWS],
        'existing_video_observations_not_modified':True,'automatic_execution_validated':False})
    print('DOCUMENT_CASH_COUNTER_SEQUENCE_READY:',path)
    print(json.dumps({'cases':len(cases),'visual_review_candidates':sum(len(c['result']['review_candidates']) for c in cases),
                      'supported_visible_sequences':sum(c['result']['visible_sequence_state'] in {'required_visible_steps_observed','visible_steps_supported_by_human_relative_order'} for c in cases),
                      'supported_before_storage':sum(c['result'].get('pre_storage_sequence_state') in {'required_visible_steps_observed','visible_steps_supported_by_human_relative_order'} for c in cases),
                      'automatic_legal_verdicts':0}))
    return path


if __name__=='__main__':build_and_save()
