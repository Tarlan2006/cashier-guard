"""Scene-refinement integration checks, with no weights or video access."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from backend.pipeline.perception.config import PerceptionConfig
from backend.pipeline.perception.refine import refine_facts


def scene() -> dict:
    frames = []
    for index in range(20):
        people = [
            {
                "id": 1,
                "confidence": 0.90,
                "bbox": [0.4, 0.6, 0.6, 0.8],
                "observed": True,
            },
            {
                "id": 3,
                "confidence": 0.60,
                "bbox": [0.8, 0.4, 0.9, 0.5],
                "observed": True,
            },
        ]
        if index >= 6:
            people.append(
                {
                    "id": 2,
                    "confidence": 0.90,
                    "bbox": [0.4, 0.2, 0.6, 0.4],
                    "observed": True,
                }
            )
        frames.append(
            {
                "timestamp_sec": index * 0.5,
                "persons": people,
                "objects": [
                    {
                        "class": "suitcase",
                        "bbox": [0.47, 0.47, 0.53, 0.53],
                        "confidence": 0.8,
                    }
                ],
                "counter": {
                    "status": "calibrated",
                    "observed_near_person_ids": [1, 3],
                    "observed_object_counts_near_line": {"suitcase": 1},
                    "changes": [],
                },
            }
        )
    return {
        "schema_version": "1.0",
        "video": {"width": 800, "height": 600},
        "frames": frames,
    }


def fixture_annotation(_path: object, facts: dict, **_kwargs: object) -> dict:
    """A mocked naming result; deliberately do not read a frame or load SigLIP."""
    facts["fixtures"] = [
        {"id": 1, "class": "counter_machine", "bbox": [0.47, 0.47, 0.53, 0.53]}
    ]
    for row in facts["frames"]:
        row["objects"][0].update(
            {"class": "counter_machine", "coco_class": "suitcase", "fixture": True}
        )
        row["counter_machine"] = {"bbox": [0.47, 0.47, 0.53, 0.53]}
    return facts


class RefinementTests(unittest.TestCase):
    def setUp(self):
        for target in [
            "backend.pipeline.perception.refine.annotate_glass_context",
            "backend.pipeline.perception.proposals.discover_counter_machine",
            "backend.pipeline.perception.detector.get_detector",
            "backend.pipeline.perception.fixtures.get_fixture_classifier",
        ]:
            patcher = patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_calibrated_counter_roles_and_counts_exclude_retained_reflections(
        self,
    ) -> None:
        geometry = {
            "line": [[0.2, 0.5], [0.8, 0.5]],
            "cashier_side_reference": [0.5, 0.8],
        }
        config = PerceptionConfig(
            scene_version="v4",
            counter_geometry=geometry,
            anchor_vocabulary="legacy",
            role_method="legacy_temporal",
            state_engine_enabled=False,
        )
        facts = scene()
        original_counts = [len(row["persons"]) for row in facts["frames"]]
        classifier = Mock(name="local_fixture_classifier")
        with patch(
            "backend.pipeline.perception.refine.annotate_fixtures",
            side_effect=fixture_annotation,
        ) as naming:
            result = refine_facts(
                "nonexistent-no-video-access.mov", facts, config, classifier=classifier
            )
        self.assertIs(result, facts)
        self.assertIs(naming.call_args.kwargs["classifier"], classifier)
        self.assertEqual(
            [len(row["persons"]) for row in facts["frames"]], original_counts
        )
        self.assertEqual(facts["schema_version"], "1.3")
        for index, row in enumerate(facts["frames"]):
            persons = {person["id"]: person for person in row["persons"]}
            self.assertTrue(persons[3]["is_reflection"])
            self.assertEqual(persons[3]["role"], "unknown")
            self.assertEqual(
                persons[3]["role_reason"], "reflection_excluded_from_roles"
            )
            self.assertEqual(
                persons[1]["role"], "unknown" if index < 4 else "cashier_candidate"
            )
            self.assertEqual(row["reflection_count"], 1)
            self.assertEqual(
                row["people_count"], 0 if index < 4 else 1 if index < 10 else 2
            )
            self.assertEqual(
                row["counter"]["observed_near_person_ids"],
                [] if index < 4 else [1] if index < 10 else [1, 2],
            )
            self.assertEqual(
                row["counter"]["observed_object_counts_near_line"],
                {"counter_machine": 1},
            )
            self.assertNotIn(
                3, persons[1]["counter_relation"]["across_counter_person_ids"]
            )
            if index >= 10:
                self.assertEqual(persons[2]["role"], "visitor_candidate")
                self.assertEqual(
                    persons[1]["counter_relation"]["nearest_other_person_id"], 2
                )
        changes = facts["frames"][10]["counter"]["changes"]
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["newly_observed_ids"], [2])
        self.assertEqual(changes[0]["no_longer_observed_ids"], [])

    def test_automatic_machine_relative_roles_do_not_invent_counter_calibration(
        self,
    ) -> None:
        facts = scene()
        with patch(
            "backend.pipeline.perception.refine.annotate_fixtures",
            side_effect=fixture_annotation,
        ):
            refine_facts(
                "unused.mov",
                facts,
                PerceptionConfig(
                    scene_version="v4",
                    anchor_vocabulary="legacy",
                    role_method="legacy_temporal",
                    state_engine_enabled=False,
                ),
            )
        last = {person["id"]: person for person in facts["frames"][-1]["persons"]}
        self.assertEqual(last[1]["role"], "cashier_candidate")
        self.assertEqual(last[2]["role"], "client_candidate")
        self.assertEqual(last[3]["role"], "unknown")
        self.assertEqual(last[1]["counter_relation"]["nearest_other_person_id"], 2)
        self.assertTrue(
            all(row["counter"]["status"] == "uncalibrated" for row in facts["frames"])
        )
        self.assertTrue(all(row["counter"]["changes"] == [] for row in facts["frames"]))

    def test_global_reflection_config_is_forwarded(self) -> None:
        config = PerceptionConfig(
            scene_version="v4",
            reflection_config={"candidate_max_confidence": 0.50},
            anchor_vocabulary="legacy",
            role_method="legacy_temporal",
            state_engine_enabled=False,
        )
        facts = scene()
        with patch(
            "backend.pipeline.perception.refine.annotate_fixtures",
            side_effect=fixture_annotation,
        ):
            refine_facts("unused.mov", facts, config)
        self.assertTrue(
            all(
                not person["is_reflection"]
                for row in facts["frames"]
                for person in row["persons"]
            )
        )
        self.assertEqual(facts["frames"][-1]["people_count"], 3)
        self.assertEqual(
            facts["reflection_filter"]["config"]["candidate_max_confidence"], 0.50
        )

    def test_legacy_feature_roles_and_state_engine_integrate_without_network(
        self,
    ) -> None:
        facts = scene()
        classifier = Mock(name="injected_local_classifier")
        with (
            patch(
                "backend.pipeline.perception.refine.annotate_fixtures",
                side_effect=fixture_annotation,
            ),
            patch("backend.pipeline.perception.anchors.discover_scene_anchors"),
        ):
            refine_facts(
                "unused.mov",
                facts,
                PerceptionConfig(scene_version="v4", role_method="feature_softmax"),
                classifier=classifier,
                anchor_classifier=classifier,
            )
        self.assertEqual(facts["roles"]["method"], "feature_softmax_v1")
        self.assertEqual(facts["roles"]["cashier_id"], 1)
        self.assertIn("state_engine", facts)
        for row in facts["frames"]:
            for person in row["persons"]:
                self.assertGreaterEqual(person["cashier_prob"], 0.0)
                self.assertLessEqual(
                    person["cashier_prob"] + person["client_prob"], 1.0 + 1e-6
                )
                if person["is_reflection"]:
                    self.assertEqual(person["cashier_prob"], 0.0)
        self.assertEqual(facts["events"][0]["timecode_sec"], 0.0)

    def test_refinement_order_and_injected_classifier_without_inference(self) -> None:
        facts = {
            "video": {},
            "frames": [
                {
                    "timestamp_sec": 0.0,
                    "persons": [
                        {"id": 1, "confidence": 0.9, "bbox": [0.1, 0.1, 0.2, 0.3]}
                    ],
                    "objects": [],
                }
            ],
        }
        config = PerceptionConfig(
            scene_version="v4",
            torch_threads=1,
            device="cpu",
            anchor_vocabulary="legacy",
            role_method="legacy_temporal",
            state_engine_enabled=False,
        )
        classifier = Mock(name="injected_offline_classifier")
        order = []

        def reflection_step(target: dict, configured: object) -> None:
            self.assertIsNone(configured)
            order.append("reflections")
            target["frames"][0]["persons"][0]["is_reflection"] = True

        def fixture_step(path: object, target: dict, **kwargs: object) -> None:
            self.assertEqual(str(path), "unused.mov")
            self.assertTrue(target["frames"][0]["persons"][0]["is_reflection"])
            self.assertIs(kwargs["classifier"], classifier)
            self.assertEqual(kwargs["threads"], 1)
            self.assertEqual(kwargs["device"], "cpu")
            order.append("fixtures")
            target["fixtures"] = []

        def role_step(target: dict) -> None:
            self.assertIn("fixtures", target)
            order.append("roles")
            target["frames"][0]["persons"][0]["role"] = "unknown"

        def counter_step(target: dict) -> None:
            self.assertEqual(target["frames"][0]["persons"][0]["role"], "unknown")
            order.append("counter")

        with (
            patch(
                "backend.pipeline.perception.refine.annotate_reflections",
                side_effect=reflection_step,
            ),
            patch(
                "backend.pipeline.perception.refine.annotate_fixtures",
                side_effect=fixture_step,
            ),
            patch(
                "backend.pipeline.perception.refine.infer_scene_roles",
                side_effect=role_step,
            ),
            patch(
                "backend.pipeline.perception.counter.refine_counter_facts",
                side_effect=counter_step,
            ),
        ):
            refine_facts("unused.mov", facts, config, classifier=classifier)
        self.assertEqual(
            order, ["reflections", "reflections", "fixtures", "roles", "counter"]
        )
        self.assertEqual(facts["frames"][0]["people_count"], 0)
        self.assertEqual(facts["frames"][0]["reflection_count"], 1)
        self.assertEqual(facts["refinement"]["version"], "perception-v4")
        classifier.assert_not_called()


if __name__ == "__main__":
    unittest.main()
