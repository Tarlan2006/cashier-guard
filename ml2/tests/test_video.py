"""PTS, source orientation and JPEG contracts; synthetic video only."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import av
import cv2
import numpy as np
from PIL import Image

from backend.pipeline.video import VideoReader, extract_jpegs
from scripts.debug_perception import create_contact_sheet
from video_fixtures import normalized_mp4


class Frame:
    def __init__(self, t, index, rotation):
        self.pts = None if t is None else round(t * 1000)
        self.time_base = Fraction(1, 1000)
        self.rotation = rotation
        self.width, self.height = 4, 2
        self.raw = (
            np.arange(24, dtype=np.uint8).reshape(2, 4, 3)
            if rotation
            else np.full((2, 4, 3), index * 20, np.uint8)
        )

    def to_ndarray(self, format):
        assert format == "bgr24"
        return self.raw.copy()


class Container:
    def __init__(self, times=(0, 0.5, 1), rotation=0, broken_seek=False):
        self.times, self.rotation, self.broken_seek = times, rotation, broken_seek
        self.after_seek, self.closed = False, False
        stream = SimpleNamespace(
            time_base=Fraction(1, 1000),
            start_time=0,
            duration=round((max(t for t in times if t is not None) + 0.5) * 1000),
            average_rate=Fraction(999),
            frames=len(times),
            codec_context=SimpleNamespace(thread_count=0),
        )
        self.streams = SimpleNamespace(video=[stream])
        self.duration, self.start_time = stream.duration * 1000, 0

    def decode(self, stream):
        if self.after_seek and self.broken_seek:
            return
        for index, t in enumerate(self.times):
            yield Frame(t, index, self.rotation)

    def seek(self, *args, **kwargs):
        self.after_seek = True

    def close(self):
        self.closed = True


class VideoReaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "synthetic.avi"

    def _write_video(self):
        writer = cv2.VideoWriter(
            str(self.path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (64, 32)
        )
        self.assertTrue(writer.isOpened())
        for index in range(21):
            writer.write(np.full((32, 64, 3), index * 10, np.uint8))
        writer.release()

    def factory(self, **options):
        containers = []

        def open_container(*args, **kwargs):
            container = Container(**options)
            containers.append(container)
            return container

        return containers, open_container

    def test_rotation_is_applied_once_and_dimensions_are_oriented(self):
        self.path.touch()
        containers, factory = self.factory(rotation=-90)
        with patch("backend.pipeline.video.av.open", side_effect=factory):
            with VideoReader(self.path) as reader:
                self.assertEqual(
                    (reader.metadata.width, reader.metadata.height), (2, 4)
                )
                self.assertEqual(reader.metadata.rotation_deg, 90)
                samples = list(reader.iter_samples())
        self.assertTrue(all(c.closed for c in containers))
        np.testing.assert_array_equal(
            samples[0].frame_bgr,
            cv2.rotate(
                np.arange(24, dtype=np.uint8).reshape(2, 4, 3), cv2.ROTATE_90_CLOCKWISE
            ),
        )

    def test_grid_actual_timestamps_and_boundary_jpegs(self):
        self._write_video()
        with VideoReader(self.path) as reader:
            samples = list(reader.iter_samples())
            self.assertAlmostEqual(reader.metadata.duration_sec, 2.1, places=5)
        self.assertEqual([s.timestamp_sec for s in samples], [0, 0.5, 1, 1.5, 2])
        for sample in samples:
            self.assertAlmostEqual(
                sample.timestamp_sec, sample.actual_timestamp_sec, places=5
            )
        jpegs = extract_jpegs(self.path, [-10, 0.5, 1000])
        self.assertAlmostEqual(jpegs[0][0], 0)
        self.assertAlmostEqual(jpegs[-1][0], 2)
        for _, data in jpegs:
            self.assertEqual(
                cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR).shape,
                (32, 64, 3),
            )

    def test_pts_override_incorrect_fps_and_do_not_duplicate_missing_frames(self):
        self.path.touch()
        _, factory = self.factory(times=(0, 0.2, 0.9, 1.4))
        with patch("backend.pipeline.video.av.open", side_effect=factory):
            with VideoReader(self.path) as reader:
                self.assertEqual(reader.metadata.fps, 999)
                self.assertEqual(
                    [s.actual_timestamp_sec for s in reader.iter_samples()],
                    [0, 0.9, 1.4],
                )

    def test_missing_pts_is_rejected_instead_of_using_frame_number(self):
        self.path.touch()
        _, factory = self.factory(times=(None, 0.5, 1))
        with patch("backend.pipeline.video.av.open", side_effect=factory):
            with self.assertRaisesRegex(ValueError, "presentation timestamp"):
                VideoReader(self.path)

    def test_non_monotonic_pts_is_rejected(self):
        self.path.touch()
        _, factory = self.factory(times=(0, 0.5, 0.25))
        with patch("backend.pipeline.video.av.open", side_effect=factory):
            with VideoReader(self.path) as reader:
                with self.assertRaisesRegex(ValueError, "non-monotonic"):
                    list(reader.iter_samples())

    def test_real_h264_yuv420p_vfr_sampling_and_evidence_use_pts(self):
        self.path = self.path.with_suffix(".mp4")
        normalized_mp4(self.path)
        with av.open(str(self.path)) as source:
            self.assertEqual(source.streams.video[0].codec_context.name, "h264")
            self.assertEqual(source.streams.video[0].codec_context.pix_fmt, "yuv420p")
            self.assertEqual(len(source.streams.audio), 0)
        with VideoReader(self.path) as reader:
            samples = list(reader.iter_samples())
        np.testing.assert_allclose(
            [s.actual_timestamp_sec for s in samples], [0, 0.9, 1, 1.6], atol=1e-6
        )
        np.testing.assert_allclose(
            [t for t, _ in extract_jpegs(self.path, [0.9, 1.6])], [0.9, 1.6], atol=1e-6
        )

    def test_real_leading_edit_is_not_rebased_to_zero(self):
        self.path = self.path.with_suffix(".mp4")
        normalized_mp4(self.path, (2000, 2100, 2200, 2900, 3000, 3600))
        with VideoReader(self.path) as reader:
            self.assertGreater(reader.metadata.duration_sec, 3.6)
            samples = list(reader.iter_samples())
            self.assertAlmostEqual(reader.read_at(3.6).actual_timestamp_sec, 3.6)
        np.testing.assert_allclose(
            [s.actual_timestamp_sec for s in samples], [2, 2.9, 3, 3.6], atol=1e-6
        )

    def test_real_rotation_keeps_oriented_dimensions(self):
        self.path = self.path.with_suffix(".mp4")
        normalized_mp4(self.path, rotation=90)
        with VideoReader(self.path) as reader:
            self.assertEqual((reader.metadata.width, reader.metadata.height), (32, 64))
            self.assertEqual(reader.read_at(0).frame_bgr.shape, (64, 32, 3))

    def test_contact_sheet_reuses_facts_without_detector(self):
        self._write_video()
        facts = {
            "frames": [
                dict(
                    timestamp_sec=t,
                    persons=[
                        dict(
                            id=1,
                            role="unknown",
                            bbox=[0.1, 0.1, 0.6, 0.8],
                            confidence=0.9,
                        )
                    ],
                    objects=[],
                    counter=dict(status="uncalibrated", changes=[]),
                )
                for t in (0, 1, 2)
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

    def test_invalid_timing_is_rejected(self):
        self._write_video()
        with VideoReader(self.path) as reader:
            with self.assertRaises(ValueError):
                list(reader.iter_samples(0))
            with self.assertRaises(ValueError):
                reader.read_at(float("nan"))

    def test_end_seek_failure_decodes_from_start_with_real_pts(self):
        self.path.touch()
        containers, factory = self.factory(times=(0, 0.5, 1, 1.5, 2), broken_seek=True)
        with patch("backend.pipeline.video.av.open", side_effect=factory):
            with VideoReader(self.path) as reader:
                sample = reader.read_at(2)
        self.assertEqual(len(containers), 2)
        self.assertEqual(sample.actual_timestamp_sec, 2)
        self.assertTrue(np.all(sample.frame_bgr == 80))

    def test_broken_seek_index_reopens_once_and_retains_actual_frame(self):
        self.path.touch()
        containers, factory = self.factory(
            times=tuple(i * 0.5 for i in range(9)), broken_seek=True
        )
        with patch("backend.pipeline.video.av.open", side_effect=factory):
            with VideoReader(self.path) as reader:
                sample = reader.read_at(3.75)
        self.assertEqual(len(containers), 2)
        self.assertEqual(sample.timestamp_sec, 3.75)
        self.assertEqual(sample.actual_timestamp_sec, 3.5)
        self.assertTrue(np.all(sample.frame_bgr == 140))


if __name__ == "__main__":
    unittest.main()
