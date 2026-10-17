"""Hysteresis and geometric repair contracts, without video/model weights."""

import copy
import unittest

from backend.pipeline.perception.scene_tracks import apply_hysteresis, repair_tracks


def p(identifier, box, confidence=0.9):
    return {"id": identifier, "bbox": box, "confidence": confidence, "observed": True}


class SceneTrackTests(unittest.TestCase):
    def test_nested_duplicate_is_suppressed_but_observation_is_auditable(self):
        facts = {
            "frames": [
                {
                    "timestamp_sec": i * 0.5,
                    "persons": [p(1, [0.2, 0.2, 0.5, 0.7])]
                    + ([p(2, [0.3, 0.3, 0.4, 0.6], 0.5)] if i == 0 else []),
                }
                for i in range(8)
            ]
        }
        repair_tracks(facts)
        self.assertEqual(len(facts["frames"][0]["persons"]), 1)
        self.assertEqual(
            facts["frames"][0]["suppressed_persons"][0]["duplicate_of_id"], 1
        )
        self.assertEqual(facts["track_repair"]["suppressed_boxes"], 1)

    def test_continuation_keeps_source_ids_without_inventing_missing_boxes(self):
        facts = {
            "frames": [
                {
                    "timestamp_sec": i * 0.5,
                    "persons": (
                        [p(1 if i < 3 else 3, [0.2, 0.2, 0.4, 0.5])]
                        if i < 3 or i > 6
                        else []
                    ),
                }
                for i in range(12)
            ]
        }
        # The former 2.5s geometry-only join is deliberately forbidden now.
        for frame in facts["frames"]:
            for person in frame["persons"]:
                person["clothing_histogram"] = [1.0, 0.0]
        repair_tracks(facts, max_gap_sec=3.0, require_appearance=False)
        self.assertTrue(
            all(p["id"] == 1 for f in facts["frames"] for p in f["persons"])
        )
        self.assertEqual(facts["frames"][4]["persons"], [])
        self.assertEqual(facts["frames"][-1]["persons"][0]["source_track_ids"], [1, 3])

    def test_two_simultaneously_visible_people_are_never_joined(self):
        facts = {
            "frames": [
                {
                    "timestamp_sec": i * 0.5,
                    "persons": [
                        p(1, [0.2, 0.2, 0.35, 0.6]),
                        p(2, [0.36, 0.2, 0.51, 0.6]),
                    ],
                }
                for i in range(8)
            ]
        }
        repair_tracks(facts)
        self.assertTrue(all(len(f["persons"]) == 2 for f in facts["frames"]))
        self.assertEqual(facts["track_repair"]["joins"], [])

    def test_two_second_confirmation_is_causal_and_not_two_detector_hits(self):
        facts = {
            "frames": [
                {"timestamp_sec": i * 0.5, "persons": [p(1, [0.2, 0.2, 0.4, 0.5])]}
                for i in range(8)
            ]
        }
        apply_hysteresis(facts)
        self.assertEqual(
            [f["persons"][0]["counted"] for f in facts["frames"]],
            [False] * 4 + [True] * 4,
        )
        self.assertFalse(facts["frames"][1]["persons"][0]["event_eligible"])

    def test_short_track_is_retained_and_never_event_eligible(self):
        facts = {
            "frames": [
                {
                    "timestamp_sec": i * 0.5,
                    "persons": [p(1, [0.2, 0.2, 0.4, 0.5])] if i in [4, 5] else [],
                }
                for i in range(10)
            ]
        }
        apply_hysteresis(facts)
        rows = [p for f in facts["frames"] for p in f["persons"]]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(not p["event_eligible"] for p in rows))

    def test_short_late_track_stays_uncertain_and_confirmed_when_old_enough(self):
        facts = {
            "frames": [
                {
                    "timestamp_sec": i * 0.5,
                    "persons": [p(4, [0.2, 0.2, 0.4, 0.5])] if i >= 4 else [],
                }
                for i in range(12)
            ]
        }
        apply_hysteresis(facts)
        self.assertTrue(facts["frames"][-1]["persons"][0]["uncertain"])
        self.assertEqual(facts["frames"][-1]["persons"][0]["status"], "uncertain")
        self.assertFalse(facts["frames"][-1]["persons"][0]["event_eligible"])

    def test_reflections_are_not_counted_even_when_old(self):
        facts = {
            "frames": [
                {
                    "timestamp_sec": i * 0.5,
                    "persons": [dict(p(1, [0.2, 0.2, 0.4, 0.5]), is_reflection=True)],
                }
                for i in range(10)
            ]
        }
        apply_hysteresis(facts)
        self.assertTrue(all(not f["persons"][0]["counted"] for f in facts["frames"]))

    def test_hysteresis_resets_after_long_detection_gap(self):
        facts = {
            "frames": [
                {"timestamp_sec": t, "persons": [p(1, [0.2, 0.2, 0.4, 0.5])]}
                for t in [0, 0.5, 1, 1.5, 2, 4, 4.5, 5]
            ]
        }
        apply_hysteresis(facts)
        self.assertTrue(facts["frames"][4]["persons"][0]["counted"])
        self.assertTrue(
            all(not f["persons"][0]["counted"] for f in facts["frames"][5:])
        )

    def test_repeated_source_frame_does_not_confirm_a_track(self):
        facts = {
            "frames": [
                {
                    "timestamp_sec": i * 0.5,
                    "actual_timestamp_sec": 1.0,
                    "persons": [p(1, [0.2, 0.2, 0.4, 0.5])],
                }
                for i in range(10)
            ]
        }
        apply_hysteresis(facts)
        self.assertTrue(
            all(not f["persons"][0]["event_eligible"] for f in facts["frames"])
        )


if __name__ == "__main__":
    unittest.main()
