import copy, hashlib, json, tempfile, unittest
from pathlib import Path
from import_document_search_review import validate


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.trial = Path(self.temp.name)
        protocol = self.trial/'protocol.local.json'; protocol.write_text('{}')
        self.card = {'key':'0','source_session':'scene-test','source_video_sha256':'a'*64,'frame_sha256':'b'*64,
                     'timestamp_sec':1.,'source_name':'synthetic','proposals':[{'bbox':[.1,.2,.3,.4],'reference_similarity':.5}]}
        manifest = self.trial/'candidate-manifest.local.json'; manifest.write_text(json.dumps({'cards':[self.card]}))
        self.review = {'schema_version':'document-search-review/1','review_session':self.trial.name,
          'protocol_sha256':hashlib.sha256(protocol.read_bytes()).hexdigest(),'candidate_manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),
          'confirmed':True,'approved_for_rule_engine':False,'absence_detection_validated':False,
          'review_scope':'human_review_of_automatically_ranked_sampled_frame_candidates','reviews':[{**self.card,'human_selection':'none'}]}

    def tearDown(self): self.temp.cleanup()

    def test_none_is_not_absence(self):
        row = validate(self.review,self.trial)[0]
        self.assertIsNone(row['document_candidate_box']);self.assertIsNone(row['legal_violation_label'])
        self.assertIn('not_whole_frame_or_video_absence',row['none_means'])

    def test_source_geometry_tampering_rejected(self):
        review = copy.deepcopy(self.review);review['reviews'][0]['proposals'][0]['bbox'][0] = .5
        with self.assertRaises(ValueError): validate(review,self.trial)

    def test_draft_not_accepted(self):
        self.review['confirmed'] = False
        with self.assertRaises(ValueError): validate(self.review,self.trial)

    def test_selected_box_preserved(self):
        self.review['reviews'][0]['human_selection'] = 'A'
        self.assertEqual(validate(self.review,self.trial)[0]['document_candidate_box'],[.1,.2,.3,.4])


if __name__ == '__main__': unittest.main()
