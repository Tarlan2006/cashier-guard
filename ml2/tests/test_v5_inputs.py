"""Clothing gating and temporal role contracts, with synthetic facts only."""

import unittest
import numpy as np

from backend.pipeline.perception.appearance import clothing_histogram, color_distance
from backend.pipeline.perception.tracking import PersonTracker
from backend.pipeline.perception.scene_tracks import repair_tracks
from backend.pipeline.perception.roles_v2 import assign_temporal_roles


def person(key, box=None, **kwargs):
    return dict(
        id=key,
        bbox=box or [0.4, 0.4, 0.5, 0.6],
        confidence=0.9,
        counted=True,
        track_confirmed=True,
        **kwargs
    )


def scene():
    return dict(
        video=dict(width=400, height=600, duration_sec=10.0),
        sample_interval_sec=0.5,
        fixtures=[{"class": "counter_machine", "bbox": [0.5, 0.4, 0.6, 0.5]}],
        frames=[dict(timestamp_sec=i * 0.5, persons=[person(1)]) for i in range(20)],
    )


class V5InputTests(unittest.TestCase):
    def test_client_role_survives_moving_away_before_track_confirmation(self):
        facts = scene()
        for i, row in enumerate(facts["frames"]):
            if i >= 6:
                p = person(
                    2, box=[0.5, 0.4, 0.6, 0.5] if i == 6 else [0.9, 0.8, 0.99, 0.9]
                )
                p.update(counted=i >= 10, track_confirmed=i >= 10)
                row["persons"].append(p)
        assign_temporal_roles(facts)
        p = facts["frames"][-1]["persons"][1]
        self.assertEqual(p["role"], "client_candidate")
        self.assertFalse(p["near_table"])

    def test_top_of_box_does_not_contribute_to_clothing_histogram(self):
        first = np.full((100, 80, 3), 180, np.uint8)
        second = first.copy()
        second[:35] = [0, 0, 255]
        a = clothing_histogram(first, [0, 0, 1, 1])
        b = clothing_histogram(second, [0, 0, 1, 1])
        self.assertAlmostEqual(color_distance(a, b), 0.0, places=6)
        dark = np.full_like(first, 20)
        self.assertGreater(
            color_distance(a, clothing_histogram(dark, [0, 0, 1, 1])), 0.45
        )

    def test_same_geometry_with_different_clothes_does_not_reuse_id(self):
        tracker = PersonTracker()
        a = dict(
            bbox=[0.2, 0.2, 0.4, 0.5], confidence=0.9, clothing_histogram=[1.0, 0.0]
        )
        b = dict(a, clothing_histogram=[0.0, 1.0])
        self.assertEqual(tracker.update([a], 0.0)[0]["id"], 1)
        self.assertEqual(tracker.update([b], 0.5)[0]["id"], 2)

    def test_join_requires_color_and_no_more_than_two_seconds(self):
        for gap, second_hist, expected in [
            (2.0, [1.0, 0.0], 1),
            (2.5, [1.0, 0.0], 2),
            (1.0, [0.0, 1.0], 2),
        ]:
            facts = dict(
                frames=[
                    dict(
                        timestamp_sec=0.0,
                        persons=[person(1, clothing_histogram=[1.0, 0.0])],
                    ),
                    dict(
                        timestamp_sec=gap,
                        persons=[person(2, clothing_histogram=second_hist)],
                    ),
                ]
            )
            repair_tracks(facts)
            self.assertEqual(facts["frames"][-1]["persons"][0]["id"], expected)

    def test_single_occupant_is_cashier_without_scene_anchor(self):
        facts = scene()
        facts["fixtures"] = []
        assign_temporal_roles(facts)
        self.assertEqual(facts["roles"]["cashier_id"], 1)
        self.assertGreater(facts["frames"][-1]["persons"][0]["cashier_prob"], 0.9)

    def test_sequential_color_fragments_are_not_a_new_client_without_copresence(self):
        facts = scene()
        for i, row in enumerate(facts["frames"]):
            row["persons"][0]["id"] = 1 if i < 12 else 2
        assign_temporal_roles(facts)
        self.assertTrue(facts["roles"]["single_actor_scenario"])
        self.assertTrue(
            all(
                p["role"] == "cashier_candidate"
                for row in facts["frames"]
                for p in row["persons"]
            )
        )
        self.assertTrue(
            all(
                p["client_prob"] == 0 for row in facts["frames"] for p in row["persons"]
            )
        )

    def test_later_person_near_machine_does_not_take_the_cashier_role(self):
        facts = scene()
        for i, row in enumerate(facts["frames"]):
            if i >= 6:
                row["persons"].append(person(2, box=[0.5, 0.4, 0.6, 0.5]))
        assign_temporal_roles(facts)
        self.assertEqual(facts["roles"]["cashier_id"], 1)
        self.assertEqual(facts["frames"][-1]["persons"][1]["role"], "client_candidate")

    def test_uncertain_second_person_prevents_the_single_occupant_shortcut(self):
        facts = scene()
        for i, row in enumerate(facts["frames"]):
            if i >= 12:
                row["persons"].append(person(2, uncertain=True))
        assign_temporal_roles(facts)
        self.assertFalse(facts["roles"]["single_actor_scenario"])
        self.assertEqual(facts["frames"][-1]["persons"][1]["role"], "client_candidate")
        self.assertTrue(facts["frames"][-1]["persons"][1]["role_uncertain"])
