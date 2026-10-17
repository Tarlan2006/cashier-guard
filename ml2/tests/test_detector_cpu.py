"""Numerical contracts for the lightweight CPU adapter; no model is loaded."""

import unittest
from unittest.mock import Mock, patch

import numpy as np

from backend.pipeline.perception.config import PerceptionConfig
from backend.pipeline.perception.detector import (
    ONNXPersonObjectDetector,
    _cached_detector,
    get_detector,
    preprocess_bgr,
)


class DetectorCPUContracts(unittest.TestCase):
    def test_preprocessing_is_rgb_unit_range_and_nchw(self) -> None:
        frame = np.full((2, 3, 3), [0, 127, 255], dtype=np.uint8)
        values = preprocess_bgr(frame, 384)
        self.assertEqual(values.shape, (1, 3, 384, 384))
        self.assertEqual(values.dtype, np.float32)
        self.assertTrue(values.flags.c_contiguous)
        np.testing.assert_allclose(values[0, :, 0, 0], [1, 127 / 255, 0], atol=1e-7)

    def test_logits_become_normalized_coco_detections(self) -> None:
        detector = object.__new__(ONNXPersonObjectDetector)
        detector.config = PerceptionConfig()
        detector.labels = {0: "person", 1: "handbag"}
        detector.session = Mock()
        detector.session.run.return_value = [
            np.asarray([[[4.0, -4.0], [-4.0, 3.0]]], dtype=np.float32),
            np.asarray(
                [[[0.25, 0.25, 0.2, 0.2], [0.75, 0.75, 0.2, 0.2]]], dtype=np.float32
            ),
        ]
        result = detector.predict_batch([np.zeros((30, 40, 3), dtype=np.uint8)])[0]
        self.assertEqual([item["class"] for item in result], ["person", "handbag"])
        np.testing.assert_allclose(
            result[0]["bbox"], [0.15, 0.15, 0.35, 0.35], atol=1e-6
        )
        self.assertAlmostEqual(result[0]["confidence"], 0.982014, places=6)
        self.assertEqual(
            detector.session.run.call_args.args[0], ["logits", "pred_boxes"]
        )

    def test_repeated_api_calls_reuse_only_the_same_configuration(self) -> None:
        _cached_detector.cache_clear()
        try:
            with patch(
                "backend.pipeline.perception.detector.ONNXPersonObjectDetector"
            ) as factory:
                first = object()
                second = object()
                factory.side_effect = [first, second]
                self.assertIs(get_detector(PerceptionConfig()), first)
                self.assertIs(get_detector(PerceptionConfig()), first)
                self.assertEqual(factory.call_count, 1)
                self.assertIs(
                    get_detector(PerceptionConfig(person_threshold=0.6)), second
                )
                self.assertEqual(factory.call_count, 2)
        finally:
            _cached_detector.cache_clear()


if __name__ == "__main__":
    unittest.main()
