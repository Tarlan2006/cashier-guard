import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from run_object_event_trial import bind_model,validate_sam_source

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def setup(root):
    plan=root/'local/check';model=plan/'frozen-model';model.mkdir(parents=True);(root/'scene_mvp').mkdir();feature=root/'scene_mvp/object_event_model.py';feature.write_text('frozen feature code');sam=root/'run_sam2_object_trial.py';sam.write_text('frozen SAM code');weights=model/'object-event-model.npz';weights.write_bytes(b'fake weights for binding test');meta={'schema_version':'object-event-model/1','model_sha256':sha(weights)};(model/'model-metadata.local.json').write_text(json.dumps(meta));data={'source_session':'s','source_video_sha256':'v','model_sha256':sha(weights),'feature_code_sha256':sha(feature),'sam_code_sha256':sha(sam)};path=plan/'plan.local.json';path.write_text(json.dumps(data));profile={'source_session':'s','source_video_sha256':'v','object_event_check':{'plan_id':'check','sha256':sha(path)}};return profile,model

class TrialTests(unittest.TestCase):
    def test_frozen_model_selected_without_current_model_pointer(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);profile,expected=setup(root)
            with patch('run_object_event_trial.ROOT',root):actual,_=bind_model(profile)
            self.assertEqual(actual,expected.resolve())
    def test_tampered_plan_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);profile,_=setup(root);profile['object_event_check']['sha256']='wrong'
            with patch('run_object_event_trial.ROOT',root),self.assertRaises(ValueError):bind_model(profile)
    def test_feature_code_changes_after_freeze_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);profile,_=setup(root);(root/'scene_mvp/object_event_model.py').write_text('changed')
            with patch('run_object_event_trial.ROOT',root),self.assertRaises(ValueError):bind_model(profile)
    def test_other_video_cannot_use_check_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);profile,_=setup(root);profile['source_video_sha256']='other'
            with patch('run_object_event_trial.ROOT',root),self.assertRaises(ValueError):bind_model(profile)
    def test_sam_calibration_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'calibration.local.json').write_text(json.dumps({'source_video_sha256':'a'}))
            with self.assertRaises(ValueError):validate_sam_source(p,{'source_video_sha256':'b'})

if __name__=='__main__':unittest.main()
