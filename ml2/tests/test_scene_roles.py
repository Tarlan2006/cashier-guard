"""Scene-role rules only: synthetic geometry, no model or video processing."""

from __future__ import annotations

import copy
import unittest

import numpy as np

from backend.pipeline.perception.roles import RoleAssigner, infer_scene_roles


def person(identifier: int, center: tuple[float, float], **extra: object) -> dict:
    x, y = center
    return {
        "id": identifier,
        "bbox": [x - 0.07, y - 0.09, x + 0.07, y + 0.09],
        "confidence": 0.9,
        **extra,
    }


def scene(*, machine: bool = True, client_start: int = 6) -> dict:
    return {
        "config": {},
        "fixtures": (
            [{"class": "counter_machine", "bbox": [0.46, 0.46, 0.54, 0.54]}]
            if machine
            else []
        ),
        "frames": [
            {
                "timestamp_sec": index * 0.5,
                "persons": [person(1, (0.5, 0.70))]
                + ([person(2, (0.5, 0.30))] if index >= client_start else []),
            }
            for index in range(20)
        ],
    }


class SceneRolesTests(unittest.TestCase):
    def test_machine_residency_and_late_opposite_arrival(self) -> None:
        facts = infer_scene_roles(scene())
        self.assertEqual(
            [p["role"] for p in facts["frames"][-1]["persons"]],
            ["cashier_candidate", "client_candidate"],
        )
        resident = facts["frames"][-1]["persons"][0]
        self.assertEqual(resident["counter_relation"]["across_counter_person_ids"], [2])
        self.assertEqual(resident["role_confidence"], 0.6)

    def test_no_machine_or_raw_coco_suitcase_never_assigns_role(self) -> None:
        facts = scene(machine=False)
        facts["fixtures"] = [{"class": "suitcase", "bbox": [0.46, 0.46, 0.54, 0.54]}]
        infer_scene_roles(facts)
        self.assertTrue(
            all(
                p["role"] == "unknown"
                for row in facts["frames"]
                for p in row["persons"]
            )
        )

    def test_equal_residence_leaves_roles_unknown(self) -> None:
        facts = infer_scene_roles(scene(client_start=0))
        self.assertTrue(
            all(
                p["role"] == "unknown"
                for row in facts["frames"]
                for p in row["persons"]
            )
        )

    def test_later_person_on_same_side_has_unknown_role(self) -> None:
        facts = scene()
        for row in facts["frames"]:
            if len(row["persons"]) > 1:
                row["persons"][1] = person(2, (0.7, 0.7))
        infer_scene_roles(facts)
        self.assertEqual(facts["frames"][-1]["persons"][1]["role"], "unknown")

    def test_longest_track_far_from_machine_is_unknown(self) -> None:
        facts = scene()
        for row in facts["frames"]:
            row["persons"][0] = person(1, (0.10, 0.9))
        infer_scene_roles(facts)
        self.assertTrue(
            all(
                p["role"] == "unknown"
                for row in facts["frames"]
                for p in row["persons"]
            )
        )

    def test_reflection_is_retained_but_excluded_from_residency_and_relations(
        self,
    ) -> None:
        facts = scene()
        for row in facts["frames"]:
            row["persons"].append(person(3, (0.5, 0.705), is_reflection=True))
        infer_scene_roles(facts)
        last = facts["frames"][-1]["persons"]
        self.assertEqual(
            [p["role"] for p in last],
            ["cashier_candidate", "client_candidate", "unknown"],
        )
        self.assertEqual(last[0]["counter_relation"]["nearest_other_person_id"], 2)
        self.assertEqual(last[2]["role_reason"], "reflection_excluded_from_roles")
        self.assertTrue(last[2]["is_reflection"])

    def test_calibrated_geometry_also_excludes_reflections(self) -> None:
        geometry = {
            "line": [[0.2, 0.5], [0.8, 0.5]],
            "cashier_side_reference": [0.5, 0.8],
        }
        people = [
            person(1, (0.5, 0.7)),
            person(2, (0.5, 0.3)),
            person(3, (0.5, 0.71), is_reflection=True),
        ]
        result = RoleAssigner(geometry).assign(people)
        self.assertEqual(
            [p["role"] for p in result],
            ["cashier_candidate", "visitor_candidate", "unknown"],
        )
        self.assertEqual(result[0]["counter_relation"]["nearest_other_person_id"], 2)
        self.assertEqual(
            result[1]["counter_relation"]["across_counter_person_ids"], [1]
        )

    def test_machine_relative_roles_do_not_depend_on_image_axis(self) -> None:
        original = scene()
        expected = [
            p["role"]
            for p in infer_scene_roles(copy.deepcopy(original))["frames"][-1]["persons"]
        ]
        transforms = [
            np.array([[0.0, -1.0], [1.0, 0.0]]),
            np.array([[-1.0, 0.0], [0.0, 1.0]]),
            np.array([[0.866, -0.5], [0.5, 0.866]]),
        ]
        for transform in transforms:
            facts = copy.deepcopy(original)
            for item in facts["fixtures"] + [
                p for row in facts["frames"] for p in row["persons"]
            ]:
                x1, y1, x2, y2 = item["bbox"]
                corners = (
                    np.asarray([[x1, y1], [x2, y1], [x2, y2], [x1, y2]]) - 0.5
                ) @ transform.T + 0.5
                item["bbox"] = [*corners.min(axis=0), *corners.max(axis=0)]
            infer_scene_roles(facts)
            self.assertEqual(
                [p["role"] for p in facts["frames"][-1]["persons"]], expected
            )


if __name__ == "__main__":
    unittest.main()
