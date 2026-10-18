import copy,unittest
from scene_mvp.reviewed_transfers import validate_direction_review

def fixture():
    source={'source_trial':'s','source_session':'video','source_video_sha256':'sha','transfer_candidates':[],
            'timeline':[{'timestamp_sec':t,'relation':'unknown' if t==2 else 'neither_near'} for t in (0,1,2,3)]}
    manual={'start_sec':1,'end_sec':3,'human_direction':'client_to_cashier','source':'human_selected_sampled_timeline_window','frame_accurate_boundaries':False}
    review={'schema_version':1,'review_kind':'transfer_direction_review','review_session':'m','source_trial':'s','source_session':'video',
            'source_video_sha256':'sha','review_scope':'sampled_timeline_human_windows_and_candidate_intervals','approved_for_rule_engine':False,
            'transfer_candidates':[],'human_event_reviews':[],'human_additional_event_reviews':[manual],'confirmed':True}
    return review,source

class ManualTests(unittest.TestCase):
    def test_missed_handover_can_be_labelled_without_a_model_proposal(self):
        r,s=fixture();event=validate_direction_review(r,s,'m')[0]
        self.assertEqual(event['human_label'],'client_to_cashier');self.assertIsNone(event['model_hypothesis']);self.assertIsNone(event['legal_violation_label']);self.assertFalse(event['frame_accurate_boundaries']);self.assertEqual(event['candidate_selection_source'],'explicit_human_window');self.assertEqual(event['uncertain_tracking_times_sec'],[2])
    def test_draft_manual_window_rejected(self):
        r,s=fixture();r['confirmed']=False
        with self.assertRaises(ValueError):validate_direction_review(r,s,'m')
    def test_outside_source_window_rejected(self):
        r,s=fixture();r['human_additional_event_reviews'][0]['end_sec']=4
        with self.assertRaises(ValueError):validate_direction_review(r,s,'m')
    def test_unconfirmed_manual_provenance_rejected(self):
        r,s=fixture();r['human_additional_event_reviews'][0]['source']='model_guess'
        with self.assertRaises(ValueError):validate_direction_review(r,s,'m')
    def test_wrong_scope_rejected(self):
        r,s=fixture();r['review_scope']='displayed_candidate_intervals_only'
        with self.assertRaises(ValueError):validate_direction_review(r,s,'m')
    def test_duplicate_windows_rejected(self):
        r,s=fixture();r['human_additional_event_reviews']*=2
        with self.assertRaises(ValueError):validate_direction_review(r,s,'m')

if __name__=='__main__':unittest.main()
