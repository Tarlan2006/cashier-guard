"""Do not promote a faster or selectively available but less stable method."""
import unittest
from eval.distance_gate import promotion_gate


def cases(table=.9,machine=.7,extra=1):
    return [dict(video=n,variant='mirror',status='ok',extra_sec=extra,
                 stability=dict(role=1,near_table=table,near_machine=machine)) for n in (0,1)]


class DistanceGateTests(unittest.TestCase):
    def test_machine_improvement_cannot_hide_table_regression(self):
        gate=promotion_gate(cases(),cases(table=.8,machine=.95))
        self.assertFalse(gate['passed'])
        self.assertIn('near_table_less_stable',gate['reasons'])

    def test_missing_hard_case_cannot_improve_coverage(self):
        gate=promotion_gate(cases(),cases(machine=.9)[:1])
        self.assertFalse(gate['passed'])
        self.assertIn('coverage_or_availability_changed',gate['reasons'])

    def test_improved_but_too_slow_is_rejected(self):
        self.assertFalse(promotion_gate(cases(),cases(machine=.9,extra=5.01))['passed'])

    def test_unchanged_is_not_a_reason_to_switch(self):
        self.assertFalse(promotion_gate(cases(),cases())['passed'])

    def test_noninferior_improved_and_fast_candidate_passes(self):
        self.assertTrue(promotion_gate(cases(),cases(machine=.9,extra=5))['passed'])


if __name__=='__main__':unittest.main()
