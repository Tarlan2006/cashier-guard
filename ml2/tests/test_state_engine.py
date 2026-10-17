"""Check state conditions, onset timing and ambiguous-evidence suppression."""

from copy import deepcopy
import unittest

from backend.pipeline.state_engine import build_state_events, RULE_IDS


def timeline():
    return dict(
        video=dict(width=100, height=100),
        fixtures=[{"class": "counter_machine", "bbox": [0.4, 0.4, 0.5, 0.5]}],
        frames=[dict(timestamp_sec=i * 0.5, persons=[], objects=[]) for i in range(20)],
    )


def person(identifier, role="unknown", box=None, **kwargs):
    return dict(
        id=identifier,
        role=role,
        bbox=box or [0.2, 0.2, 0.3, 0.3],
        event_eligible=True,
        **kwargs
    )


class StateTests(unittest.TestCase):
    def test_new_person_onset_precedes_hysteresis_confirmation(self):
        facts = timeline()
        for i, f in enumerate(facts["frames"]):
            f["persons"] = [person(1, "cashier_candidate")]
            if i >= 6:
                f["persons"].append(person(2, event_eligible_override=False))
                f["persons"][-1]["event_eligible"] = i >= 10
        result = build_state_events(facts)
        event = next(e for e in result["events"] if e["rule_id"] == RULE_IDS[1])
        self.assertEqual(event["timecode_sec"], 3.0)
        self.assertEqual(event["confirmed_at"], 5.0)
        self.assertFalse(result["zones"]["door"]["known"])

    def test_disappearance_and_remaining_object_have_separate_confirmation(self):
        facts = timeline()
        for i, f in enumerate(facts["frames"]):
            f["persons"] = [person(1, "cashier_candidate")] if i < 6 else []
            f["objects"] = [
                {"class": "handbag", "object_id": "bag", "bbox": [0.45, 0.4, 0.5, 0.5]}
            ]
        result = build_state_events(facts)
        event = next(e for e in result["events"] if e["rule_id"] == RULE_IDS[0])
        self.assertEqual(event["timecode_sec"], 3.0)
        self.assertEqual(event["confirmed_at"], 5.0)

    def test_uncertain_or_reflection_cannot_be_second_person(self):
        for flag in ("uncertain", "is_reflection"):
            facts = timeline()
            for i, f in enumerate(facts["frames"]):
                f["persons"] = [person(1, "cashier_candidate")]
                if i >= 6:
                    f["persons"].append(person(2, **{flag: True}))
            self.assertEqual(build_state_events(facts)["events"], [])

    def test_leaving_desk_zone_does_not_require_leaving_camera_frame(self):
        facts = timeline()
        for i, f in enumerate(facts["frames"]):
            box = [0.4, 0.45, 0.5, 0.55] if i < 6 else [0.8, 0.8, 0.9, 0.9]
            f["persons"] = [person(1, "cashier_candidate", box=box)]
            f["objects"] = [
                {"class": "handbag", "object_id": "bag", "bbox": [0.45, 0.4, 0.5, 0.5]}
            ]
        result = build_state_events(facts)
        event = next(e for e in result["events"] if e["rule_id"] == RULE_IDS[0])
        self.assertEqual(event["first_seen"], 3.0)
        self.assertEqual(event["confirmed_at"], 5.0)
        self.assertTrue(all(f["persons"] for f in facts["frames"]))
        # A brief reach/movement followed by a return is not a confirmed exit.
        for f in facts["frames"][8:]:
            f["persons"][0]["bbox"] = [0.4, 0.45, 0.5, 0.55]
        self.assertEqual(build_state_events(facts)["events"], [])

    def test_concurrent_clients_require_roles_and_sustained_overlap(self):
        facts = timeline()
        for i, f in enumerate(facts["frames"]):
            f["persons"] = [
                person(1, "cashier_candidate"),
                person(2, "client_candidate"),
            ]
            if i >= 6:
                f["persons"].append(person(3, "client_candidate"))
        result = build_state_events(facts)
        event = next(e for e in result["events"] if e["rule_id"] == RULE_IDS[2])
        self.assertEqual(event["first_seen"], 3.0)
        for f in facts["frames"]:
            for p in f["persons"]:
                if p["id"] == 3:
                    p["role"] = "unknown"
        self.assertFalse(
            any(
                e["rule_id"] == RULE_IDS[2] for e in build_state_events(facts)["events"]
            )
        )


if __name__ == "__main__":
    unittest.main()
