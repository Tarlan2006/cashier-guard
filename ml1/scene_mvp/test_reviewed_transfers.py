import copy,unittest
from scene_mvp.reviewed_transfers import validate_direction_review

def fixture():
    event={'start_sec':1.,'end_sec':3.,'direction':'cashier_to_client','uncertain_times_sec':[2.]}
    source={'source_trial':'s','source_session':'video','source_video_sha256':'sha','transfer_candidates':[event]}
    review={'schema_version':1,'review_kind':'transfer_direction_review','review_session':'m','source_trial':'s','source_session':'video','source_video_sha256':'sha','review_scope':'displayed_candidate_intervals_only','approved_for_rule_engine':False,'transfer_candidates':[copy.deepcopy(event)],'human_event_reviews':[{**event,'human_direction':'cashier_to_client'}]}
    return review,source

class ReviewTests(unittest.TestCase):
    def test_explicit_draft_rejected(self):
        r,s=fixture();r['confirmed']=False
        with self.assertRaises(ValueError):validate_direction_review(r,s,'m')
    def test_direction_label_does_not_become_violation_or_precise_boundaries(self):
        r,s=fixture();e=validate_direction_review(r,s,'m')[0]
        self.assertTrue(e['handover_confirmed']);self.assertIsNone(e['legal_violation_label']);self.assertFalse(e['frame_accurate_boundaries']);self.assertEqual(e['split_group'],'sha');self.assertEqual(e['uncertain_tracking_times_sec'],[2.])
    def test_human_can_disagree_with_model(self):
        r,s=fixture();r['human_event_reviews'][0]['human_direction']='client_to_cashier';e=validate_direction_review(r,s,'m')[0]
        self.assertEqual(e['human_label'],'client_to_cashier');self.assertFalse(e['human_agrees_with_direction'])
    def test_no_transfer_is_explicit_negative_window(self):
        r,s=fixture();r['human_event_reviews'][0]['human_direction']='no_transfer';self.assertIs(validate_direction_review(r,s,'m')[0]['handover_confirmed'],False)
    def test_unclear_is_not_negative(self):
        r,s=fixture();r['human_event_reviews'][0]['human_direction']='unclear';self.assertIsNone(validate_direction_review(r,s,'m')[0]['handover_confirmed'])
    def test_tampered_video_rejected(self):
        r,s=fixture();r['source_video_sha256']='other'
        with self.assertRaises(ValueError):validate_direction_review(r,s,'m')
    def test_tampered_interval_rejected(self):
        r,s=fixture();r['human_event_reviews'][0]['start_sec']=0.
        with self.assertRaises(ValueError):validate_direction_review(r,s,'m')

if __name__=='__main__':unittest.main()
