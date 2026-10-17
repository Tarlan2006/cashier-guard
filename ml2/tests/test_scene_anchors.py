"""Scene-vocabulary acceptance, furniture audit and shared-session contracts."""

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock

import numpy as np

from backend.pipeline.perception.anchors import (
    get_scene_classifier,
    sanitize_scene_fixtures,
    discover_scene_anchors,
)
from backend.pipeline.perception.fixtures import LocalSigLIPClassifier
from backend.pipeline.perception.scene_vocab import SCENE_LABELS, SCENE_PROMPTS


class AnchorTests(unittest.TestCase):
    def test_scene_vocabulary_can_accept_safe_but_not_a_single_view(self):
        classifier = LocalSigLIPClassifier.__new__(LocalSigLIPClassifier)
        classifier.labels = list(SCENE_PROMPTS)
        classifier.output_names = SCENE_LABELS
        classifier.prompt_labels = np.array(
            [label for label, phrases in SCENE_PROMPTS.items() for _ in phrases]
        )
        classifier.prompt_features = np.eye(len(classifier.labels))[
            np.array([classifier.labels.index(x) for x in classifier.prompt_labels])
        ]
        classifier.logit_scale, classifier.logit_bias = 1.0, 0.0
        classifier.min_margin, classifier.min_similarity = 0.01, None
        vector = np.zeros((1, len(classifier.labels)), np.float32)
        vector[0, classifier.labels.index("safe")] = 1.0
        classifier.session = SimpleNamespace(run=lambda *_: [vector])
        crop = np.zeros((20, 20, 3), np.uint8)
        self.assertEqual(classifier.classify([crop])["class"], "unclassified_fixture")
        self.assertEqual(classifier.classify([crop, crop])["class"], "safe")

    def test_unknown_fixed_proposal_is_audited_without_changing_raw_class(self):
        facts = dict(
            fixtures=[dict(id=7, **{"class": "unclassified_fixture"})],
            frames=[
                dict(
                    objects=[
                        dict(
                            fixture_id=7,
                            fixture=True,
                            **{"class": "unclassified_fixture", "coco_class": "chair"}
                        )
                    ]
                )
            ],
        )
        sanitize_scene_fixtures(facts)
        self.assertEqual(facts["fixtures"], [])
        self.assertEqual(len(facts["rejected_fixture_proposals"]), 1)
        obj = facts["frames"][0]["objects"][0]
        self.assertEqual(obj["class"], "chair")
        self.assertFalse(obj["fixture"])
        self.assertTrue(obj["fixture_candidate"])

    def test_new_text_vectors_reuse_existing_vision_session(self):
        get_scene_classifier.cache_clear()
        self.addCleanup(get_scene_classifier.cache_clear)
        base = SimpleNamespace(session=object())
        with tempfile.TemporaryDirectory() as directory:
            labels = np.array(
                [label for label, phrases in SCENE_PROMPTS.items() for _ in phrases]
            )
            np.savez(
                Path(directory) / "scene_text_features.npz",
                features=np.ones((len(labels), 4)),
                labels=labels,
            )
            with patch(
                "backend.pipeline.perception.anchors.get_fixture_classifier",
                return_value=base,
            ):
                result = get_scene_classifier(directory)
        self.assertIs(result.session, base.session)
        self.assertIsNot(result, base)

    def test_array_proposal_can_overlap_a_json_list_fixture(self):
        facts = dict(
            fixtures=[
                dict(id=1, **{"class": "counter_machine", "bbox": [0.2, 0.2, 0.4, 0.4]})
            ],
            frames=[],
        )
        classifier = Mock()
        track = dict(box=np.asarray([0.2, 0.2, 0.4, 0.4]))
        with patch(
            "backend.pipeline.perception.anchors.small_object_proposals",
            return_value=([track], []),
        ):
            discover_scene_anchors("unused.mov", facts, Mock(), classifier)
        classifier.classify.assert_not_called()
        self.assertEqual(facts["scene_anchor_search"]["missing_required"], ["safe"])


if __name__ == "__main__":
    unittest.main()
