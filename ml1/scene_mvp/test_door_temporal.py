import unittest
from scene_mvp.door_temporal import confirm, episode_metrics


def rows(states, times=None):
    return [{'timestamp_sec': t, 'predicted': s} for t, s in zip(times or [i*.5 for i in range(len(states))], states)]


class TemporalTests(unittest.TestCase):
    def test_confirmation_has_delay_and_no_backdating(self):
        r=confirm(rows(['open','open','open']))
        self.assertEqual([x['predicted'] for x in r], ['unknown','open','open'])
        self.assertEqual(r[1]['evidence_start_sec'],0)

    def test_isolated_open_never_becomes_event(self):
        r=confirm(rows(['closed','closed','open','closed','closed']))
        self.assertNotIn('open',[x['predicted'] for x in r])
        self.assertEqual(r[2]['predicted'],'unknown')

    def test_unknown_resets_and_never_carries_open(self):
        r=confirm(rows(['open','open','unknown','open','open']))
        self.assertEqual([x['predicted'] for x in r],['unknown','open','unknown','unknown','open'])

    def test_gap_requires_reconfirmation(self):
        r=confirm(rows(['open']*4,[0,.5,2,2.5]))
        self.assertEqual([x['predicted'] for x in r],['unknown','open','unknown','open'])

    def test_dense_samples_need_duration(self):
        r=confirm(rows(['open']*4,[0,.1,.2,.5]))
        self.assertEqual([x['predicted'] for x in r],['unknown']*3+['open'])

    def test_transition_is_not_stale_closed(self):
        r=confirm(rows(['closed','closed','open','open']))
        self.assertEqual([x['predicted'] for x in r],['unknown','closed','unknown','open'])

    def test_future_cannot_change_past(self):
        x=rows(['closed','closed','open','open','unknown'])
        self.assertEqual(confirm(x[:3]),confirm(x)[:3])

    def test_invalid_order_and_state(self):
        for x in (rows(['open','open'],[0,0]),rows(['open'],[-1]),rows(['open'],[float('nan')]),rows(['bad'])):
            with self.assertRaises(ValueError):confirm(x)

    def test_episode_fragments_not_hidden(self):
        x=rows(['open']*6)
        truth=[dict(r,expected='open') for r in x]
        pred=confirm(rows(['open','open','unknown','open','open','open']))
        m=episode_metrics(truth,pred)
        self.assertEqual(m['human_open_runs'],1)
        self.assertEqual(m['predicted_open_runs'],2)
        self.assertEqual(m['human_runs'][0]['overlapping_prediction_runs'],2)

    def test_ground_truth_not_consumed(self):
        x=rows(['open','open'])
        self.assertEqual(confirm(x),confirm([dict(r,expected='closed') for r in x]))

if __name__=='__main__':unittest.main()
