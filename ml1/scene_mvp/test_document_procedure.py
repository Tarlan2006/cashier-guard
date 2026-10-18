import unittest
from scene_mvp.document_procedure import analyze,storage_stage


class ProcedureTests(unittest.TestCase):
    def setUp(self):
        self.document={'source_video_sha256':'a','physical_document_observation':'presentation_seen','presentation_window_sec':[7.5,8.5],'complete_operation_visible':'yes'}
        self.cash={'source_video_sha256':'a','handover_confirmed':True,'human_label':'client_to_cashier','reviewed_window_sec':[10.,12.]}
        self.order={'source_video_sha256':'a','same_operation':'yes','counter_use_observation':'observed','counter_use_window_sec':[13.,15.]}

    def test_expected_sequence_does_not_establish_identity_or_count_accuracy(self):
        r=analyze(self.document,self.cash,self.order)
        self.assertEqual(r['pre_storage_sequence_state'],'required_visible_steps_observed')
        self.assertEqual(r['visible_sequence_state'],'incomplete_evidence')
        self.assertEqual(r['identity_verification_status'],'unknown_no_bank_record')
        self.assertIsNone(r['legal_violation_label']);self.assertFalse(r['cash_count_accuracy_established'])

    def test_visible_absence_requires_whole_procedure_coverage(self):
        self.document['physical_document_observation']='not_observed';self.document['presentation_window_sec']=None
        self.assertTrue(analyze(self.document,self.cash)['review_candidates'])
        self.document['complete_operation_visible']='no'
        self.assertFalse(analyze(self.document,self.cash)['review_candidates'])

    def test_outgoing_partial_cash_return_is_not_cash_receipt(self):
        self.cash['human_label']='cashier_to_client'
        self.assertEqual(analyze(self.document,self.cash,self.order)['document_state'],'not_a_confirmed_incoming_cash_handover')

    def test_document_cannot_be_borrowed_from_another_client_operation(self):
        self.order['same_operation']='unclear'
        r=analyze(self.document,self.cash,self.order)
        self.assertEqual(r['document_state'],'same_client_operation_not_bound')

    def test_overlap_has_unknown_order(self):
        self.cash['reviewed_window_sec']=[8.,10.]
        self.assertEqual(analyze(self.document,self.cash,self.order)['document_state'],'document_cash_order_unclear')

    def test_counter_absence_does_not_invent_no_manual_count(self):
        self.order.update(counter_use_observation='not_observed',counter_use_window_sec=None,manual_count_observation='observed')
        r=analyze(self.document,self.cash,self.order)
        self.assertFalse(r['review_candidates'][0]['absence_of_any_count_established'])

    def test_different_videos_not_joined(self):
        self.cash['source_video_sha256']='other'
        with self.assertRaises(ValueError):analyze(self.document,self.cash,self.order)

    def test_combined_document_cash_window_does_not_invent_cash_start(self):
        self.cash['reviewed_window_sec']=[7.118,11.818]
        self.order.update(cash_window_scope='combined_document_and_cash',human_relative_order='document_then_banknotes',counter_use_window_sec=[17.39,20.033])
        r=analyze(self.document,self.cash,self.order)
        self.assertIsNone(r['cash_handover_window_sec']);self.assertIsNone(r['precise_cash_handover_start_sec'])
        self.assertEqual(r['pre_storage_sequence_state'],'visible_steps_supported_by_human_relative_order')
        self.assertIsNone(r['legal_violation_label'])

    def test_counter_inside_combined_window_is_not_assumed_after_cash(self):
        self.cash['reviewed_window_sec']=[7.118,11.818]
        self.order.update(cash_window_scope='combined_document_and_cash',human_relative_order='document_then_banknotes',counter_use_window_sec=[8.,9.])
        self.assertEqual(analyze(self.document,self.cash,self.order)['counter_state'],'cash_counter_order_unclear')

    def test_full_chain_requires_cash_placement_and_closure(self):
        self.order.update(cash_storage_after_count_observation='observed',cash_storage_closed_after_placement_observation='observed',storage_stage_coverage='complete')
        result=analyze(self.document,self.cash,self.order)
        self.assertEqual(result['visible_sequence_state'],'required_visible_steps_observed')
        self.assertEqual(result['storage_lock_status'],'not_established')

    def test_short_video_does_not_invent_failure_to_store_cash(self):
        result=storage_stage({'cash_storage_after_count_observation':'not_observed','storage_stage_coverage':'incomplete'},True)
        self.assertFalse(result['storage_review_candidates'])

    def test_storage_cannot_be_borrowed_from_other_operation(self):
        self.order.update(cash_storage_after_count_observation='observed',cash_storage_closed_after_placement_observation='observed',same_operation='unclear')
        self.assertEqual(analyze(self.document,self.cash,self.order)['storage_state'],'same_client_operation_not_bound')


if __name__=='__main__':unittest.main()
