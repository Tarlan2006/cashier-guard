from __future__ import annotations

import copy
import math
import unittest

from backend.pipeline.perception.reflections import (
    ReflectionConfig,
    annotate_reflections,
)


def example_facts(
    *, small_confidence: float = 0.60, mirrored_motion: bool = False
) -> dict:
    frames = []
    for index in range(24):
        # Sufficient movement in both dimensions, without an axis-aligned mirror.
        angle = index * 0.28
        dx, dy = 0.055 * math.cos(angle), 0.030 * math.sin(angle)
        reflection_dx, reflection_dy = (
            (-dx * 0.5, dy * 0.5) if mirrored_motion else (0.0, 0.0)
        )
        frames.append(
            {
                "timestamp_sec": index * 0.5,
                "persons": [
                    {
                        "id": 1,
                        "confidence": 0.88,
                        "bbox": [0.25 + dx, 0.30 + dy, 0.45 + dx, 0.60 + dy],
                    },
                    {
                        "id": 2,
                        "confidence": small_confidence,
                        "bbox": [
                            0.65 + reflection_dx,
                            0.40 + reflection_dy,
                            0.75 + reflection_dx,
                            0.55 + reflection_dy,
                        ],
                    },
                ],
            }
        )
    return {"video": {"width": 800, "height": 600}, "frames": frames}


class ReflectionTests(unittest.TestCase):
    def test_size_alone_does_not_exclude_shorter_real_person(self) -> None:
        facts = annotate_reflections(example_facts(small_confidence=0.84))
        self.assertFalse(
            any(
                person["is_reflection"]
                for row in facts["frames"]
                for person in row["persons"]
            )
        )

    def test_low_confidence_alone_does_not_exclude_real_person(self) -> None:
        facts = example_facts()
        for row in facts["frames"]:
            row["persons"][1]["bbox"] = [0.60, 0.30, 0.80, 0.60]
        annotate_reflections(facts)
        self.assertFalse(facts["frames"][0]["persons"][1]["is_reflection"])

    def test_combined_track_evidence_flags_but_preserves_every_observation(
        self,
    ) -> None:
        facts = example_facts()
        original = copy.deepcopy(facts)
        returned = annotate_reflections(facts)
        self.assertIs(returned, facts)
        self.assertEqual(len(facts["frames"]), len(original["frames"]))
        for after, before in zip(facts["frames"], original["frames"]):
            self.assertEqual(len(after["persons"]), len(before["persons"]))
            self.assertFalse(after["persons"][0]["is_reflection"])
            self.assertTrue(after["persons"][1]["is_reflection"])
            self.assertEqual(after["persons"][1]["bbox"], before["persons"][1]["bbox"])
            self.assertEqual(after["persons"][1]["reflection_evidence"]["anchor_id"], 1)
        self.assertIn("heuristic", facts["reflection_filter"]["limitation"].lower())

    def test_ambiguous_low_confidence_small_person_is_not_claimed_mirrored(
        self,
    ) -> None:
        facts = annotate_reflections(example_facts(small_confidence=0.75))
        self.assertFalse(facts["frames"][0]["persons"][1]["is_reflection"])
        self.assertFalse(
            facts["reflection_tracks"][1]["evidence"]["motion"]["supports_reflection"]
        )

    def test_mirrored_motion_is_reported_when_nonstationary_and_two_dimensional(
        self,
    ) -> None:
        facts = annotate_reflections(example_facts(mirrored_motion=True))
        person = facts["frames"][0]["persons"][1]
        self.assertTrue(person["is_reflection"])
        self.assertTrue(person["reflection_evidence"]["motion"]["supports_reflection"])
        self.assertIn("mirrored_motion", person["reflection_reason"])

    def test_mirrored_motion_can_support_reflection_above_low_score_gate(self) -> None:
        facts = annotate_reflections(
            example_facts(small_confidence=0.80, mirrored_motion=True)
        )
        self.assertTrue(facts["frames"][0]["persons"][1]["is_reflection"])
        self.assertTrue(
            facts["frames"][0]["persons"][1]["reflection_evidence"]["motion"][
                "supports_reflection"
            ]
        )

    def test_global_mirror_rotation_and_resolution_do_not_change_flags(self) -> None:
        original = annotate_reflections(example_facts(mirrored_motion=True))
        transformed = example_facts(mirrored_motion=True)
        # 90-degree rotation + horizontal reflection, with swapped dimensions.
        transformed["video"] = {"width": 1200, "height": 1600}
        for row in transformed["frames"]:
            for person in row["persons"]:
                x1, y1, x2, y2 = person["bbox"]
                person["bbox"] = [y1, x1, y2, x2]
        annotate_reflections(transformed)
        self.assertEqual(
            [row["is_reflection"] for row in original["reflection_tracks"]],
            [row["is_reflection"] for row in transformed["reflection_tracks"]],
        )
        self.assertTrue(
            transformed["reflection_tracks"][1]["evidence"]["motion"][
                "supports_reflection"
            ]
        )

    def test_short_or_nonoverlapping_tracks_stay_ambiguous(self) -> None:
        facts = example_facts()
        for row in facts["frames"][2:]:
            row["persons"] = row["persons"][:1]
        annotate_reflections(facts)
        self.assertFalse(facts["reflection_tracks"][1]["is_reflection"])
        facts = example_facts()
        for index, row in enumerate(facts["frames"]):
            row["persons"] = row["persons"][:1] if index < 12 else row["persons"][1:]
        annotate_reflections(facts)
        self.assertFalse(
            any(row["is_reflection"] for row in facts["reflection_tracks"])
        )

    def test_config_empty_video_and_repeat_application(self) -> None:
        with self.assertRaises(ValueError):
            ReflectionConfig(max_relative_scale=0)
        empty = annotate_reflections(
            {"video": {"width": 100, "height": 100}, "frames": []}
        )
        self.assertEqual(empty["reflection_tracks"], [])
        facts = annotate_reflections(example_facts())
        expected = copy.deepcopy(facts)
        annotate_reflections(facts)
        self.assertEqual(facts, expected)


if __name__ == "__main__":
    unittest.main()
