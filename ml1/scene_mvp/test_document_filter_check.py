import unittest
from run_document_filter_check import select_review


class CheckSelectionTests(unittest.TestCase):
    def test_rejected_controls_not_hidden_by_top_retained_frames(self):
        rows=[]
        for i in range(12):
            rows.append({'timestamp_sec':i*2.,'proposals':[{'reference_similarity':1-i*.01,'selection_state':'retained_candidate' if i<6 else 'rejected_control'}]})
        result=select_review(rows)
        self.assertEqual(sum(r['selection_reason']=='retained_candidate' for r in result),4)
        self.assertEqual(sum(r['selection_reason']=='rejected_control' for r in result),4)
        self.assertEqual(len({r['timestamp_sec'] for r in result}),8)

    def test_all_rejected_keeps_control_sample_for_review(self):
        rows=[{'timestamp_sec':i*2.,'proposals':[{'reference_similarity':.5,'selection_state':'rejected_control'}]} for i in range(6)]
        result=select_review(rows)
        self.assertEqual(len(result),4)
        self.assertTrue(all(r['selection_reason']=='rejected_control' for r in result))


if __name__=='__main__':unittest.main()
