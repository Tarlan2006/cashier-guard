import unittest
from import_document_cash_order import validate,apply_timing_clarification


class OrderTests(unittest.TestCase):
    def setUp(self):
        self.protocol={'review_session':'r','source_session':'s','source_video_sha256':'v','duration_sec':20.}
        self.review={'schema_version':'document-cash-order-review/1','review_session':'r','source_session':'s','source_video_sha256':'v',
             'protocol_sha256':'p','confirmed':True,'review_scope':'human_native_video_event_windows','frame_accurate_boundaries':False,
             'automatic_legal_verdict':False,'identity_verification_established':False,'cash_handover_window_sec':[10.,12.],
             'human_direction':'client_to_cashier','same_operation':'yes','counter_use_observation':'observed',
             'counter_use_window_sec':[13.,16.],'manual_count_observation':'unknown'}

    def test_valid_observation_and_unknown_binding_are_accepted(self):
        validate(self.review,self.protocol,'p');self.review['same_operation']='unclear';validate(self.review,self.protocol,'p')

    def test_counter_interval_required_only_when_observed(self):
        self.review['counter_use_window_sec']=None
        with self.assertRaises(ValueError):validate(self.review,self.protocol,'p')
        self.review['counter_use_observation']='not_observed';validate(self.review,self.protocol,'p')

    def test_draft_and_foreign_source_are_rejected(self):
        self.review['confirmed']=False
        with self.assertRaises(ValueError):validate(self.review,self.protocol,'p')

    def test_clarification_preserves_original_span_without_guessing_cash_start(self):
        self.review['cash_handover_window_sec']=[7.118,11.818]
        c={'original_review_sha256':'export','source_video_sha256':'v','document_transfer_at_marked_start_sec':7.118,'human_relative_order':'document_then_banknotes',
           'evidence':{'kind':'explicit_user_chat_reply','answer':'Передают документ, банкноты позже'}}
        accepted=apply_timing_clarification(self.review,c,'export')
        self.assertEqual(accepted['cash_handover_window_sec'],[7.118,11.818])
        self.assertEqual(accepted['cash_window_scope'],'combined_document_and_cash')
        self.assertIsNone(accepted['precise_cash_handover_start_sec'])
        c['original_review_sha256']='other'
        with self.assertRaises(ValueError):apply_timing_clarification(self.review,c,'export')
        self.review['confirmed']=True;self.review['source_video_sha256']='other'
        with self.assertRaises(ValueError):validate(self.review,self.protocol,'p')


if __name__=='__main__':unittest.main()
