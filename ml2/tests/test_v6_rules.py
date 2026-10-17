import unittest
from backend.pipeline.track_rules import evaluate_track_rules


def scene(*, uncertain=False, gap=False):
    rows = []
    for i in range(9):
        t = i * (2.0 if gap else 0.5)
        rows.append(
            dict(
                timestamp_sec=t,
                persons=[
                    dict(
                        id=n,
                        bbox=[0.2, 0.2, 0.3, 0.4],
                        role="client_candidate" if n > 1 else "cashier_candidate",
                        counted=True,
                        confidence=0.9,
                        near_table=True,
                        uncertain=uncertain and n == 3,
                    )
                    for n in (1, 2, 3)
                ],
            )
        )
    return dict(
        video=dict(width=100, height=100),
        roles=dict(cashier_ids=[1]),
        frames=rows,
        fixtures=[],
        sample_interval_sec=0.5,
    )


class TemporalRuleTests(unittest.TestCase):
    def test_overlap_onset_is_first_observation_not_confirmation(self):
        events = evaluate_track_rules(scene())
        event = next(e for e in events if e["rule_id"] == "two_clients_three_seconds")
        self.assertEqual(event["first_seen"], 0)
        self.assertEqual(event["confirmed_at"], 3)

    def test_uncertain_third_person_cannot_trigger_overlap(self):
        events = evaluate_track_rules(scene(uncertain=True))
        self.assertFalse(
            any(
                e["rule_id"] in {"three_people_at_table", "two_clients_three_seconds"}
                for e in events
            )
        )

    def test_unobserved_gaps_do_not_prove_continuous_overlap(self):
        events = evaluate_track_rules(scene(gap=True))
        self.assertFalse(
            any(
                e["rule_id"] in {"three_people_at_table", "two_clients_three_seconds"}
                for e in events
            )
        )
