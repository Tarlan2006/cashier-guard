"""Video grid, orientation and JPEG contract checks, using local synthetic pixels."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from backend.pipeline.video import VideoReader, extract_jpegs
from scripts.debug_perception import create_contact_sheet


class RotatedCapture:
    def __init__(self, *_: object) -> None:
        self.index = -1
        self.auto = 1
        self.raw = np.arange(2 * 4 * 3, dtype=np.uint8).reshape(2, 4, 3)
        self.released = False

    def isOpened(self) -> bool:
        return True

    def release(self) -> None:
        self.released = True

    def get(self, prop: int) -> float:
        return float(
            {
                cv2.CAP_PROP_ORIENTATION_META: 90,
                cv2.CAP_PROP_ORIENTATION_AUTO: self.auto,
                cv2.CAP_PROP_FPS: 2,
                cv2.CAP_PROP_FRAME_COUNT: 3,
                cv2.CAP_PROP_FRAME_WIDTH: 4,
                cv2.CAP_PROP_FRAME_HEIGHT: 2,
                cv2.CAP_PROP_POS_MSEC: max(0, self.index) * 500,
                cv2.CAP_PROP_POS_FRAMES: self.index + 1,
            }.get(prop, 0)
        )

    def set(self, prop: int, value: float) -> bool:
        if prop == cv2.CAP_PROP_ORIENTATION_AUTO:
            self.auto = value
        elif prop == cv2.CAP_PROP_POS_FRAMES:
            self.index = int(value) - 1
        elif prop == cv2.CAP_PROP_POS_MSEC:
            self.index = round(value / 500) - 1
        return True

    def grab(self) -> bool:
        self.index += 1
        return self.index < 3

    def retrieve(self) -> tuple[bool, np.ndarray]:
        return True, self.raw.copy()

    def read(self) -> tuple[bool, np.ndarray | None]:
        return self.retrieve() if self.grab() else (False, None)


class BrokenEndSeekCapture(RotatedCapture):
    """The last frame is sequentially readable but cannot be sought directly."""

    def __init__(self, rewind_only: bool = False, frame_count: int = 5) -> None:
        super().__init__()
        self.rewind_only = rewind_only
        self.frame_count = frame_count
        self.rewinds = 0

    def get(self, prop: int) -> float:
        if prop == cv2.CAP_PROP_ORIENTATION_META:
            return 0.0
        if prop == cv2.CAP_PROP_FRAME_COUNT:
            return float(self.frame_count)
        return super().get(prop)

    def set(self, prop: int, value: float) -> bool:
        super().set(prop, value)
        if prop in (cv2.CAP_PROP_POS_MSEC, cv2.CAP_PROP_POS_FRAMES):
            if prop == cv2.CAP_PROP_POS_FRAMES and value == 0:
                self.rewinds += 1
            requested_index = (
                round(value / 500) if prop == cv2.CAP_PROP_POS_MSEC else int(value)
            )
            if requested_index >= 4 or self.rewind_only and requested_index > 0:
                self.index = self.frame_count  # Reports seek success, then EOF.
        return True

    def grab(self) -> bool:
        self.index += 1
        return self.index < self.frame_count

    def retrieve(self) -> tuple[bool, np.ndarray]:
        return True, np.full((2, 4, 3), self.index * 20, np.uint8)


class VideoReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "synthetic.avi"

    def _write_video(self) -> None:
        writer = cv2.VideoWriter(
            str(self.path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (64, 32)
        )
        self.assertTrue(writer.isOpened())
        for index in range(21):
            frame = np.zeros((32, 64, 3), np.uint8)
            frame[:, :32] = (index * 10, 20, 230)
            frame[:, 32:] = (30, 180, index * 10)
            writer.write(frame)
        writer.release()

    def test_rotation_is_applied_once_and_dimensions_are_oriented(self) -> None:
        self.path.touch()
        capture = RotatedCapture()
        with patch("backend.pipeline.video.cv2.VideoCapture", return_value=capture):
            with VideoReader(self.path) as reader:
                self.assertEqual(
                    (reader.metadata.width, reader.metadata.height), (2, 4)
                )
                self.assertEqual(reader.metadata.rotation_deg, 90)
                samples = list(reader.iter_samples())
        self.assertEqual(capture.auto, 0)
        self.assertTrue(capture.released)
        self.assertEqual([sample.timestamp_sec for sample in samples], [0, 0.5, 1.0])
        np.testing.assert_array_equal(
            samples[0].frame_bgr, cv2.rotate(capture.raw, cv2.ROTATE_90_CLOCKWISE)
        )

    def test_grid_actual_timestamps_and_boundary_jpegs(self) -> None:
        self._write_video()
        with VideoReader(self.path) as reader:
            samples = list(reader.iter_samples())
            self.assertAlmostEqual(reader.metadata.duration_sec, 2.1, places=5)
        self.assertEqual(
            [sample.timestamp_sec for sample in samples], [0, 0.5, 1, 1.5, 2]
        )
        for sample in samples:
            self.assertAlmostEqual(
                sample.timestamp_sec, sample.actual_timestamp_sec, places=5
            )
            self.assertEqual(sample.frame_bgr.shape, (32, 64, 3))
        jpegs = extract_jpegs(self.path, [-10, 0.5, 1000])
        self.assertEqual(len(jpegs), 3)
        self.assertAlmostEqual(jpegs[0][0], 0)
        self.assertAlmostEqual(jpegs[-1][0], 2)
        for _, data in jpegs:
            decoded = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            self.assertEqual(decoded.shape, (32, 64, 3))

    def test_contact_sheet_reuses_facts_without_detector(self) -> None:
        self._write_video()
        facts = {
            "frames": [
                {
                    "timestamp_sec": value,
                    "persons": [
                        {
                            "id": 1,
                            "role": "unknown",
                            "bbox": [0.1, 0.1, 0.6, 0.8],
                            "confidence": 0.9,
                        }
                    ],
                    "objects": [],
                    "counter": {"status": "uncalibrated", "changes": []},
                }
                for value in (0.0, 1.0, 2.0)
            ]
        }
        output = create_contact_sheet(
            self.path,
            facts,
            self.path.parent / "contact.jpg",
            max_frames=3,
            columns=2,
            thumb_width=160,
        )
        with Image.open(output) as sheet:
            self.assertEqual(sheet.format, "JPEG")
            self.assertGreater(sheet.width, 320)
        with self.assertRaises(ValueError):
            create_contact_sheet(self.path, {**facts, "video": {"name": "other.avi"}})

    def test_invalid_timing_is_rejected(self) -> None:
        self._write_video()
        with VideoReader(self.path) as reader:
            with self.assertRaises(ValueError):
                list(reader.iter_samples(interval_sec=0))
            with self.assertRaises(ValueError):
                reader.read_at(float("nan"))

    def test_end_seek_failure_decodes_forward_from_earlier_frame(self) -> None:
        self.path.touch()
        with patch(
            "backend.pipeline.video.cv2.VideoCapture",
            return_value=BrokenEndSeekCapture(),
        ):
            with VideoReader(self.path) as reader:
                sample = reader.read_at(2.0)
        self.assertEqual(sample.actual_timestamp_sec, 2.0)
        self.assertTrue(np.all(sample.frame_bgr == 80))

    def test_broken_seek_index_rewinds_once_and_retains_actual_frame(self) -> None:
        self.path.touch()
        capture = BrokenEndSeekCapture(rewind_only=True, frame_count=9)
        with patch("backend.pipeline.video.cv2.VideoCapture", return_value=capture):
            with VideoReader(self.path) as reader:
                sample = reader.read_at(3.75)
        self.assertEqual(capture.rewinds, 1)
        self.assertEqual(sample.timestamp_sec, 3.75)
        self.assertEqual(sample.actual_timestamp_sec, 3.5)
        self.assertTrue(np.all(sample.frame_bgr == 140))


if __name__ == "__main__":
    unittest.main()
