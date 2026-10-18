"""Shared cash-retention workflow policy, separate from observed video evidence."""
from copy import deepcopy

STORAGE_TAIL=['cash_counter_use','cash_storage_placement_after_count','cash_storage_closed_after_placement']
SPEC={'version':'cash-custody-workflows/1','policy_source':'explicit_user_cash_custody_workflow_request',
      'storage_tail_steps':STORAGE_TAIL,'applies_to':'cash_retained_by_cashier_after_count',
      'closure_establishes_locking':False,'object_disappearance_establishes_storage':False,
      'missing_video_coverage_establishes_violation':False,'statutory_requirement_asserted':False,
      'automatic_violation_verdict':False}
WORKFLOWS={
    'client_cash_receipt':{'steps':['document_presentation','cash_handover',*STORAGE_TAIL],
        'storage_condition':'received_cash_retained_by_cashier','bind_to_same_client_operation':True},
    'collection_bag_cash_processing':{'steps':['bag_handover','bag_opening',*STORAGE_TAIL],
        'storage_condition':'cash_removed_from_bag_and_retained_by_cashier','bind_to_same_bag_and_cash_batch':True,
        'presenter_check_is_separate_observation':True},
    'cashier_to_client_handover':{'steps':['cashier_to_client_handover'],
        'conditional_retained_cash_branch':STORAGE_TAIL,'storage_condition':'remaining_cash_retained_by_cashier',
        'outgoing_cash_must_not_be_forced_into_storage':True,'transaction_type_inferred_from_direction':False},
    'unknown_cash_operation':{'steps':[],'conditional_retained_cash_branch':STORAGE_TAIL,
        'storage_condition':'cash_retention_and_operation_binding_confirmed',
        'operation_kind_must_not_be_inferred_from_video_filename':True}
}


def workflow_policy(kind):
    if kind not in WORKFLOWS:raise ValueError('Unknown cash workflow')
    return {'workflow_kind':kind,'policy_version':SPEC['version'],**deepcopy(WORKFLOWS[kind]),
            'observations_inferred_from_policy':False}


def storage_stage(order,same_operation):
    result={'storage_state':'not_annotated','storage_closure_state':'not_annotated','storage_lock_status':'not_established','storage_review_candidates':[]}
    if not order:return result
    coverage=order.get('storage_stage_coverage','unknown')
    for field,output,seen in [('cash_storage_after_count_observation','storage_state','cash_stored_after_count_seen'),
                              ('cash_storage_closed_after_placement_observation','storage_closure_state','storage_closed_after_placement_seen')]:
        observed=order.get(field,'unknown')
        if observed=='observed':result[output]=seen if same_operation else 'same_client_operation_not_bound'
        elif observed=='unclear':result[output]='unclear'
        elif observed=='not_observed':
            result[output]='not_observed_in_reviewed_scope'
            if coverage=='complete' and same_operation:
                result['storage_review_candidates'].append({'code':field+'_not_observed','requires_human_review':True,
                    'policy_source':SPEC['policy_source'],'legal_violation_established':False})
    return result
