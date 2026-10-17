"""Local, geometry-only person tracking; no appearance or identity features."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Sequence

import numpy as np
from scipy.optimize import linear_sum_assignment
from .appearance import color_distance


def validated_bbox(value: Sequence[float]) -> np.ndarray:
    """Return a finite, nonempty normalized [x1, y1, x2, y2] box."""
    box = np.asarray(value, dtype=np.float64)
    if box.shape != (4,) or not np.all(np.isfinite(box)):
        raise ValueError("bbox must contain four finite normalized coordinates")
    if np.any(box < 0) or np.any(box > 1):
        raise ValueError("bbox coordinates must be within [0, 1]")
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError("bbox must have positive width and height")
    return box


def bbox_center(box: np.ndarray) -> np.ndarray:
    return (box[:2] + box[2:]) * 0.5


def bbox_diagonal(box: np.ndarray) -> float:
    return float(np.linalg.norm(box[2:] - box[:2]))


def bbox_iou(first: np.ndarray, second: np.ndarray) -> float:
    intersection_sides = np.maximum(
        0.0, np.minimum(first[2:], second[2:]) - np.maximum(first[:2], second[:2])
    )
    intersection = float(np.prod(intersection_sides))
    union = (
        float(np.prod(first[2:] - first[:2]) + np.prod(second[2:] - second[:2]))
        - intersection
    )
    return intersection / union if union > 0 else 0.0


@dataclass
class _Track:
    track_id: int
    bbox: np.ndarray
    timestamp_sec: float
    hits: int = 1
    velocity: np.ndarray | None = None
    clothing_histogram: list[float] | None = None

    def predict(self, timestamp_sec: float) -> np.ndarray:
        if self.velocity is None:
            return self.bbox
        displacement = self.velocity * (timestamp_sec - self.timestamp_sec)
        return self.bbox + np.tile(displacement, 2)


class PersonTracker:
    """Associate detections by Hungarian matching of predicted boxes and centers.

    ``max_age_sec`` retains missing tracks internally; missing boxes are never
    emitted as observations. A pair passes gating if its predicted boxes overlap
    by ``min_iou`` OR its normalized center distance is small enough. IDs are
    temporary video-local track IDs and say nothing about a person's identity.
    """

    def __init__(
        self,
        max_age_sec: float = 2.0,
        min_hits: int = 2,
        max_center_distance: float = 0.18,
        min_iou: float = 0.05,
        moving_speed_threshold: float = 0.08,
        max_color_distance: float = 0.45,
    ) -> None:
        if not math.isfinite(max_age_sec) or max_age_sec < 0:
            raise ValueError("max_age_sec must be finite and nonnegative")
        if min_hits < 1 or not isinstance(min_hits, int):
            raise ValueError("min_hits must be a positive integer")
        if not math.isfinite(max_center_distance) or max_center_distance <= 0:
            raise ValueError("max_center_distance must be finite and positive")
        if not math.isfinite(min_iou) or not 0 < min_iou <= 1:
            raise ValueError("min_iou must be within (0, 1]")
        if not math.isfinite(moving_speed_threshold) or moving_speed_threshold < 0:
            raise ValueError("moving_speed_threshold must be finite and nonnegative")
        self.max_age_sec = max_age_sec
        self.min_hits = min_hits
        self.max_center_distance = max_center_distance
        self.min_iou = min_iou
        self.moving_speed_threshold = moving_speed_threshold
        self.max_color_distance = max_color_distance
        self._tracks: dict[int, _Track] = {}
        self._next_id = 1
        self._timestamp_sec: float | None = None

    def update(
        self, person_detections: list[dict[str, Any]], timestamp_sec: float
    ) -> list[dict[str, Any]]:
        timestamp_sec = float(timestamp_sec)
        if not math.isfinite(timestamp_sec) or timestamp_sec < 0:
            raise ValueError("timestamp_sec must be finite and nonnegative")
        if self._timestamp_sec is not None and timestamp_sec <= self._timestamp_sec:
            raise ValueError("tracking timestamps must be strictly increasing")
        detections = [
            dict(item)
            for item in person_detections
            if item.get("class", "person") == "person"
        ]
        boxes = [validated_bbox(item["bbox"]) for item in detections]
        for item in detections:
            confidence = float(item["confidence"])
            if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                raise ValueError("confidence must be finite and within [0, 1]")
            item["class"] = "person"
            item["confidence"] = confidence
        self._timestamp_sec = timestamp_sec

        self._tracks = {
            track_id: track
            for track_id, track in self._tracks.items()
            if timestamp_sec - track.timestamp_sec <= self.max_age_sec
        }
        tracks = sorted(self._tracks.values(), key=lambda item: item.track_id)
        assignments: dict[int, _Track] = {}
        if tracks and boxes:
            cost = np.full((len(tracks), len(boxes)), 1e6, dtype=np.float64)
            for row, track in enumerate(tracks):
                predicted = track.predict(timestamp_sec)
                for column, box in enumerate(boxes):
                    appearance = color_distance(
                        track.clothing_histogram,
                        detections[column].get("clothing_histogram"),
                    )
                    if appearance is not None and appearance > self.max_color_distance:
                        continue
                    distance = float(
                        np.linalg.norm(bbox_center(predicted) - bbox_center(box))
                    )
                    overlap = bbox_iou(predicted, box)
                    if distance <= self.max_center_distance or overlap >= self.min_iou:
                        cost[row, column] = (
                            0.5 * (1.0 - overlap)
                            + 0.5 * distance / self.max_center_distance
                        )
            rows, columns = linear_sum_assignment(cost)
            assignments = {
                int(column): tracks[int(row)]
                for row, column in zip(rows, columns)
                if cost[row, column] < 1e6
            }

        result: list[dict[str, Any]] = []
        for index, (detection, box) in enumerate(zip(detections, boxes)):
            track = assignments.get(index)
            speed: float | None = None
            dt_sec: float | None = None
            if track is None:
                track = _Track(self._next_id, box.copy(), timestamp_sec)
                self._tracks[track.track_id] = track
                self._next_id += 1
            else:
                dt_sec = timestamp_sec - track.timestamp_sec
                displacement = bbox_center(box) - bbox_center(track.bbox)
                body_scale = (bbox_diagonal(box) + bbox_diagonal(track.bbox)) * 0.5
                speed = float(np.linalg.norm(displacement)) / body_scale / dt_sec
                track.velocity = displacement / dt_sec
                track.bbox = box.copy()
                track.timestamp_sec = timestamp_sec
                track.hits += 1
            track.clothing_histogram = detection.get(
                "clothing_histogram", track.clothing_histogram
            )
            detection.update(
                {
                    "id": track.track_id,
                    "bbox": box.tolist(),
                    "observed": True,
                    "confirmed": track.hits >= self.min_hits,
                    "hits": track.hits,
                    "motion": {
                        "state": (
                            "unknown"
                            if speed is None
                            else (
                                "moving"
                                if speed >= self.moving_speed_threshold
                                else "stationary"
                            )
                        ),
                        "speed_body_lengths_sec": speed,
                        "dt_sec": dt_sec,
                    },
                }
            )
            result.append(detection)
        return sorted(result, key=lambda item: item["id"])
