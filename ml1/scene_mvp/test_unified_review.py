import copy,math,unittest
from scene_mvp.unified_review import assemble,event


class UnifiedReviewTests(unittest.TestCase):
    def setUp(self):
        self.sha='a'*64;self.catalog={'source_pdf_sha256':'b'*64,'records':[
            {'filename':'X-4.mov','video_sha256':self.sha,'annotation_type':'source only'},
            {'filename':'X-47.mov','video_sha256':self.sha,'annotation_type':'second source moment'}]}
        self.item=event(self.sha,'human','cash_handover',[3,4],'Observed by human')
        self.channel={'source_video_sha256':self.sha,'kind':'human_cash_transfer','events':[self.item]}

    def test_duplicate_videos_and_repeated_event_are_not_multiplied(self):
        result=assemble(self.catalog,[self.channel,self.channel])
        self.assertEqual(len(result['cases']),1)
        self.assertEqual(len(result['cases'][0]['reference_annotations']),2)
        self.assertEqual(len(result['cases'][0]['events']),1)

    def test_empty_events_are_not_a_normal_verdict(self):
        case=assemble(self.catalog,[])['cases'][0]
        self.assertEqual(case['analysis_status'],'not_analyzed')
        self.assertIsNone(case['verdict']);self.assertFalse(case['analysis_complete'])
        case=assemble(self.catalog,[dict(self.channel,events=[])])['cases'][0]
        self.assertEqual(case['analysis_status'],'partial');self.assertIsNone(case['verdict'])

    def test_pdf_changes_do_not_change_predictions(self):
        other=copy.deepcopy(self.catalog);other['records'][0]['annotation_type']='completely different'
        self.assertEqual(assemble(self.catalog,[self.channel])['cases'][0]['events'],
                         assemble(other,[self.channel])['cases'][0]['events'])

    def test_foreign_video_or_event_rejected(self):
        with self.assertRaises(ValueError):assemble(self.catalog,[dict(self.channel,source_video_sha256='c'*64)])
        changed=copy.deepcopy(self.channel);changed['events'][0]['source_video_sha256']='c'*64
        with self.assertRaises(ValueError):assemble(self.catalog,[changed])

    def test_legal_verdict_rejected(self):
        changed=copy.deepcopy(self.channel);changed['events'][0]['legal_violation_established']=True
        with self.assertRaises(ValueError):assemble(self.catalog,[changed])

    def test_bad_time_and_missing_sha_rejected(self):
        for span in [[0,math.inf],[-1,2],[3,2],[True,2]]:
            with self.assertRaises(ValueError):event(self.sha,'model','x',span,'description')
        with self.assertRaises(ValueError):event('X-4','model','x',[1,2],'description')


if __name__=='__main__':unittest.main()
