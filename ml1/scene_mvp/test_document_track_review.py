import unittest
from import_document_track_review import validate,actions_from_review,apply_clarification


class TrackReviewTests(unittest.TestCase):
    def setUp(self):
        self.protocol={'source_session':'s','source_video_sha256':'v'}
        self.review={'schema_version':1,'review_kind':'reviewed_document_track_review','review_session':'r',
            'source_session':'s','source_video_sha256':'v','protocol_sha256':'p','confirmed':True,
            'human_mask_review':'incorrect_on_reviewed_frames','human_observed_motion':None,
            'approved_for_rule_engine':False,'identity_verification_established':False,'review_scope':'user_reviewed_sampled_clip_frames_only'}

    def test_negative_feedback_accepted_without_motion_guess(self):
        validate(self.review,self.protocol,'r','p')

    def test_draft_and_identity_verdict_rejected(self):
        self.review['confirmed']=False
        with self.assertRaises(ValueError):validate(self.review,self.protocol,'r','p')
        self.review['confirmed']=True;self.review['identity_verification_established']=True
        with self.assertRaises(ValueError):validate(self.review,self.protocol,'r','p')

    def test_foreign_source_rejected(self):
        self.review['source_video_sha256']='other'
        with self.assertRaises(ValueError):validate(self.review,self.protocol,'r','p')

    def test_legacy_single_action_remains_readable(self):
        self.review['human_observed_motion']='lifted_or_held_in_hand'
        self.assertEqual(actions_from_review(self.review),['lifted_or_held_in_hand'])

    def test_multiple_compatible_actions_preserved(self):
        self.review['schema_version']=2
        self.review['human_observed_actions']=['lifted_or_held_in_hand','passed_between_people']
        validate(self.review,self.protocol,'r','p')
        self.assertEqual(actions_from_review(self.review),self.review['human_observed_actions'])

    def test_chat_clarification_is_source_bound_and_does_not_guess_direction(self):
        accepted={**self.review,'human_observed_actions':['lifted_or_held_in_hand']}
        clarification={'original_review_sha256':'export','source_video_sha256':'v',
            'human_observed_actions':['lifted_or_held_in_hand','passed_between_people'],'human_claimed_object_kind':'identity_document',
            'evidence':{'kind':'explicit_user_chat_statement','quote':'Документ передают и держат в руках'}}
        result=apply_clarification(accepted,clarification,'export')
        self.assertEqual(len(result['human_observed_actions']),2)
        self.assertEqual(result['transfer_direction'],'unknown_not_annotated')
        self.assertFalse(result['frame_accurate_action_intervals'])
        self.assertFalse(result['automatic_identity_document_recognition_established'])
        clarification['original_review_sha256']='other'
        with self.assertRaises(ValueError):apply_clarification(accepted,clarification,'export')


if __name__=='__main__':unittest.main()
