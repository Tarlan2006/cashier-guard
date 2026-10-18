import unittest
import cv2
import numpy as np
from scene_mvp.document_search import SPEC, crop_box, iou, templates, search, diverse_frames


class SearchTests(unittest.TestCase):
    def test_finds_synthetic_reference_without_target_box(self):
        rng = np.random.default_rng(42)
        patch = rng.integers(0, 255, (16, 24, 3), dtype=np.uint8)
        image = np.full((200, 300, 3), 120, np.uint8)
        image[85:101, 95:119] = patch
        predictions = search(image, templates(patch))
        self.assertGreater(iou(predictions[0]['bbox'], [95/300, 85/200, 119/300, 101/200]), .95)
        self.assertFalse(SPEC['absence_decision_allowed'])

    def test_blank_reference_rejected(self):
        with self.assertRaises(ValueError):
            templates(np.zeros((20, 20, 3), np.uint8))

    def test_invalid_box_rejected(self):
        with self.assertRaises(ValueError):
            crop_box(np.zeros((100, 100, 3), np.uint8), [.5, .3, .2, .9])

    def test_rank_selection_is_diverse_not_ground_truth_window(self):
        rows = [{'timestamp_sec': t, 'proposals': [{'reference_similarity': s}]} for t, s in [(1, .9), (1.5, .8), (3, .7), (6, .5)]]
        self.assertEqual([r['timestamp_sec'] for r in diverse_frames(rows, count=3)], [1, 3, 6])


if __name__ == '__main__':
    unittest.main()
