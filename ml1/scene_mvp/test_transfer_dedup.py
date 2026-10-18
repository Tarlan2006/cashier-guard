import copy,unittest
from scene_mvp.reviewed_transfers import deduplicate_windows

def event():
    return {'event_id':'model:0','source_video_sha256':'video','reviewed_window_sec':[9.5,13.466666666666667],
            'human_label':'client_to_cashier','label_source':'human_review_of_displayed_candidate_interval',
            'candidate_selection_source':'model_proposal','boundary_source':'algorithm_candidate_window_not_frame_accurate_human_boundaries',
            'model_hypothesis':'client_to_cashier','human_agrees_with_direction':True,'uncertain_tracking_times_sec':[10.5,11],
            'frame_accurate_boundaries':False,'legal_violation_label':None,'approved_for_rule_engine':False}

class DedupTests(unittest.TestCase):
    def test_confirmed_and_manual_copy_are_one_window_with_both_sources(self):
        a=event();b=copy.deepcopy(a);b.update(event_id='manual:0',label_source='human_review_of_sampled_timeline_window',candidate_selection_source='explicit_human_window',model_hypothesis=None,human_agrees_with_direction=None,uncertain_tracking_times_sec=[10.5])
        rows=deduplicate_windows([a,b]);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['review_entry_count'],2);self.assertEqual(len(rows[0]['review_evidence']),2);self.assertEqual(rows[0]['uncertain_tracking_times_sec'],[10.5,11]);self.assertIsNone(rows[0]['legal_violation_label']);self.assertNotIn('review_evidence',a)
    def test_conflicting_same_window_rejected(self):
        a=event();b=copy.deepcopy(a);b['human_label']='cashier_to_client'
        with self.assertRaises(ValueError):deduplicate_windows([a,b])
    def test_different_video_is_not_duplicate(self):
        a=event();b=copy.deepcopy(a);b['source_video_sha256']='other';self.assertEqual(len(deduplicate_windows([a,b])),2)
    def test_overlap_with_different_bounds_not_silently_merged(self):
        a=event();b=copy.deepcopy(a);b['reviewed_window_sec'][0]=10;self.assertEqual(len(deduplicate_windows([a,b])),2)

if __name__=='__main__':unittest.main()
