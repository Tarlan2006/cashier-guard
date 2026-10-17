from __future__ import annotations

import math
import unittest

import numpy as np

from backend.pipeline.perception.roles import RoleAssigner, infer_roles
from backend.pipeline.perception.tracking import PersonTracker


def detection(x: float, y: float = 0.4, size: float = 0.1) -> dict:
    return {
        "class": "person",
        "bbox": [x - size / 2, y - size / 2, x + size / 2, y + size / 2],
        "confidence": 0.9,
    }


class TrackingTests(unittest.TestCase):
    def test_reordered_detections_keep_ids_and_misses_are_not_emitted(self) -> None:
        tracker = PersonTracker()
        first = tracker.update([detection(0.2), detection(0.8)], 0.0)
        second = tracker.update([detection(0.78), detection(0.22)], 0.5)
        self.assertEqual([person["id"] for person in first], [1, 2])
        self.assertAlmostEqual(second[0]["bbox"][0], 0.17)
        self.assertTrue(all(person["confirmed"] for person in second))
        self.assertEqual(tracker.update([], 1.0), [])
        reappeared = tracker.update([detection(0.26), detection(0.74)], 1.5)
        self.assertEqual([person["id"] for person in reappeared], [1, 2])

    def test_tracks_expire_without_reusing_ids(self) -> None:
        tracker = PersonTracker(max_age_sec=1.0)
        self.assertEqual(tracker.update([detection(0.2)], 0.0)[0]["id"], 1)
        self.assertEqual(tracker.update([detection(0.2)], 1.5)[0]["id"], 2)

    def test_gating_does_not_match_distant_box(self) -> None:
        tracker = PersonTracker(max_center_distance=0.1)
        tracker.update([detection(0.2)], 0.0)
        self.assertEqual(tracker.update([detection(0.8)], 0.5)[0]["id"], 2)

    def test_prediction_preserves_ids_after_crossing(self) -> None:
        tracker = PersonTracker(max_center_distance=0.25)
        tracker.update([detection(0.3), detection(0.7)], 0.0)
        tracker.update([detection(0.4), detection(0.6)], 0.5)
        crossed = tracker.update([detection(0.47), detection(0.53)], 1.0)
        self.assertGreater(crossed[0]["bbox"][0], crossed[1]["bbox"][0])

    def test_speed_uses_body_scale_and_time(self) -> None:
        tracker = PersonTracker()
        tracker.update([detection(0.2)], 0.0)
        moved = tracker.update([detection(0.25)], 0.5)[0]
        self.assertEqual(moved["motion"]["state"], "moving")
        self.assertAlmostEqual(
            moved["motion"]["speed_body_lengths_sec"], 0.05 / math.sqrt(0.02) / 0.5
        )

    def test_invalid_timestamps_and_bbox_fail(self) -> None:
        tracker = PersonTracker()
        tracker.update([], 0.0)
        with self.assertRaises(ValueError):
            tracker.update([], 0.0)
        with self.assertRaises(ValueError):
            tracker.update([{"bbox": [0, 0, 0, 1], "confidence": 0.9}], 0.5)


class RoleGeometryTests(unittest.TestCase):
    geometry = {"line": [[0.2, 0.5], [0.8, 0.5]], "cashier_side_reference": [0.5, 0.8]}

    def persons(self) -> list[dict]:
        return [dict(detection(0.45, 0.65), id=1), dict(detection(0.55, 0.35), id=2)]

    def test_uncalibrated_roles_are_unknown(self) -> None:
        roles = infer_roles(self.persons())
        self.assertEqual([item["role"] for item in roles], ["unknown", "unknown"])
        self.assertTrue(
            all(
                item["role_reason"] == "counter_geometry_not_calibrated"
                for item in roles
            )
        )

    def test_roles_depend_on_counter_side_with_person_relations(self) -> None:
        roles = infer_roles(self.persons(), self.geometry)
        self.assertEqual(
            [item["role"] for item in roles], ["cashier_candidate", "visitor_candidate"]
        )
        self.assertEqual(roles[0]["counter_relation"]["across_counter_person_ids"], [2])
        self.assertEqual(roles[1]["counter_relation"]["nearest_other_person_id"], 1)

    def test_reversing_counter_line_does_not_change_roles(self) -> None:
        geometry = dict(self.geometry, line=list(reversed(self.geometry["line"])))
        self.assertEqual(
            [p["role"] for p in infer_roles(self.persons(), self.geometry)],
            [p["role"] for p in infer_roles(self.persons(), geometry)],
        )

    def test_rotation_reflection_scale_translation_preserve_positional_roles(
        self,
    ) -> None:
        expected = [p["role"] for p in infer_roles(self.persons(), self.geometry)]
        angle = math.radians(30)
        transforms = [
            np.array(
                [
                    [math.cos(angle), -math.sin(angle)],
                    [math.sin(angle), math.cos(angle)],
                ]
            ),
            np.array([[-1.0, 0.0], [0.0, 1.0]]),
            np.array([[0.5, 0.0], [0.0, 0.5]]),
            np.array([[0.0, -1.0], [1.0, 0.0]]),
        ]
        for transform in transforms:

            def points(value: list) -> np.ndarray:
                return (np.asarray(value) - 0.5) @ transform.T + 0.5

            geometry = {
                "line": points(self.geometry["line"]).tolist(),
                "cashier_side_reference": points(
                    self.geometry["cashier_side_reference"]
                ).tolist(),
            }
            persons = self.persons()
            for person in persons:
                x1, y1, x2, y2 = person["bbox"]
                corners = points([[x1, y1], [x2, y1], [x2, y2], [x1, y2]])
                person["bbox"] = [*corners.min(axis=0), *corners.max(axis=0)]
            self.assertEqual(
                [p["role"] for p in infer_roles(persons, geometry)], expected
            )

    def test_far_and_on_line_are_unknown(self) -> None:
        persons = [
            dict(detection(0.5, 0.5), id=1),
            dict(detection(0.05, 0.95, 0.03), id=2),
        ]
        result = infer_roles(persons, self.geometry)
        self.assertEqual([p["role"] for p in result], ["unknown", "unknown"])

    def test_calibration_validation(self) -> None:
        with self.assertRaises(ValueError):
            RoleAssigner(
                {"line": [[0, 0], [0, 0]], "cashier_side_reference": [0.5, 0.5]}
            )
        with self.assertRaises(ValueError):
            RoleAssigner(
                {"line": [[0, 0.5], [1, 0.5]], "cashier_side_reference": [0.5, 0.5]}
            )


if __name__ == "__main__":
    unittest.main()
