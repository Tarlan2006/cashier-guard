"""Semantic state consensus and shared workplace geometry; no video/model."""

from types import SimpleNamespace
import unittest
import numpy as np

from backend.pipeline.semantic_engine import semantic_window, collect_moments


class Reader:
    def read_at(self, t):
        return SimpleNamespace(
            actual_timestamp_sec=t, frame_bgr=np.full((100, 100, 3), 180, np.uint8)
        )


class SemanticTests(unittest.TestCase):
    def test_uncertain_client_cannot_create_arrival_or_overlap_moments(self):
        frames = [
            dict(
                timestamp_sec=i * 0.5,
                persons=[
                    dict(
                        id=1,
                        role="cashier_candidate",
                        bbox=[0.4, 0.4, 0.5, 0.6],
                        confidence=0.9,
                    ),
                    dict(
                        id=2,
                        role="client_candidate",
                        bbox=[0.2, 0.2, 0.3, 0.3],
                        near_table=True,
                        uncertain=True,
                    ),
                ],
            )
            for i in range(20)
        ]
        facts = dict(
            video=dict(width=100, height=100),
            frames=frames,
            fixtures=[],
            roles=dict(cashier_ids=[1]),
        )
        self.assertFalse(
            any(
                m["type"] in {"new_client_at_table", "two_clients_overlap"}
                for m in collect_moments(facts)["moments"]
            )
        )

    def test_unknown_is_not_forced_into_open_or_closed(self):
        model = SimpleNamespace(
            classify=lambda *_: dict(
                state="unknown", margin=0.0, candidate="unknown", scores={}
            )
        )
        state = semantic_window(Reader(), model, "safe", [0, 0, 1, 1], [1.0, 1.5], {})
        self.assertEqual(state["state"], "unknown")

    def test_two_distinct_frames_are_needed_for_semantic_state(self):
        model = SimpleNamespace(
            classify=lambda *_: dict(
                state="open", margin=0.03, candidate="open", scores={}
            )
        )
        self.assertEqual(
            semantic_window(Reader(), model, "safe", [0, 0, 1, 1], [1.0, 1.0], {})[
                "state"
            ],
            "unknown",
        )
        self.assertEqual(
            semantic_window(Reader(), model, "safe", [0, 0, 1, 1], [1.0, 1.5], {})[
                "state"
            ],
            "open",
        )

    def test_cashier_id_change_does_not_move_the_workplace(self):
        frames = []
        for i in range(24):
            box = [0.4, 0.4, 0.5, 0.6] if i < 12 else [0.7, 0.7, 0.8, 0.9]
            frames.append(
                dict(
                    timestamp_sec=i * 0.5,
                    persons=[dict(id=1 if i < 12 else 2, bbox=box, confidence=0.9)],
                )
            )
        facts = dict(
            video=dict(width=100, height=100),
            frames=frames,
            fixtures=[],
            roles=dict(cashier_ids=[1, 2]),
        )
        moments = collect_moments(facts)["moments"]
        exit = next(m for m in moments if m["type"] == "cashier_left_workplace")
        self.assertEqual(exit["first_seen"], 6.0)
        self.assertEqual(exit["confirmed_at"], 8.0)

    def test_three_second_overlap_keeps_the_first_overlap_time(self):
        frames = [
            dict(
                timestamp_sec=i * 0.5,
                persons=[
                    dict(
                        id=1,
                        role="cashier_candidate",
                        bbox=[0.4, 0.4, 0.5, 0.6],
                        confidence=0.9,
                    ),
                    dict(
                        id=2,
                        role="client_candidate",
                        bbox=[0.2, 0.2, 0.3, 0.3],
                        near_table=True,
                    ),
                    *(
                        [
                            dict(
                                id=3,
                                role="client_candidate",
                                bbox=[0.7, 0.2, 0.8, 0.3],
                                near_table=True,
                            )
                        ]
                        if i >= 6
                        else []
                    ),
                ],
            )
            for i in range(20)
        ]
        facts = dict(
            video=dict(width=100, height=100),
            frames=frames,
            fixtures=[],
            roles=dict(cashier_ids=[1]),
        )
        moment = next(
            m
            for m in collect_moments(facts)["moments"]
            if m["type"] == "two_clients_overlap"
        )
        self.assertEqual(moment["first_seen"], 3.0)
        self.assertEqual(moment["confirmed_at"], 6.0)
