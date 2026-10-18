import copy,unittest
from scene_mvp.transfer_events import validate,require_two_party_context
from scene_mvp.segmentation_prompts import choose_point_consistent

def fixture():
    target={'bbox':[.1,.2,.4,.5],'timestamp_sec':1.,'source':'human_box_on_visible_target'}
    profile={'schema_version':1,'profile_kind':'hand_transfer_scene','confirmed':True,'source_session':'s','source_video_sha256':'v','roles':{'cashier_ids':[1],'client_ids':[4]},'transfer_direction_supplied':False,'targets':{k:copy.deepcopy(target) for k in ('cash','cashier_hand','client_hand')}}
    session={'session_id':'s','source_video_sha256':'v','frames':[{'timestamp_sec':t,'persons':[{'id':1},{'id':4}]} for t in (1.,2.)]}
    profile['targets']['cash']['points']=[{'xy':[.2,.3],'label':1,'source':'human_click_on_visible_target_or_distractor'},{'xy':[.5,.6],'label':0,'source':'human_click_on_visible_target_or_distractor'}]
    correction=copy.deepcopy(profile['targets']['cash']);correction['timestamp_sec']=2.;profile['cash_corrections']=[correction]
    return profile,session

class PromptTests(unittest.TestCase):
    def test_human_absent_client_blocks_prompted_two_party_trial(self):
        p,s=fixture();c={'source_session':s['session_id'],'source_video_sha256':s['source_video_sha256'],'client_present':False}
        with self.assertRaises(ValueError):require_two_party_context(c,s)
    def test_context_from_different_video_rejected(self):
        p,s=fixture();c={'source_session':s['session_id'],'source_video_sha256':'other','client_present':False}
        with self.assertRaises(ValueError):require_two_party_context(c,s)
    def test_unknown_context_does_not_invent_absence(self):
        _,s=fixture();require_two_party_context(None,s)
    def test_high_score_cannot_override_click_conflict(self):
        self.assertEqual(choose_point_consistent([.9,.2],[[True,False],[True,True]]),1)
    def test_no_consistent_candidate_is_unknown(self):
        self.assertIsNone(choose_point_consistent([.9,.8],[[True,False],[False,True]]))
    def test_choose_highest_rank_only_among_consistent(self):
        self.assertEqual(choose_point_consistent([.7,.9,.8],[[True],[False],[True]]),2)
    def test_two_frames_and_negative_outside_box_supported(self):
        p,s=fixture();validate(p,s)
    def test_same_frame_correction_rejected(self):
        p,s=fixture();p['cash_corrections'][0]['timestamp_sec']=1.
        with self.assertRaises(ValueError):validate(p,s)
    def test_unavailable_frame_rejected(self):
        p,s=fixture();p['cash_corrections'][0]['timestamp_sec']=9.
        with self.assertRaises(ValueError):validate(p,s)
    def test_positive_point_outside_box_rejected(self):
        p,s=fixture();p['cash_corrections'][0]['points'][0]['xy']=[.9,.9]
        with self.assertRaises(ValueError):validate(p,s)
    def test_nonfinite_point_rejected(self):
        p,s=fixture();p['cash_corrections'][0]['points'][0]['xy']=[float('nan'),.3]
        with self.assertRaises(ValueError):validate(p,s)
    def test_label_bool_rejected(self):
        p,s=fixture();p['cash_corrections'][0]['points'][0]['label']=True
        with self.assertRaises(ValueError):validate(p,s)
    def test_direction_hint_rejected(self):
        p,s=fixture();p['transfer_direction_supplied']=True
        with self.assertRaises(ValueError):validate(p,s)

if __name__=='__main__':unittest.main()
