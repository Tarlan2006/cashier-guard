import unittest
import numpy as np
from scene_mvp.document_filter import candidate_examples, sample_weights, grouped_folds, fit, scores, decision


def row(video,frame,label):
    return {'split_group':video,'frame_group':video+':'+frame,'label':label}


class FilterTests(unittest.TestCase):
    def test_other_boxes_next_to_positive_not_invented_as_negative(self):
        case={'source_session':'s','source_video_sha256':'v','frame_sha256':'f','timestamp_sec':1,'key':'0','human_selection':'B','proposals':[{'bbox':[0,0,.1,.1]}]*3}
        rows=candidate_examples({'confirmed':True,'approved_for_rule_engine':False,'reviews':[case]})
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['label'],1)

    def test_none_labels_only_the_displayed_boxes(self):
        case={'source_session':'s','source_video_sha256':'v','frame_sha256':'f','timestamp_sec':1,'key':'0','human_selection':'none','proposals':[{'bbox':[0,0,.1,.1]}]*3}
        rows=candidate_examples({'confirmed':True,'approved_for_rule_engine':False,'reviews':[case]})
        self.assertEqual(len(rows),3);self.assertTrue(all(r['label_kind']=='rejected_document_candidate_box' for r in rows))

    def test_weights_do_not_multiply_near_duplicate_views(self):
        rows=[row('v1','f1',1),row('v1','f2',0)]
        original=sample_weights(rows)
        duplicated=sample_weights(rows+[row('v1','f2',0)]*5)
        self.assertAlmostEqual(original[0],duplicated[0]);self.assertAlmostEqual(original[1],sum(duplicated[1:]))

    def test_video_folds_are_disjoint(self):
        rows=[row(v,'f'+str(y),y) for v in ['a','b','c'] for y in [0,1]]
        for group,train,test in grouped_folds(rows):
            self.assertTrue(all(rows[i]['split_group']!=group for i in train))
            self.assertTrue(all(rows[i]['split_group']==group for i in test))

    def test_single_class_and_nonfinite_features_rejected(self):
        with self.assertRaises(ValueError): fit([[0],[1]],[row('a','a',1),row('a','b',1)])
        with self.assertRaises(ValueError): fit([[0],[np.nan]],[row('a','a',0),row('a','b',1)])

    def test_separable_synthetic_candidate_head(self):
        rows=[row('a',str(i),int(i>1)) for i in range(4)]
        model=fit([[-1.],[-.8],[.8],[1.]],rows)
        self.assertEqual([decision(s) for s in scores(model,[[-.9],[.9]])],['reject_candidate','accept_candidate'])


if __name__ == '__main__': unittest.main()
