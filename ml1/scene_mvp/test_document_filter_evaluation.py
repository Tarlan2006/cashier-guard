import unittest
from evaluate_document_filter_check import evaluate_rows


def prop(value):return {'candidate_head_score':value,'selection_state':'rejected_control' if value<=.35 else 'retained_candidate'}


class EvaluationTests(unittest.TestCase):
    def test_other_boxes_on_positive_frame_are_not_invented_negatives(self):
        result=evaluate_rows([{'key':'0','timestamp_sec':1,'human_selection':'A','proposals':[prop(.5),prop(.1),prop(.8)]}],.35)
        self.assertEqual(result['correct_boxes_retained'],1)
        self.assertEqual(result['incorrect_reviewed_boxes'],0)
        self.assertFalse(result['document_presentation_validated'])

    def test_rejected_correct_box_and_remaining_false_candidates_counted(self):
        result=evaluate_rows([{'key':'0','timestamp_sec':1,'human_selection':'A','proposals':[prop(.2)]},
                              {'key':'1','timestamp_sec':2,'human_selection':'none','proposals':[prop(.1),prop(.5)]}],.35)
        self.assertEqual(result['correct_boxes_rejected'],1)
        self.assertEqual(result['incorrect_boxes_rejected'],1)
        self.assertEqual(result['incorrect_boxes_retained'],1)
        self.assertEqual(result['negative_reviewed_frames_with_remaining_incorrect_box'],1)
        self.assertFalse(result['document_absence_validated'])

    def test_inconsistent_saved_state_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_rows([{'key':'0','timestamp_sec':1,'human_selection':'none','proposals':[{'candidate_head_score':.1,'selection_state':'retained_candidate'}]}],.35)


if __name__=='__main__':unittest.main()
