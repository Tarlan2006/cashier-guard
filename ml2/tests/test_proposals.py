"""Small-object search contracts; synthetic images, no model or network."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock

import numpy as np

from backend.pipeline.perception.proposals import (
    small_object_proposals,
    discover_counter_machine,
)


class Reader:
    def __init__(self, _path):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def read_at(self, timestamp):
        return SimpleNamespace(
            frame_bgr=np.zeros((200, 100, 3), np.uint8), actual_timestamp_sec=timestamp
        )


class ProposalTests(unittest.TestCase):
    def test_small_static_proposals_need_distinct_views_and_ignore_people(self):
        class Detector:
            def predict_batch(self, frames, *, object_threshold):
                assert object_threshold == 0.20
                if frames[0].shape[:2] != (200, 100):
                    return [[]]
                return [
                    [
                        {
                            "class": "tvmonitor",
                            "bbox": [0.3, 0.4, 0.5, 0.6],
                            "confidence": 0.4,
                        },
                        {
                            "class": "person",
                            "bbox": [0.1, 0.1, 0.2, 0.2],
                            "confidence": 0.9,
                        },
                        {
                            "class": "diningtable",
                            "bbox": [0.0, 0.0, 1.0, 1.0],
                            "confidence": 0.9,
                        },
                    ]
                ]

        facts = {"frames": [{"timestamp_sec": i * 0.5} for i in range(20)]}
        with patch("backend.pipeline.perception.proposals.VideoReader", Reader):
            tracks, views = small_object_proposals("unused.mov", facts, Detector())
        self.assertEqual(len(views), 3)
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["classes"], {"tvmonitor"})
        self.assertEqual(len(tracks[0]["views"]), 3)
        self.assertLessEqual(np.prod(tracks[0]["box"][2:] - tracks[0]["box"][:2]), 0.1)

    def test_repeated_source_frame_cannot_establish_stationary_proposal(self):
        class ReusedReader(Reader):
            def read_at(self, timestamp):
                return super().read_at(1.0)

        detector = Mock()
        detector.predict_batch.return_value = [
            [{"class": "suitcase", "bbox": [0.3, 0.4, 0.5, 0.6], "confidence": 0.9}]
        ]
        with patch("backend.pipeline.perception.proposals.VideoReader", ReusedReader):
            tracks, views = small_object_proposals(
                "unused.mov",
                {"frames": [{"timestamp_sec": i * 0.5} for i in range(20)]},
                detector,
            )
        self.assertEqual(len(views), 1)
        self.assertEqual(tracks, [])

    def test_existing_counter_machine_avoids_redundant_tiled_inference(self):
        facts = {
            "fixtures": [{"class": "counter_machine", "bbox": [0.3, 0.4, 0.5, 0.6]}]
        }
        detector, classifier = Mock(), Mock()
        discover_counter_machine("unused.mov", facts, detector, classifier)
        detector.predict_batch.assert_not_called()
        classifier.classify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
