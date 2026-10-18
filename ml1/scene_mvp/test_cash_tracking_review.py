import copy,unittest
from scene_mvp.cash_tracking_review import validate


class MaskReviewTests(unittest.TestCase):
    def setUp(self):
        self.row={'case_id':'X-13','source_video_sha256':'a'*64,'result_sha256':'b'*64,
            'human_mask_review':'correct_on_reviewed_frames','visited_times_sec':[1],
            'review_scope':'selected_viewed_sampled_frames_not_all_native_frames'}
        self.protocol={'tracking_session':'run','review_protocol_sha256':'p','cases':[
            {'case_id':'X-13','source_video_sha256':'a'*64,'result_sha256':'b'*64,'sample_times_sec':[0,1,2]}]}
        self.review={'schema_version':'cash-tracking-mask-review/1','tracking_session':'run','review_protocol_sha256':'p',
            'confirmed':True,'automatic_legal_verdict':False,'cases':[self.row]}
    def test_limited_mask_review_accepted(self):validate(self.review,self.protocol)
    def test_changed_source_or_run_rejected(self):
        changed=copy.deepcopy(self.review);changed['cases'][0]['result_sha256']='different'
        with self.assertRaises(ValueError):validate(changed,self.protocol)
        self.review['tracking_session']='other'
        with self.assertRaises(ValueError):validate(self.review,self.protocol)
    def test_unseen_frame_or_no_view_rejected(self):
        for times in [[],[1.2]]:
            self.row['visited_times_sec']=times
            with self.assertRaises(ValueError):validate(self.review,self.protocol)
    def test_scope_cannot_be_silently_promoted(self):
        self.row['review_scope']='all_native_frames_verified'
        with self.assertRaises(ValueError):validate(self.review,self.protocol)


if __name__=='__main__':unittest.main()
