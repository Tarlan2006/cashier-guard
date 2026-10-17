from __future__ import annotations

import unittest

import numpy as np

from backend.pipeline.perception.counter import CounterObserver, refine_counter_facts


class CounterObservationTests(unittest.TestCase):
    geometry = {"line": [[0.4, 0.5], [0.6, 0.5]], "cashier_side_reference": [0.5, 0.8]}

    def setUp(self) -> None:
        self.black = np.zeros((64, 80, 3), dtype=np.uint8)
        self.white = np.full((64, 80, 3), 255, dtype=np.uint8)

    def test_uncalibrated_counter_makes_no_change_claims(self) -> None:
        observer = CounterObserver(None)
        first = observer.update([], [], self.black)
        second = observer.update(
            [{"id": 1}], [{"class": "bottle", "bbox": [0.4, 0.4, 0.6, 0.6]}], self.white
        )
        self.assertEqual(first["status"], "uncalibrated")
        self.assertEqual(first["changes"], [])
        self.assertEqual(second["changes"], [])
        self.assertNotIn("observed_object_counts_near_line", second)

    def test_occupancy_is_observation_change_and_unknown_distances_are_ignored(
        self,
    ) -> None:
        observer = CounterObserver(self.geometry)
        bottle = {"class": "bottle", "bbox": [0.45, 0.45, 0.55, 0.55]}
        first = observer.update(
            [
                {"id": 1, "counter_relation": {"distance_body_lengths": 0.2}},
                {"id": 2, "counter_relation": {"distance_body_lengths": None}},
                {"id": 3},
            ],
            [bottle],
            self.black,
        )
        self.assertEqual(first["observed_near_person_ids"], [1])
        self.assertEqual(first["changes"], [])
        second = observer.update(
            [{"id": 4, "counter_relation": {"distance_body_lengths": 0.3}}],
            [],
            self.black,
        )
        changes = {change["kind"]: change for change in second["changes"]}
        occupancy = changes["observed_near_counter_person_ids_changed"]
        self.assertEqual(occupancy["newly_observed_ids"], [4])
        self.assertEqual(occupancy["no_longer_observed_ids"], [1])
        counts = changes["observed_near_counter_object_counts_changed"]
        self.assertEqual(counts["before"], {"bottle": 1})
        self.assertEqual(counts["after"], {})
        self.assertIn("transfer is not established", counts["meaning"])
        self.assertIsNone(second["appearance"])

    def test_optional_polygon_and_finite_segment_distance_with_early_validation(
        self,
    ) -> None:
        geometry = dict(
            self.geometry,
            surface_polygon=[[0.4, 0.4], [0.6, 0.4], [0.6, 0.6], [0.4, 0.6]],
        )
        observer = CounterObserver(geometry)
        remote = {"class": "bottle", "bbox": [0.94, 0.48, 0.98, 0.52]}
        observer.update([], [remote], self.black)
        second = observer.update([], [remote], self.white)
        self.assertEqual(second["observed_object_counts_near_line"], {})
        self.assertEqual(second["appearance"]["changed_fraction"], 1.0)
        self.assertEqual(
            second["changes"][0]["kind"], "counter_surface_appearance_changed"
        )
        with self.assertRaises(ValueError):
            CounterObserver(dict(self.geometry, line=[[0.4, 0.5], [0.4, 0.5]]))
        with self.assertRaises(ValueError):
            CounterObserver(
                dict(self.geometry, surface_polygon=[[0, 0], [0.5, 0.5], [1, 1]])
            )

    def test_reflections_never_enter_counter_occupancy_or_change_sets(self) -> None:
        observer = CounterObserver(self.geometry)
        real = {"id": 1, "counter_relation": {"distance_body_lengths": 0.2}}
        reflection = {
            "id": 2,
            "is_reflection": True,
            "counter_relation": {"distance_body_lengths": 0.1},
        }
        first = observer.update([real, reflection], [], self.black)
        second = observer.update([real], [], self.black)
        self.assertEqual(first["observed_near_person_ids"], [1])
        self.assertEqual(second["observed_near_person_ids"], [1])
        self.assertEqual(second["changes"], [])

    def test_refine_recomputes_ids_and_canonical_classes_preserves_appearance(
        self,
    ) -> None:
        appearance = {"changed_fraction": 0.25, "kind": "appearance_difference"}
        appearance_change = {
            "kind": "counter_surface_appearance_changed",
            "changed_fraction": 0.25,
        }
        geometry = dict(
            self.geometry,
            surface_polygon=[[0.4, 0.4], [0.6, 0.4], [0.6, 0.6], [0.4, 0.6]],
        )
        person = {"id": 1, "counter_relation": {"distance_body_lengths": 0.2}}
        reflection = {
            "id": 2,
            "is_reflection": True,
            "counter_relation": {"distance_body_lengths": 0.1},
        }
        machine = {
            "class": "counter_machine",
            "coco_class": "suitcase",
            "bbox": [0.45, 0.45, 0.55, 0.55],
        }
        facts = {
            "config": {"counter_geometry": geometry},
            "frames": [
                {
                    "timestamp_sec": 0.0,
                    "persons": [person, reflection],
                    "objects": [machine],
                    "counter": {
                        "observed_near_person_ids": [1, 2],
                        "observed_object_counts_near_line": {"suitcase": 1},
                        "appearance": None,
                        "changes": [],
                    },
                },
                {
                    "timestamp_sec": 0.5,
                    "persons": [person],
                    "objects": [],
                    "counter": {
                        "appearance": appearance,
                        "changes": [
                            appearance_change,
                            {
                                "kind": "observed_near_counter_person_ids_changed",
                                "no_longer_observed_ids": [2],
                            },
                        ],
                    },
                },
            ],
        }
        self.assertIs(refine_counter_facts(facts), facts)
        first, second = [row["counter"] for row in facts["frames"]]
        self.assertEqual(first["observed_near_person_ids"], [1])
        self.assertEqual(
            first["observed_object_counts_near_line"], {"counter_machine": 1}
        )
        self.assertEqual(first["changes"], [])
        self.assertEqual(second["appearance"], appearance)
        self.assertIn(appearance_change, second["changes"])
        counts_change = second["changes"][0]
        self.assertEqual(
            counts_change["kind"], "observed_near_counter_object_counts_changed"
        )
        self.assertEqual(counts_change["before"], {"counter_machine": 1})
        self.assertEqual(counts_change["after"], {})
        self.assertFalse(
            any(
                change["kind"] == "observed_near_counter_person_ids_changed"
                for change in second["changes"]
            )
        )
        # Running box-only refinement twice must not duplicate appearance changes.
        refine_counter_facts(facts)
        self.assertEqual(
            facts["frames"][1]["counter"]["changes"].count(appearance_change), 1
        )

    def test_refine_without_geometry_does_not_invent_machine_counter_line(self) -> None:
        appearance = {"changed_fraction": 0.25, "kind": "appearance_difference"}
        facts = {
            "config": {},
            "fixtures": [
                {"class": "counter_machine", "bbox": [0.45, 0.45, 0.55, 0.55]}
            ],
            "frames": [
                {
                    "timestamp_sec": 0.0,
                    "persons": [{"id": 1, "role": "cashier_candidate"}],
                    "counter_machine": {"bbox": [0.45, 0.45, 0.55, 0.55]},
                    "counter": {
                        "appearance": appearance,
                        "changes": [
                            {
                                "kind": "counter_surface_appearance_changed",
                                "changed_fraction": 0.25,
                            }
                        ],
                    },
                }
            ],
        }
        refine_counter_facts(facts)
        counter = facts["frames"][0]["counter"]
        self.assertEqual(counter["status"], "uncalibrated")
        self.assertEqual(counter["changes"], [])
        self.assertEqual(counter["appearance"], appearance)
        self.assertNotIn("observed_near_person_ids", counter)

    def test_refinement_excludes_track_flagged_as_reflection_in_later_row(self) -> None:
        person = {"id": 7, "counter_relation": {"distance_body_lengths": 0.2}}
        facts = {
            "config": {"counter_geometry": self.geometry},
            "frames": [
                {"timestamp_sec": 0.0, "persons": [person]},
                {"timestamp_sec": 0.5, "persons": [dict(person, is_reflection=True)]},
            ],
        }
        refine_counter_facts(facts)
        self.assertEqual(
            [row["counter"]["observed_near_person_ids"] for row in facts["frames"]],
            [[], []],
        )
        self.assertTrue(all(not row["counter"]["changes"] for row in facts["frames"]))


if __name__ == "__main__":
    unittest.main()
