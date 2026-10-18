import copy,hashlib,json,tempfile,unittest
from pathlib import Path
from scene_mvp.money_pipeline import frozen_check,check_mask_review

def fixture():
    profile={'source_session':'s','source_video_sha256':'video'}
    observations={'transfer_candidates':[]}
    review={'schema_version':1,'review_session':'trial','source_session':'s','source_video_sha256':'video',
            'confirmed':True,'review_scope':'user_reviewed_frames_only','approved_for_rule_engine':False,
            'transfer_candidates':[],'human_target_reviews':{k:'correct_on_reviewed_frames' for k in ('cash','cashier_hand','client_hand')}}
    return profile,observations,review

class ReviewTests(unittest.TestCase):
    def test_wrong_video_rejected(self):
        p,o,r=fixture();r['source_video_sha256']='other'
        with self.assertRaises(ValueError):check_mask_review(r,'trial',p,o)
    def test_draft_rejected(self):
        p,o,r=fixture();r['confirmed']=False
        with self.assertRaises(ValueError):check_mask_review(r,'trial',p,o)
    def test_bad_mask_does_not_authorize_motion(self):
        p,o,r=fixture();r['human_target_reviews']['cash']='incorrect_on_reviewed_frames'
        self.assertFalse(check_mask_review(r,'trial',p,o))
    def test_missing_answer_rejected(self):
        p,o,r=fixture();del r['human_target_reviews']['client_hand']
        with self.assertRaises(ValueError):check_mask_review(r,'trial',p,o)
    def test_prediction_edits_rejected(self):
        p,o,r=fixture();r['transfer_candidates']=[{'direction':'client_to_cashier'}]
        with self.assertRaises(ValueError):check_mask_review(r,'trial',p,o)
    def test_valid_review_retains_limited_scope(self):
        p,o,r=fixture();self.assertTrue(check_mask_review(r,'trial',p,o));self.assertEqual(r['review_scope'],'user_reviewed_frames_only')

class FrozenTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.plan_id='transfer-control-plan-20261018-000001';folder=self.root/'local'/self.plan_id;folder.mkdir(parents=True)
        self.code=self.root/'frozen.py';self.code.write_text('fixed parameters')
        runtime=self.root/'local/runtime';runtime.mkdir();(runtime/'sam2-runtime.local.json').write_text(json.dumps({'source_revision':'r','weights_sha256':'w'}))
        self.plan={'source_session':'s','source_video_sha256':'video','development_video_sha256':'development',
                   'expected_direction_supplied':False,'direction_labels_used':False,
                   'code_sha256':{'frozen.py':hashlib.sha256(self.code.read_bytes()).hexdigest()},'sam_source_revision':'r','sam_weights_sha256':'w'}
        self.path=folder/'plan.local.json';self.path.write_text(json.dumps(self.plan))
        self.profile={'source_session':'s','source_video_sha256':'video','validation_plan':{'plan_id':self.plan_id,'sha256':hashlib.sha256(self.path.read_bytes()).hexdigest()}}
    def test_valid_frozen_check_is_not_accuracy_claim(self):
        result=frozen_check(self.root,self.profile);self.assertTrue(result['different_from_development_video']);self.assertFalse(result['independent_accuracy_established']);self.assertFalse(result['review_blinded'])
    def test_changed_code_rejected(self):
        self.code.write_text('tuned parameters')
        with self.assertRaises(ValueError):frozen_check(self.root,self.profile)
    def test_changed_plan_rejected(self):
        self.path.write_text('{}')
        with self.assertRaises(ValueError):frozen_check(self.root,self.profile)
    def test_wrong_source_rejected(self):
        self.profile['source_video_sha256']='other'
        with self.assertRaises(ValueError):frozen_check(self.root,self.profile)
    def test_path_traversal_rejected(self):
        self.profile['validation_plan']['plan_id']='../../escape'
        with self.assertRaises(ValueError):frozen_check(self.root,self.profile)

if __name__=='__main__':unittest.main()
