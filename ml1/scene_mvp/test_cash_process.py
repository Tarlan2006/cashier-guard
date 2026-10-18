import copy,unittest
from scene_mvp.cash_process import candidates,validate_case,human_sequence


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.protocol={'source_session':'s','source_video_sha256':'a'*64,'duration_sec':20,'sample_times_sec':[0,1,2]}
        self.case={'source_session':'s','source_video_sha256':'a'*64,'confirmed':True,'human_cash_type_confirmed':True,
            'cash_anchor_sec':1,'zones':{k:[.1,.1,.4,.4] for k in ['machine_zone','safe_zone','cash_seed']},'same_cash_batch':'unclear'}

    def test_geometry_only_review_is_valid_without_invented_observations(self):validate_case(self.case,self.protocol)
    def test_cross_video_and_missing_seed_rejected(self):
        case=copy.deepcopy(self.case);case['source_video_sha256']='b'*64
        with self.assertRaises(ValueError):validate_case(case,self.protocol)
        del self.case['zones']['cash_seed']
        with self.assertRaises(ValueError):validate_case(self.case,self.protocol)
    def test_anchor_requires_real_sample(self):
        self.case['cash_anchor_sec']=1.2
        with self.assertRaises(ValueError):validate_case(self.case,self.protocol)
    def test_storage_before_counter_end_rejected_for_same_batch(self):
        self.case.update(same_cash_batch='yes',counter_use_observation='observed',counter_use_window_sec=[3,8],
            cash_storage_observation='observed',cash_storage_time_sec=7)
        with self.assertRaises(ValueError):validate_case(self.case,self.protocol)
    def test_one_intersection_or_mask_loss_does_not_establish_action(self):
        rows=[{'timestamp_sec':t,'state':s,'machine_overlap_fraction':o,'safe_overlap_fraction':0} for t,s,o in [(0,'mask_observed',1),(.5,'unknown',None),(1,'unknown',None)]]
        self.assertEqual(candidates(rows),[])
    def test_dwell_yields_only_geometry_candidate(self):
        rows=[{'timestamp_sec':t,'state':'mask_observed','machine_overlap_fraction':.7,'safe_overlap_fraction':0} for t in [0,.5,1]]
        result=candidates(rows);self.assertEqual(len(result),1)
        self.assertFalse(result[0]['cash_counter_use_established']);self.assertFalse(result[0]['cash_storage_established'])
    def test_large_gap_breaks_dwell(self):
        rows=[{'timestamp_sec':t,'state':'mask_observed','machine_overlap_fraction':1,'safe_overlap_fraction':0} for t in [0,.5,2]]
        self.assertEqual(candidates(rows),[])
    def test_geometry_confirmation_does_not_complete_human_action_chain(self):
        result=human_sequence(self.case)
        self.assertEqual(result['visible_sequence_state'],'incomplete_evidence')
        self.assertEqual(result['storage_state'],'not_annotated')
    def test_storage_without_visible_count_is_preserved_without_inventing_count(self):
        self.case.update(same_cash_batch='yes',process_coverage='complete',counter_use_observation='not_observed',
            cash_storage_observation='observed',cash_storage_time_sec=10)
        result=human_sequence(self.case)
        self.assertEqual(result['storage_state'],'placement_seen_count_order_not_established')
        self.assertEqual(result['review_candidates'][0]['code'],'cash_counter_use_not_observed')
    def test_positive_tail_does_not_establish_whole_bag_procedure_or_lock(self):
        self.case.update(same_cash_batch='yes',counter_use_observation='observed',counter_use_window_sec=[3,8],
            cash_storage_observation='observed',cash_storage_time_sec=10,storage_closure_observation='observed',storage_closure_time_sec=12)
        validate_case(self.case,self.protocol);result=human_sequence(self.case)
        self.assertEqual(result['visible_sequence_state'],'count_storage_tail_supported_by_human_review')
        self.assertFalse(result['full_collection_operation_validated']);self.assertEqual(result['storage_lock_status'],'not_established')


if __name__=='__main__':unittest.main()
