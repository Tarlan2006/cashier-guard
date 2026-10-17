"""Local, image-only video decoding with one explicit orientation transform.

Timeline timestamps are on an exact requested grid; ``actual_timestamp_sec``
always identifies the decoded source frame. No audio streams are opened.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Sequence

import cv2
import numpy as np


@dataclass(frozen=True)
class VideoMetadata:
    duration_sec: float
    width: int
    height: int
    fps: float
    rotation_deg: int
    frame_count: int


@dataclass(frozen=True)
class VideoSample:
    timestamp_sec: float
    actual_timestamp_sec: float
    frame_bgr: np.ndarray


class VideoReader:
    """Decode a local video; normalized boxes refer to the oriented image.

    OpenCV's implicit orientation is disabled and checked before decoding.
    Rotation metadata is then applied manually, exactly once. An unsupported
    backend that cannot disable a nonzero automatic rotation is rejected.
    ``iter_samples`` selects the first source frame at or after each target;
    the offset is normally at most one source-frame period, including VFR.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        self._capture = cv2.VideoCapture(str(self.path))
        if not self._capture.isOpened():
            self._capture.release()
            raise ValueError(f"Cannot decode video: {self.path}")
        rotation = self._capture.get(cv2.CAP_PROP_ORIENTATION_META)
        self._rotation = int(round(rotation)) % 360 if math.isfinite(rotation) else 0
        if self._rotation not in (0, 90, 180, 270):
            self.close()
            raise ValueError(f"Unsupported video rotation: {rotation}")
        self._capture.set(cv2.CAP_PROP_ORIENTATION_AUTO, 0)
        if self._rotation and self._capture.get(cv2.CAP_PROP_ORIENTATION_AUTO) > 0.5:
            self.close()
            raise RuntimeError("Decoder cannot disable automatic orientation reliably")

        fps = float(self._capture.get(cv2.CAP_PROP_FPS))
        count = int(self._capture.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(self._capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(self._capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if not math.isfinite(fps) or fps <= 0 or count <= 0 or min(width, height) <= 0:
            self.close()
            raise ValueError(f"Invalid video timing or dimensions: {self.path}")
        if self._rotation in (90, 270):
            width, height = height, width
        self.metadata = VideoMetadata(
            count / fps, width, height, fps, self._rotation, count
        )

    def __enter__(self) -> VideoReader:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._capture.release()

    def _orient(self, frame: np.ndarray) -> np.ndarray:
        rotations = {
            90: cv2.ROTATE_90_CLOCKWISE,
            180: cv2.ROTATE_180,
            270: cv2.ROTATE_90_COUNTERCLOCKWISE,
        }
        if self._rotation:
            frame = cv2.rotate(frame, rotations[self._rotation])
        if frame.shape[:2] != (self.metadata.height, self.metadata.width):
            raise RuntimeError(
                "Decoded dimensions disagree with video orientation metadata"
            )
        return frame

    def _source_time(self, index: int) -> float:
        milliseconds = float(self._capture.get(cv2.CAP_PROP_POS_MSEC))
        if (
            math.isfinite(milliseconds)
            and milliseconds >= 0
            and (index == 0 or milliseconds > 0)
        ):
            return milliseconds / 1000.0
        return index / self.metadata.fps

    def iter_samples(
        self, interval_sec: float | Callable[[float], float] = 0.5
    ) -> Iterator[VideoSample]:
        if not callable(interval_sec) and (
            not math.isfinite(interval_sec) or interval_sec <= 0
        ):
            raise ValueError("interval_sec must be finite and positive")
        self._capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
        sample_index = 0
        target = 0.0
        source_index = 0
        last_time = -1.0
        while self._capture.grab():
            actual = self._source_time(source_index)
            if actual < last_time:
                raise RuntimeError("Decoder returned non-monotonic source timestamps")
            last_time = actual
            final_frame = source_index == self.metadata.frame_count - 1
            if (
                actual + 1e-8 >= target
                or final_frame
                and target < self.metadata.duration_sec
            ):
                ok, raw = self._capture.retrieve()
                if not ok:
                    raise RuntimeError(f"Cannot retrieve video frame {source_index}")
                frame = self._orient(raw)
                # A gap in source timestamps may cover multiple timeline steps.
                while target < self.metadata.duration_sec and (
                    target <= actual + 1e-8 or final_frame
                ):
                    yield VideoSample(float(target), float(actual), frame)
                    sample_index += 1
                    step = (
                        float(interval_sec(float(target)))
                        if callable(interval_sec)
                        else interval_sec
                    )
                    if not math.isfinite(step) or step <= 0:
                        raise ValueError(
                            "Adaptive sample interval must be positive and finite"
                        )
                    target += step
            source_index += 1

    def read_at(self, time_sec: float) -> VideoSample:
        """Seek to a timestamp, recovering MOV/VFR failures near the clip end.

        A timestamp seek and a frame-index seek are tried first. If both fail,
        seek a little earlier and decode forward; finally rewind if the index
        is unusable. The retained image always carries its decoded timestamp.
        """
        if not math.isfinite(time_sec):
            raise ValueError("time_sec must be finite")
        last_index = self.metadata.frame_count - 1
        last_estimate = last_index / self.metadata.fps
        target = min(max(0.0, float(time_sec)), last_estimate)

        def decode() -> VideoSample | None:
            ok, raw = self._capture.read()
            if not ok:
                return None
            index = max(0, int(round(self._capture.get(cv2.CAP_PROP_POS_FRAMES))) - 1)
            return VideoSample(target, self._source_time(index), self._orient(raw))

        for prop, value in (
            (cv2.CAP_PROP_POS_MSEC, target * 1000.0),
            (
                cv2.CAP_PROP_POS_FRAMES,
                min(last_index, round(target * self.metadata.fps)),
            ),
        ):
            if self._capture.set(prop, value):
                sample = decode()
                if sample is not None:
                    return sample

        best: VideoSample | None = None

        def scan(max_frames: int) -> bool:
            """Keep the nearest available source image; stop after the target."""
            nonlocal best
            previous_time = -1.0
            for _ in range(max_frames):
                sample = decode()
                if sample is None:
                    break
                if sample.actual_timestamp_sec < previous_time:
                    raise RuntimeError(
                        "Decoder returned non-monotonic source timestamps"
                    )
                previous_time = sample.actual_timestamp_sec
                if best is None or abs(sample.actual_timestamp_sec - target) < abs(
                    best.actual_timestamp_sec - target
                ):
                    best = sample
                if sample.actual_timestamp_sec + 1e-8 >= target:
                    return True
            return False

        # These attempts are bounded to a few seconds, including keyframe slack.
        attempted: set[tuple[int, float]] = set()
        for backoff in (0.5, 1.0, 2.0):
            earlier = max(0.0, target - backoff)
            for prop, value in (
                (cv2.CAP_PROP_POS_MSEC, earlier * 1000.0),
                (cv2.CAP_PROP_POS_FRAMES, max(0, int(earlier * self.metadata.fps))),
            ):
                key = (prop, float(value))
                if key in attempted:
                    continue
                attempted.add(key)
                if self._capture.set(prop, value) and scan(
                    math.ceil((backoff + 1) * self.metadata.fps) + 4
                ):
                    assert best is not None
                    return best
        # Broken end-of-file seek tables can still have perfectly readable
        # sequential frames. Rewind once, never repeatedly scan the whole clip.
        if self._capture.set(cv2.CAP_PROP_POS_FRAMES, 0):
            scan(self.metadata.frame_count + 1)
        if best is not None:
            return best
        raise RuntimeError(
            f"Cannot decode evidence frame at {target:.3f}s: {self.path}"
        )


def extract_jpegs(
    path: str | Path, times_sec: Sequence[float], *, quality: int = 90
) -> list[tuple[float, bytes]]:
    """Return one oriented JPEG and its actual timestamp per requested time.

    Boundary requests may legitimately return the same frame more than once.
    """
    if not isinstance(quality, int) or not 1 <= quality <= 100:
        raise ValueError("JPEG quality must be an integer in [1, 100]")
    images: list[tuple[float, bytes]] = []
    with VideoReader(path) as reader:
        for timestamp in times_sec:
            sample = reader.read_at(float(timestamp))
            ok, encoded = cv2.imencode(
                ".jpg", sample.frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, quality]
            )
            if not ok:
                raise RuntimeError("JPEG encoder failed")
            images.append((sample.actual_timestamp_sec, encoded.tobytes()))
    return images
