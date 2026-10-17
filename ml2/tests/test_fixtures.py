from __future__ import annotations

import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from backend.pipeline.perception.fixtures import (
    LocalSigLIPClassifier,
    PROMPTS,
    annotate_fixtures,
    find_fixture_tracks,
    preprocess_crop_bgr,
)


def make_facts(count=20):
    return {
        "frames": [
            {
                "timestamp_sec": i * 0.5,
                "objects": [
                    {
                        "class": "suitcase" if i % 2 else "tv",
                        "bbox": [0.4, 0.3, 0.6, 0.6],
                        "confidence": 0.8,
                    },
                    *(
                        [
                            {
                                "class": "cell phone",
                                "bbox": [0.7, 0.1, 0.8, 0.2],
                                "confidence": 0.9,
                            }
                        ]
                        if 4 <= i < 8
                        else []
                    ),
                ],
            }
            for i in range(count)
        ]
    }


class FixtureTests(unittest.TestCase):
    def test_class_changes_do_not_fragment_a_fixed_proposal(self):
        tracks = find_fixture_tracks(make_facts())
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["presence_fraction"], 1.0)
        self.assertEqual(len(tracks[0]["hits"]), 20)

    def test_long_visibility_is_required_not_merely_stillness(self):
        facts = make_facts()
        for row in facts["frames"]:
            row["objects"] = row["objects"][1:]
        self.assertEqual(find_fixture_tracks(facts), [])

    def test_moving_object_is_not_a_fixture(self):
        facts = make_facts()
        for i, row in enumerate(facts["frames"]):
            row["objects"] = [
                {
                    "class": "suitcase",
                    "confidence": 0.9,
                    "bbox": [0.02 * i, 0.1, 0.02 * i + 0.2, 0.3],
                }
            ]
        self.assertEqual(find_fixture_tracks(facts), [])

    def test_intermittent_full_video_static_support_survives_detection_gaps(self):
        facts = make_facts(100)
        for i, row in enumerate(facts["frames"]):
            row["objects"] = row["objects"][:1] if i % 5 == 0 else []
        tracks = find_fixture_tracks(facts)
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["presence_fraction"], 0.2)
        self.assertEqual(tracks[0]["temporal_bin_coverage"], 1.0)
        self.assertEqual(len(tracks[0]["hits"]), 20)

    def test_relocated_same_size_boxes_make_same_stability_decision(self):
        facts = make_facts()
        relocated = copy.deepcopy(facts)
        for row in relocated["frames"]:
            for obj in row["objects"]:
                obj["bbox"] = [
                    value + (0.02 if j % 2 == 0 else 0.05)
                    for j, value in enumerate(obj["bbox"])
                ]
        self.assertEqual(
            [len(t["hits"]) for t in find_fixture_tracks(facts)],
            [len(t["hits"]) for t in find_fixture_tracks(relocated)],
        )

    def test_annotate_counter_preserves_raw_class_and_transient_object(self):
        class Reader:
            def __init__(self, _):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def read_at(self, timestamp):
                return SimpleNamespace(
                    frame_bgr=np.zeros((40, 80, 3), np.uint8),
                    actual_timestamp_sec=timestamp,
                )

        class Classifier:
            def classify(self, crops):
                self.views = len(crops)
                return {
                    "class": "counter_machine",
                    "label": "счётная машинка",
                    "confidence": 0.7,
                    "confidence_kind": "uncalibrated_siglip_sigmoid",
                    "reason": "accepted",
                }

        classifier = Classifier()
        with patch("backend.pipeline.perception.fixtures.VideoReader", Reader):
            facts = annotate_fixtures("unused.mov", make_facts(), classifier=classifier)
        self.assertEqual(classifier.views, 3)
        self.assertEqual(facts["fixtures"][0]["raw_coco_classes"], ["suitcase", "tv"])
        self.assertEqual(
            facts["frames"][0]["counter_machine"]["bbox"], [0.4, 0.3, 0.6, 0.6]
        )
        self.assertEqual(facts["frames"][4]["objects"][1]["class"], "cell phone")
        self.assertNotIn("fixture", facts["frames"][4]["objects"][1])

    def test_no_fixture_does_not_load_a_model_or_open_video(self):
        facts = {"frames": [{"timestamp_sec": 0, "objects": []}]}
        with patch(
            "backend.pipeline.perception.fixtures.get_fixture_classifier",
            side_effect=AssertionError,
        ):
            annotate_fixtures("missing.mov", facts)
        self.assertEqual(facts["fixtures"], [])
        self.assertIsNone(facts["frames"][0]["counter_machine"])

    def test_crops_follow_actual_timestamps_and_do_not_repeat_source_frames(self):
        requests = []

        class Reader:
            def __init__(self, _):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def read_at(self, timestamp):
                requests.append(timestamp)
                return SimpleNamespace(
                    frame_bgr=np.zeros((40, 80, 3), np.uint8), actual_timestamp_sec=1.0
                )

        class Classifier:
            def classify(self, crops):
                self.views = len(crops)
                return {
                    "class": "unclassified_fixture",
                    "label": None,
                    "reason": "insufficient_view_agreement",
                }

        facts = make_facts()
        for row in facts["frames"]:
            row["actual_timestamp_sec"] = 1.0
        classifier = Classifier()
        with patch("backend.pipeline.perception.fixtures.VideoReader", Reader):
            annotate_fixtures("unused.mov", facts, classifier=classifier)
        self.assertEqual(requests, [1.0, 1.0, 1.0])
        self.assertEqual(classifier.views, 1)
        self.assertTrue(all(row["counter_machine"] is None for row in facts["frames"]))

    def test_glass_rejection_is_not_forced_to_one_of_six_names(self):
        # Exercise classification policy with deterministic orthogonal vectors;
        # no weights, network or video is needed for this policy regression.
        classifier = LocalSigLIPClassifier.__new__(LocalSigLIPClassifier)
        classifier.labels = list(PROMPTS)
        classifier.prompt_labels = np.array(
            [label for label, prompts in PROMPTS.items() for _ in prompts]
        )
        classifier.prompt_features = np.eye(len(classifier.labels))[
            np.array(
                [classifier.labels.index(label) for label in classifier.prompt_labels]
            )
        ]
        classifier.logit_scale, classifier.logit_bias = 1.0, 0.0
        classifier.min_margin, classifier.min_similarity = 0.01, 0.18

        class Session:
            def run(self, *_):
                result = np.zeros((1, len(PROMPTS)), np.float32)
                result[0, list(PROMPTS).index("reject_glass")] = 1.0
                return [result]

        classifier.session = Session()
        result = classifier.classify([np.zeros((10, 20, 3), np.uint8)] * 3)
        self.assertEqual(result["class"], "unclassified_fixture")
        self.assertIn("reject_glass", result["reason"])

    def test_one_crop_cannot_establish_a_counter_machine(self):
        classifier = LocalSigLIPClassifier.__new__(LocalSigLIPClassifier)
        classifier.labels = list(PROMPTS)
        classifier.prompt_labels = np.array(
            [label for label, prompts in PROMPTS.items() for _ in prompts]
        )
        classifier.prompt_features = np.eye(len(classifier.labels))[
            np.array(
                [classifier.labels.index(label) for label in classifier.prompt_labels]
            )
        ]
        classifier.logit_scale, classifier.logit_bias = 1.0, 0.0
        classifier.min_margin, classifier.min_similarity = 0.01, 0.18

        class Session:
            def run(self, *_):
                result = np.zeros((1, len(PROMPTS)), np.float32)
                result[0, 0] = 1.0
                return [result]

        classifier.session = Session()
        crop = np.zeros((10, 20, 3), np.uint8)
        self.assertEqual(classifier.classify([crop])["class"], "unclassified_fixture")
        self.assertEqual(classifier.classify([crop, crop])["class"], "counter_machine")

    def test_preprocessor_normalization_and_fixed_shape(self):
        value = preprocess_crop_bgr(np.zeros((10, 20, 3), np.uint8))
        self.assertEqual(value.shape, (1, 3, 224, 224))
        self.assertTrue(np.all(value == -1.0))

    def test_absolute_cosine_gate_is_opt_in_and_not_a_model_independent_default(self):
        classifier = LocalSigLIPClassifier.__new__(LocalSigLIPClassifier)
        classifier.labels = list(PROMPTS)
        classifier.prompt_labels = np.array(
            [label for label, prompts in PROMPTS.items() for _ in prompts]
        )
        dimensions = len(classifier.labels) + 1
        classifier.prompt_features = np.eye(dimensions)[
            np.array(
                [classifier.labels.index(label) for label in classifier.prompt_labels]
            )
        ]
        classifier.logit_scale, classifier.logit_bias = 117.0, -13.0
        classifier.min_margin, classifier.min_similarity = 0.01, None

        class Session:
            def run(self, *_):
                result = np.zeros((1, dimensions), np.float32)
                result[0, 0], result[0, -1] = 0.1, np.sqrt(0.99)
                return [result]

        classifier.session = Session()
        crops = [np.zeros((10, 20, 3), np.uint8)] * 3
        result = classifier.classify(crops)
        self.assertEqual(result["class"], "counter_machine")
        self.assertEqual(result["naming_status"], "uncalibrated_hypothesis")
        classifier.min_similarity = 0.18
        self.assertEqual(classifier.classify(crops)["class"], "unclassified_fixture")


if __name__ == "__main__":
    unittest.main()
