import unittest
from scene_mvp.document_temporal import associate


def proposal(index=0,box=None):return {'bbox':box or [.3,.4,.35,.42],'appearance':[1.,0.], 'proposal_index':index,'selection_state':'retained_candidate'}


class TemporalTests(unittest.TestCase):
    def test_adjacent_same_candidate_forms_track(self):
        result=associate([{'timestamp_sec':t,'proposals':[proposal()]} for t in [0,.5,1.]])
        self.assertEqual(len(result['tracks']),1);self.assertEqual(result['tracks'][0]['priority'],'repeated_candidate')

    def test_missing_sample_not_bridged_and_singletons_not_deleted(self):
        result=associate([{'timestamp_sec':0,'proposals':[proposal()]},{'timestamp_sec':.5,'proposals':[]},{'timestamp_sec':1,'proposals':[proposal()]}])
        self.assertEqual(len(result['tracks']),2);self.assertFalse(result['absence_detection_validated'])

    def test_one_track_cannot_take_two_candidates_in_same_frame(self):
        result=associate([{'timestamp_sec':0,'proposals':[proposal()]},{'timestamp_sec':.5,'proposals':[proposal(0),proposal(1)]}])
        ids=[p['track_id'] for p in result['timeline'][1]['candidate_tracks']]
        self.assertEqual(len(set(ids)),2)

    def test_far_candidate_gets_new_track(self):
        result=associate([{'timestamp_sec':0,'proposals':[proposal()]},{'timestamp_sec':.5,'proposals':[proposal(box=[.6,.4,.65,.42])]}])
        self.assertEqual(len(result['tracks']),2)


if __name__=='__main__':unittest.main()
