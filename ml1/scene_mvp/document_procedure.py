"""Join document, cash, counter and storage observations; no legal verdict."""
import math
from scene_mvp.cash_custody import STORAGE_TAIL,storage_stage

SPEC={'version':'document-cash-counter-storage-sequence/3','approximate_time_margin_sec':.5,
      'required_visible_steps':['document_presentation','cash_handover',*STORAGE_TAIL],
      'counter_step_policy_source':'explicit_user_workflow_request_not_a_statutory_claim',
      'storage_step_policy_source':'explicit_user_cash_custody_workflow_request',
      'automatic_identity_verification':False,'rule_engine_enabled':False}


def window(value):
    if not isinstance(value,list) or len(value)!=2 or any(type(t) not in (int,float) or not math.isfinite(t) for t in value) or not 0<=value[0]<=value[1]:
        raise ValueError('Finite nonnegative observation window required')
    return value


def analyze(document,cash=None,order=None,spec=SPEC):
    sha=document['source_video_sha256'];result={'schema_version':spec['version'],'source_video_sha256':sha,
        'document_state':'unknown','counter_state':'not_annotated','visible_sequence_state':'incomplete_evidence',
        'storage_state':'not_annotated','storage_closure_state':'not_annotated','storage_lock_status':'not_established',
        'review_candidates':[],'identity_verification_status':'unknown_no_bank_record','cash_count_accuracy_established':False,
        'automatic_identity_failure_detected':False,'legal_violation_label':None,'approved_for_rule_engine':False,
        'evidence_basis':'human_reviewed_visual_observations','frame_accurate_boundaries':False}
    if cash is None:
        result['document_state']='cash_handover_not_annotated';return result
    if cash['source_video_sha256']!=sha or order is not None and order['source_video_sha256']!=sha:
        raise ValueError('Never join different original videos')
    if cash.get('handover_confirmed') is not True or cash.get('human_label')!='client_to_cashier':
        result['document_state']='not_a_confirmed_incoming_cash_handover';return result
    cash_span=window(cash['reviewed_window_sec'])
    combined=bool(order and order.get('cash_window_scope')=='combined_document_and_cash')
    result['cash_handover_window_sec']=None if combined else cash_span
    if combined:
        result.update(document_cash_combined_window_sec=cash_span,precise_cash_handover_start_sec=None,
                      document_cash_order_source='explicit_human_relative_order_clarification',
                      human_document_transfer_point_sec=order['human_timing_clarification']['document_transfer_at_marked_start_sec'] if order.get('human_timing_clarification') else None)
    doc_state=document['physical_document_observation'];same=order and order.get('same_operation')=='yes'
    margin=spec['approximate_time_margin_sec']
    if doc_state=='not_observed':
        if document.get('complete_operation_visible')=='yes':
            result['document_state']='physical_document_presentation_not_observed'
            result['review_candidates'].append({'code':'physical_document_presentation_not_observed_before_cash',
                'message_ru':'Предъявление физического документа перед приёмом денег не наблюдается.',
                'window_sec':cash_span,'requires_human_review':True,'identity_failure_established':False})
        else:result['document_state']='insufficient_video_coverage'
    elif doc_state=='presentation_seen':
        doc_span=window(document['presentation_window_sec']);result['document_presentation_window_sec']=doc_span
        if not same:result['document_state']='same_client_operation_not_bound'
        elif combined and order.get('human_relative_order')=='document_then_banknotes':
            result['document_state']='human_reported_document_transfer_precedes_cash'
        elif combined:result['document_state']='document_cash_order_unclear'
        elif doc_span[1]+margin<cash_span[0]:result['document_state']='visible_document_presentation_precedes_cash'
        elif doc_span[0]>cash_span[1]+margin:
            result['document_state']='visible_document_presentation_after_marked_cash_handover'
            result['review_candidates'].append({'code':'document_cash_order_requires_review','requires_human_review':True,'window_sec':cash_span})
        else:result['document_state']='document_cash_order_unclear'
    elif doc_state=='already_present':result['document_state']='document_present_but_presentation_not_established'
    else:result['document_state']='document_observation_unclear'
    if order:
        counter=order.get('counter_use_observation');counter_span=order.get('counter_use_window_sec')
        if counter=='observed':
            counter_span=window(counter_span);result['counter_use_window_sec']=counter_span
            if not same:result['counter_state']='same_client_operation_not_bound'
            elif combined and counter_span[0]>cash_span[1]+margin:result['counter_state']='counter_use_seen_after_combined_document_cash_window'
            elif combined:result['counter_state']='cash_counter_order_unclear'
            elif counter_span[0]>cash_span[0]+margin:result['counter_state']='counter_use_seen_after_cash_handover_started'
            elif counter_span[1]<cash_span[0]-margin:result['counter_state']='counter_event_precedes_handover_needs_review'
            else:result['counter_state']='cash_counter_order_unclear'
        elif counter=='not_observed':
            result['counter_state']='cash_counter_use_not_observed'
            if document.get('complete_operation_visible')=='yes' and same:
                result['review_candidates'].append({'code':'cash_counter_use_not_observed',
                    'message_ru':'Использование счётной машины в отмеченной операции не наблюдается.',
                    'requires_human_review':True,'policy_source':spec['counter_step_policy_source'],
                    'manual_count_observation':order.get('manual_count_observation','unknown'),
                    'absence_of_any_count_established':False})
        elif counter=='unclear':result['counter_state']='counter_use_unclear'
    if result['document_state'] in {'visible_document_presentation_precedes_cash','human_reported_document_transfer_precedes_cash'} and result['counter_state'] in {'counter_use_seen_after_cash_handover_started','counter_use_seen_after_combined_document_cash_window'}:
        result['visible_sequence_state']='visible_steps_supported_by_human_relative_order' if combined else 'required_visible_steps_observed'
    elif result['review_candidates']:result['visible_sequence_state']='visual_procedure_review_candidate'
    result['pre_storage_sequence_state']=result['visible_sequence_state']
    storage=storage_stage(order,same);result['review_candidates'].extend(storage.pop('storage_review_candidates'));result.update(storage)
    if result['review_candidates']:result['visible_sequence_state']='visual_procedure_review_candidate'
    elif result['storage_state']!='cash_stored_after_count_seen' or result['storage_closure_state']!='storage_closed_after_placement_seen':
        result['visible_sequence_state']='incomplete_evidence'
    return result
