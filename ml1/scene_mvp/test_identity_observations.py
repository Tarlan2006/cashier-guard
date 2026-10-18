import copy,unittest
from scene_mvp.identity_observations import validate_identity_review

def fixture(observation='not_observed'):
    case={'source_session':'s','source_video_sha256':'v','confirmed':True,'complete_operation_visible':'yes',
          'physical_document_observation':observation,'presentation_window_sec':[1,2] if observation=='presentation_seen' else None,
          'document_seed':None,'possible_device_use':'unknown','identity_verification_status':'unknown_no_bank_record',
          'legal_violation_label':None,'frame_accurate_boundaries':False,'review_scope':'human_review_of_native_video_and_optional_sampled_frame_box'}
    review={'schema_version':'identity-observation-review/1','review_session':'review','protocol_sha256':'p','confirmed':True,
            'automatic_legal_verdict':False,'face_recognition_used':False,'cases':[case]}
    protocol={'review_session':'review','cases':[{'session_id':'s','sha256':'v','duration_sec':3,'operation_context':'cash_deposit'}]}
    return review,protocol,{'s':[{'timestamp_sec':1}]}

class IdentityTests(unittest.TestCase):
    def test_absence_of_visible_document_is_not_failure_or_legal_verdict(self):
        r,p,f=fixture();x=validate_identity_review(r,p,'p',f)[0]
        self.assertFalse(x['automatic_identity_failure_detected']);self.assertIsNone(x['legal_violation_label']);self.assertEqual(x['identity_verification_status'],'unknown_no_bank_record');self.assertTrue(x['external_verification_record_required'])
    def test_digital_device_use_does_not_confirm_verification(self):
        r,p,f=fixture();r['cases'][0]['possible_device_use']='possible_device_use';self.assertEqual(validate_identity_review(r,p,'p',f)[0]['identity_verification_status'],'unknown_no_bank_record')
    def test_already_present_is_not_a_presentation_event(self):
        r,p,f=fixture('already_present');self.assertIsNone(validate_identity_review(r,p,'p',f)[0]['presentation_window_sec'])
    def test_wrong_video_rejected(self):
        r,p,f=fixture();r['cases'][0]['source_video_sha256']='other'
        with self.assertRaises(ValueError):validate_identity_review(r,p,'p',f)
    def test_draft_rejected(self):
        r,p,f=fixture();r['confirmed']=False
        with self.assertRaises(ValueError):validate_identity_review(r,p,'p',f)
    def test_claimed_verified_identity_rejected(self):
        r,p,f=fixture();r['cases'][0]['identity_verification_status']='verified'
        with self.assertRaises(ValueError):validate_identity_review(r,p,'p',f)
    def test_presentation_window_outside_video_rejected(self):
        r,p,f=fixture('presentation_seen');r['cases'][0]['presentation_window_sec']=[1,4]
        with self.assertRaises(ValueError):validate_identity_review(r,p,'p',f)
    def test_seed_must_match_source_frame(self):
        r,p,f=fixture('presentation_seen');r['cases'][0]['document_seed']={'bbox':[.1,.2,.2,.3],'timestamp_sec':2,'source':'human_box_on_visible_object','object_kind':'card_like_unknown'}
        with self.assertRaises(ValueError):validate_identity_review(r,p,'p',f)

if __name__=='__main__':unittest.main()
