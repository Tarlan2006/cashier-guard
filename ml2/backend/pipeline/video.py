"""Local video-only decoding. Source times are frame.pts * frame.time_base.

PTS are never inferred from frame numbers or FPS and are not rebased to zero:
normalized MP4 may retain an empty leading edit or variable frame spacing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Sequence

import av
from av.video.reformatter import Colorspace
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
    """Read presentation timestamps and rotate raw pixels exactly once.

    FPS and frame_count are informational metadata only. Sampling, seeking,
    evidence and the video end time use timestamp/time-base units.
    Only the first video stream is decoded; audio is never decoded.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._container = None
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        try:
            self._open()
            first = next(self._container.decode(self._stream))
            self._first_time = self._source_time(first)
            angle = float(first.rotation)
            if not math.isfinite(angle) or abs(angle / 90 - round(angle / 90)) > 1e-6:
                raise ValueError("Unsupported video rotation")
            # PyAV's display matrix is counter-clockwise; metadata here keeps
            # the existing clockwise convention used by scene/debug code.
            self._rotation = (-int(round(angle))) % 360
            width, height = first.width, first.height
            if self._rotation in (90, 270):
                width, height = height, width
            if self._stream.duration is not None:
                start = float((self._stream.start_time or 0) * self._stream.time_base)
                end = start + float(self._stream.duration * self._stream.time_base)
            elif self._container.duration is not None:
                start = float((self._container.start_time or 0) / av.time_base)
                end = start + float(self._container.duration / av.time_base)
            else:
                raise ValueError("Video has no timestamp-based duration")
            if (
                not math.isfinite(end)
                or end <= self._first_time
                or min(width, height) <= 0
            ):
                raise ValueError("Invalid video duration or dimensions")
            self.metadata = VideoMetadata(
                end,
                width,
                height,
                float(self._stream.average_rate or 0),
                self._rotation,
                int(self._stream.frames or 0),
            )
        except (av.FFmpegError, StopIteration) as exc:
            self.close()
            raise ValueError("Cannot decode video") from exc
        except Exception:
            self.close()
            raise

    def _open(self) -> None:
        self._container = av.open(
            str(self.path), mode="r", options={"protocol_whitelist": "file"}
        )
        if not self._container.streams.video:
            raise ValueError("Input has no video stream")
        self._stream = self._container.streams.video[0]
        # Decoding and model inference share the CPU. Limit decode concurrency
        # alongside the resident detector / scene encoder thread pools.
        self._stream.codec_context.thread_count = 1

    def __enter__(self) -> VideoReader:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._container is not None:
            self._container.close()
            self._container = None

    @staticmethod
    def _source_time(frame) -> float:
        if frame.pts is None or frame.time_base is None:
            raise ValueError("Video frame has no presentation timestamp")
        value = float(frame.pts * frame.time_base)
        if not math.isfinite(value) or value < 0:
            raise ValueError("Invalid video frame presentation timestamp")
        return value

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

    def _bgr(self, frame: av.VideoFrame) -> np.ndarray:
        # Preserve the BT.601 YUV->BGR conversion used by the former OpenCV
        # reader and therefore by existing detector/appearance thresholds.
        # PyAV otherwise follows the source's matrix tags, changing pixels
        # and even track associations on the same source frames. This is a
        # pipeline compatibility choice, not a claim of colorimetric accuracy.
        # Source color range remains automatic; PTS are unaffected.
        return self._orient(
            frame.to_ndarray(format="bgr24", src_colorspace=Colorspace.ITU601)
        )

    def _rewind(self) -> None:
        # Reopening is a reliable fallback for MOV files with a broken seek
        # index and flushes decoder state after earlier random-access reads.
        self.close()
        self._open()

    def _frames(self):
        previous = -1.0
        for frame in self._container.decode(self._stream):
            timestamp = self._source_time(frame)
            if timestamp < previous:
                raise ValueError(
                    "Decoder returned non-monotonic presentation timestamps"
                )
            previous = timestamp
            yield timestamp, frame

    def iter_samples(
        self, interval_sec: float | Callable[[float], float] = 0.5
    ) -> Iterator[VideoSample]:
        if not callable(interval_sec) and (
            not math.isfinite(interval_sec) or interval_sec <= 0
        ):
            raise ValueError("interval_sec must be finite and positive")
        self._rewind()
        target = self._first_time
        for actual, raw in self._frames():
            if actual + 1e-8 < target:
                continue
            yield VideoSample(
                target, actual, self._bgr(raw)
            )
            # A source gap has no invented frames. Each decoded image is
            # emitted at most once, even if it crosses several grid points.
            while target <= actual + 1e-8:
                step = (
                    float(interval_sec(target))
                    if callable(interval_sec)
                    else interval_sec
                )
                if not math.isfinite(step) or step <= 0:
                    raise ValueError(
                        "Adaptive sample interval must be positive and finite"
                    )
                target += step

    def read_at(self, time_sec: float) -> VideoSample:
        """Return the nearest real frame, seeking in stream time-base units.

        A broken/missing seek index falls back once to sequential decoding.
        Requests beyond the end retain the last real PTS, never an FPS estimate.
        """
        if not math.isfinite(time_sec):
            raise ValueError("time_sec must be finite")
        target = max(self._first_time, float(time_sec))

        def scan():
            best = None
            first_time = None
            for actual, frame in self._frames():
                if first_time is None:
                    first_time = actual
                if best is None or abs(actual - target) < abs(best[0] - target):
                    best = (actual, frame)
                if actual + 1e-8 >= target:
                    break
            return best, first_time

        try:
            ticks = math.floor(target / self._stream.time_base)
            self._container.seek(
                ticks, stream=self._stream, backward=True, any_frame=False
            )
            best, first_time = scan()
        except av.FFmpegError:
            best, first_time = None, None
        if best is None or first_time > target + 1e-8:
            self._rewind()
            best, _ = scan()
        if best is None:
            raise ValueError("Cannot decode evidence frame")
        actual, frame = best
        return VideoSample(
            target, actual, self._bgr(frame)
        )


def extract_jpegs(
    path: str | Path, times_sec: Sequence[float], *, quality: int = 90
) -> list[tuple[float, bytes]]:
    """Return original oriented JPEGs paired with their presentation times."""
    if not isinstance(quality, int) or not 1 <= quality <= 100:
        raise ValueError("JPEG quality must be an integer in [1, 100]")
    images = []
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
