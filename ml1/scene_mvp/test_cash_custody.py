import unittest
from scene_mvp.cash_custody import STORAGE_TAIL,workflow_policy,storage_stage


class CashCustodyTests(unittest.TestCase):
    def test_receipts_and_bag_cash_share_storage_tail(self):
        for kind in ['client_cash_receipt','collection_bag_cash_processing']:
            self.assertEqual(workflow_policy(kind)['steps'][-3:],STORAGE_TAIL)

    def test_paid_out_cash_not_forced_into_storage(self):
        policy=workflow_policy('cashier_to_client_handover')
        self.assertNotIn('cash_storage_placement_after_count',policy['steps'])
        self.assertEqual(policy['conditional_retained_cash_branch'],STORAGE_TAIL)
        self.assertFalse(policy['transaction_type_inferred_from_direction'])

    def test_policy_does_not_infer_observations(self):
        self.assertFalse(workflow_policy('client_cash_receipt')['observations_inferred_from_policy'])
        self.assertEqual(storage_stage(None,True)['storage_state'],'not_annotated')
        copy=workflow_policy('client_cash_receipt');copy['steps'].clear()
        self.assertTrue(workflow_policy('client_cash_receipt')['steps'])

    def test_complete_scope_and_same_operation_required_for_absence_candidate(self):
        order={'cash_storage_after_count_observation':'not_observed','storage_stage_coverage':'complete'}
        self.assertTrue(storage_stage(order,True)['storage_review_candidates'])
        self.assertFalse(storage_stage(order,False)['storage_review_candidates'])
        order['storage_stage_coverage']='unknown'
        self.assertFalse(storage_stage(order,True)['storage_review_candidates'])

    def test_closed_safe_does_not_establish_money_inside_or_lock(self):
        result=storage_stage({'cash_storage_closed_after_placement_observation':'observed'},True)
        self.assertEqual(result['storage_state'],'not_annotated')
        self.assertEqual(result['storage_lock_status'],'not_established')


if __name__=='__main__':unittest.main()
