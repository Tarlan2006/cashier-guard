import copy,unittest
from scene_mvp.cabinet_model import validate_fixture_data

def fixture():
    profile={'schema_version':1,'profile_kind':'fixture_only','fixture_kind':'cash_storage_cabinet','confirmed':True,'source_video_sha256':'a'*64,'source_session':'s','zones':{'safe_zone':[.1,.1,.9,.9]},'roles':{},'fixture_frame_labels':[{'timestamp_sec':0.,'state':'closed','source':'human_frame_label'},{'timestamp_sec':.5,'state':'unknown','source':'human_frame_label'}]}
    session={'target_kind':'cash_storage_cabinet','session_id':'s','source_video_sha256':'a'*64,'frames':[{'timestamp_sec':0.},{'timestamp_sec':.5}]}
    return profile,session

class Tests(unittest.TestCase):
    def test_unknown_is_explicit_not_closed(self):
        p,s=fixture();self.assertEqual(validate_fixture_data(p,s)[.5],'unknown')
    def test_missing_label(self):
        p,s=fixture();p['fixture_frame_labels'].pop()
        with self.assertRaises(ValueError):validate_fixture_data(p,s)
    def test_duplicate_label(self):
        p,s=fixture();p['fixture_frame_labels'].append(copy.deepcopy(p['fixture_frame_labels'][0]))
        with self.assertRaises(ValueError):validate_fixture_data(p,s)
    def test_other_video(self):
        p,s=fixture();s['source_video_sha256']='b'*64
        with self.assertRaises(ValueError):validate_fixture_data(p,s)
    def test_other_session(self):
        p,s=fixture();s['session_id']='other'
        with self.assertRaises(ValueError):validate_fixture_data(p,s)
    def test_entrance_door_target_rejected(self):
        p,s=fixture();s['target_kind']='entrance_door'
        with self.assertRaises(ValueError):validate_fixture_data(p,s)
    def test_model_label_not_human_ground_truth(self):
        p,s=fixture();p['fixture_frame_labels'][0]['source']='experimental_door_classifier'
        with self.assertRaises(ValueError):validate_fixture_data(p,s)
if __name__=='__main__':unittest.main()
