"""Cautious temporal and positional role candidates, without face recognition."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from .tracking import bbox_center, bbox_diagonal, validated_bbox


class RoleAssigner:
    """Assign positional candidates, never infer an identity or an occupation.

    Optional normalized geometry::

        {"line": [[x1, y1], [x2, y2]],
         "cashier_side_reference": [x, y],
         "near_distance_body_lengths": 2.0,
         "side_margin_body_lengths": 0.05}

    The reference point specifies one side of the counter, not a pixel zone.
    With no geometry the role remains unknown. The infinite supporting line is
    used to determine sides, while proximity uses the finite line segment.
    """

    def __init__(self, counter_geometry: Mapping[str, Any] | None = None) -> None:
        self.counter_geometry = counter_geometry
        self._line: np.ndarray | None = None
        self._reference_side = 0.0
        self._near = 2.0
        self._margin = 0.05
        if counter_geometry is None:
            return
        line = np.asarray(counter_geometry["line"], dtype=np.float64)
        reference = np.asarray(
            counter_geometry["cashier_side_reference"], dtype=np.float64
        )
        if line.shape != (2, 2) or reference.shape != (2,):
            raise ValueError(
                "counter line needs two 2D endpoints and a 2D cashier_side_reference"
            )
        if not np.all(np.isfinite(line)) or not np.all(np.isfinite(reference)):
            raise ValueError("counter geometry must be finite")
        if (
            np.any(line < 0)
            or np.any(line > 1)
            or np.any(reference < 0)
            or np.any(reference > 1)
        ):
            raise ValueError(
                "counter geometry must use normalized coordinates in [0, 1]"
            )
        direction = line[1] - line[0]
        if float(np.linalg.norm(direction)) <= 1e-9:
            raise ValueError("counter line endpoints must be distinct")
        self._line = line
        side = self._signed_distance(reference)
        if abs(side) <= 1e-9:
            raise ValueError(
                "cashier_side_reference must be away from the counter line"
            )
        self._reference_side = 1.0 if side > 0 else -1.0
        self._near = float(counter_geometry.get("near_distance_body_lengths", 2.0))
        self._margin = float(counter_geometry.get("side_margin_body_lengths", 0.05))
        if not np.isfinite(self._near) or self._near <= 0:
            raise ValueError("near_distance_body_lengths must be finite and positive")
        if not np.isfinite(self._margin) or self._margin < 0:
            raise ValueError("side_margin_body_lengths must be finite and nonnegative")

    def _signed_distance(self, point: np.ndarray) -> float:
        assert self._line is not None
        direction = self._line[1] - self._line[0]
        relative = point - self._line[0]
        return float(direction[0] * relative[1] - direction[1] * relative[0]) / float(
            np.linalg.norm(direction)
        )

    def _segment_distance(self, point: np.ndarray) -> float:
        assert self._line is not None
        direction = self._line[1] - self._line[0]
        fraction = float(
            np.dot(point - self._line[0], direction) / np.dot(direction, direction)
        )
        closest = self._line[0] + np.clip(fraction, 0.0, 1.0) * direction
        return float(np.linalg.norm(point - closest))

    def assign(
        self, persons: list[dict[str, Any]], timestamp_sec: float | None = None
    ) -> list[dict[str, Any]]:
        """Return copies with roles; timestamp is accepted for runner symmetry."""
        del timestamp_sec
        result = [dict(person) for person in persons]
        boxes = [validated_bbox(person["bbox"]) for person in persons]
        centers = [bbox_center(box) for box in boxes]
        scales = [bbox_diagonal(box) for box in boxes]
        for index, person in enumerate(result):
            person["role"] = "unknown"
            person["role_reason"] = "counter_geometry_not_calibrated"
            person["role_confidence"] = 0.0
            relations: dict[str, Any] = {
                "side": "unknown",
                "distance_body_lengths": None,
                "nearest_other_person_id": None,
                "nearest_other_distance_body_lengths": None,
                "across_counter_person_ids": [],
            }
            others = [
                other
                for other in range(len(result))
                if other != index
                and not result[other].get("is_reflection", False)
                and result[other].get("counted", True)
            ]
            if others and not person.get("is_reflection", False):
                nearest = min(
                    others,
                    key=lambda other: float(
                        np.linalg.norm(centers[index] - centers[other])
                    ),
                )
                distance = float(np.linalg.norm(centers[index] - centers[nearest]))
                relations["nearest_other_person_id"] = result[nearest]["id"]
                relations["nearest_other_distance_body_lengths"] = distance / (
                    (scales[index] + scales[nearest]) * 0.5
                )
            person["counter_relation"] = relations
            if person.get("is_reflection", False):
                person["role_reason"] = "reflection_excluded_from_roles"
                continue
            if not person.get("counted", True) or person.get("uncertain", False):
                person["role_reason"] = "tentative_or_uncertain_track"
                continue
            if self._line is None:
                continue
            signed_body_distance = (
                self._signed_distance(centers[index])
                * self._reference_side
                / scales[index]
            )
            segment_distance = self._segment_distance(centers[index]) / scales[index]
            relations["distance_body_lengths"] = segment_distance
            if abs(signed_body_distance) <= self._margin:
                relations["side"] = "on_line"
                person["role_reason"] = (
                    "person_center_too_close_to_counter_line_to_assign_side"
                )
                continue
            relations["side"] = (
                "cashier_reference_side"
                if signed_body_distance > 0
                else "opposite_side"
            )
            if segment_distance > self._near:
                person["role_reason"] = "person_far_from_calibrated_counter_segment"
                continue
            if signed_body_distance > 0:
                person["role"] = "cashier_candidate"
                person["role_confidence"] = 0.7
                person["role_reason"] = (
                    "near_counter_on_cashier_reference_side; positional_candidate_only"
                )
            else:
                person["role"] = "visitor_candidate"
                person["role_confidence"] = 0.7
                person["role_reason"] = (
                    "near_counter_on_opposite_side; positional_candidate_only"
                )

        for index, person in enumerate(result):
            side = person["counter_relation"]["side"]
            if side not in {"cashier_reference_side", "opposite_side"}:
                continue
            person["counter_relation"]["across_counter_person_ids"] = [
                other["id"]
                for other_index, other in enumerate(result)
                if other_index != index
                and not other.get("is_reflection", False)
                and other["role"] != "unknown"
                and other["counter_relation"]["side"]
                in {"cashier_reference_side", "opposite_side"}
                and other["counter_relation"]["side"] != side
            ]
        return result


def infer_roles(
    persons: list[dict[str, Any]],
    counter_geometry: Mapping[str, Any] | None = None,
    timestamp_sec: float | None = None,
) -> list[dict[str, Any]]:
    return RoleAssigner(counter_geometry).assign(persons, timestamp_sec)


def _machine_anchor(facts: Mapping[str, Any]) -> np.ndarray | None:
    """Get the median center of explicitly identified counter-machine fixtures.

    Raw COCO labels (including suitcase/tvmonitor) are never machine evidence.
    All points are relative scene coordinates, with no camera-specific zones.
    """
    boxes: list[np.ndarray] = []
    for fixture in facts.get("fixtures", []):
        if fixture.get("class") == "counter_machine" and not fixture.get(
            "ambiguous", False
        ):
            boxes.append(validated_bbox(fixture["bbox"]))
    for frame in facts.get("frames", []):
        machine = frame.get("counter_machine")
        items = machine if isinstance(machine, list) else [machine] if machine else []
        for item in items:
            if isinstance(item, dict) and not item.get("ambiguous", False):
                boxes.append(validated_bbox(item["bbox"]))
    if not boxes:
        return None
    centers = np.asarray([bbox_center(box) for box in boxes])
    # Several spatially separate machines do not define a unique desk anchor.
    anchor = np.median(centers, axis=0)
    scale = float(np.median([bbox_diagonal(box) for box in boxes]))
    if np.max(np.linalg.norm(centers - anchor, axis=1)) > max(scale, 1e-6):
        return None
    return anchor


def infer_scene_roles(facts: dict[str, Any]) -> dict[str, Any]:
    """Annotate a completed timeline using time and machine-relative positions.

    This is a conservative candidate rule, not an occupation classifier. A
    stationary counter-machine anchor is required in automatic mode. Duration
    alone never assigns a role. A resident must be a predominant, confirmed
    track with uniquely longest stable observed residence near that anchor.
    A client candidate additionally arrives later and stays across the
    anchor from that resident. Ambiguous geometry or multiple equally resident
    people leave roles unknown. Reflections remain present but never take roles
    or participate in geometric relations.

    With explicit counter calibration, the existing calibrated side rule takes
    precedence; it too excludes reflections. The input is updated and returned.
    """
    frames = facts.get("frames", [])
    geometry = facts.get("config", {}).get("counter_geometry")
    if geometry is not None:
        assigner = RoleAssigner(geometry)
        for frame in frames:
            frame["persons"] = assigner.assign(
                frame.get("persons", []), frame.get("timestamp_sec")
            )
        facts["roles"] = {
            "method": "calibrated_counter_geometry",
            "candidate_only": True,
        }
        return facts
    anchor = _machine_anchor(facts)
    observations: dict[int | str, list[tuple[int, float, np.ndarray, float]]] = {}
    for index, frame in enumerate(frames):
        timestamp = float(frame["timestamp_sec"])
        for person in frame.get("persons", []):
            person["role"] = "unknown"
            person["role_confidence"] = 0.0
            person["role_reason"] = (
                "reflection_excluded_from_roles"
                if person.get("is_reflection", False)
                else (
                    "counter_machine_unavailable"
                    if anchor is None
                    else "insufficient_temporal_or_spatial_evidence"
                )
            )
            person["counter_relation"] = {
                "side": "unknown",
                "distance_body_lengths": None,
                "nearest_other_person_id": None,
                "nearest_other_distance_body_lengths": None,
                "across_counter_person_ids": [],
            }
            if (
                person.get("is_reflection", False)
                or person.get("observed") is False
                or not person.get("counted", True)
                or person.get("uncertain", False)
            ):
                continue
            box = validated_bbox(person["bbox"])
            observations.setdefault(person["id"], []).append(
                (index, timestamp, bbox_center(box), bbox_diagonal(box))
            )
    facts["roles"] = {
        "method": "temporal_machine_relative",
        "candidate_only": True,
        "machine_anchor": anchor.tolist() if anchor is not None else None,
        "limitation": "Machine center is a desk proxy; no table boundary or occupation is verified.",
    }
    if anchor is None or not frames:
        return facts
    start = float(frames[0]["timestamp_sec"])
    duration = max(float(frames[-1]["timestamp_sec"]) - start, 0.5)
    summaries: dict[int | str, dict[str, Any]] = {}
    for identifier, rows in observations.items():
        centers = np.asarray([row[2] for row in rows])
        body = float(np.median([row[3] for row in rows]))
        spread = float(
            np.quantile(
                np.linalg.norm(centers - np.median(centers, axis=0), axis=1) / body, 0.9
            )
        )
        near = np.linalg.norm(centers - anchor, axis=1) / body <= 1.5
        dwell_sec = float(np.count_nonzero(near)) * float(
            facts.get("sample_interval_sec", 0.5)
        )
        summaries[identifier] = {
            "center": np.median(centers, axis=0),
            "body": body,
            "presence": len({row[0] for row in rows}) / len(frames),
            "first": min(row[1] for row in rows),
            "samples": len(rows),
            "near_fraction": float(np.mean(near)),
            "dwell_sec": dwell_sec,
            "residence_score": dwell_sec / (1 + 3 * spread),
            "position_spread_body_lengths": spread,
        }
    candidates = [
        identifier
        for identifier, item in summaries.items()
        if item["samples"] >= 3
        and item["dwell_sec"] >= 2.0
        and item["samples"] >= 0.75 * max(s["samples"] for s in summaries.values())
        and item["near_fraction"] >= 0.7
    ]
    candidates.sort(
        key=lambda identifier: summaries[identifier]["residence_score"], reverse=True
    )
    # A scene containing two equally persistent people has no unique temporal
    # cashier anchor. Do not break that tie by horizontal/vertical image zones.
    facts["roles"]["track_evidence"] = {
        str(key): {name: value for name, value in item.items() if name != "center"}
        for key, item in summaries.items()
    }
    if not candidates or (
        len(candidates) > 1
        and summaries[candidates[0]]["residence_score"]
        - summaries[candidates[1]]["residence_score"]
        < max(1.0, 0.1 * summaries[candidates[0]]["residence_score"])
    ):
        return facts
    cashier_id = candidates[0]
    resident = summaries[cashier_id]
    resident_vector = resident["center"] - anchor
    if np.linalg.norm(resident_vector) <= 0.1 * resident["body"]:
        return facts
    axis = resident_vector / np.linalg.norm(resident_vector)
    assignments: dict[int | str, tuple[str, str, float]] = {
        cashier_id: (
            "cashier_candidate",
            "longest_stable_observed_residence_near_counter_machine; candidate_only",
            0.6,
        ),
    }
    for identifier, item in summaries.items():
        if identifier == cashier_id or item["samples"] < 3:
            continue
        rows = observations[identifier]
        signed = np.asarray(
            [float(np.dot(row[2] - anchor, axis)) / row[3] for row in rows]
        )
        distances = np.asarray(
            [float(np.linalg.norm(row[2] - anchor)) / row[3] for row in rows]
        )
        later = item["first"] - resident["first"] >= max(1.0, 0.1 * duration)
        opposite = float(np.mean(signed < -0.15)) >= 0.7
        near = float(np.mean(distances <= 2.5)) >= 0.7
        if later and opposite and near:
            assignments[identifier] = (
                "client_candidate",
                "later_arrival_across_machine_from_resident; positional_temporal_candidate_only",
                0.6,
            )
    for frame in frames:
        active = [
            person
            for person in frame.get("persons", [])
            if not person.get("is_reflection", False)
            and person.get("counted", True)
            and not person.get("uncertain", False)
        ]
        for person in active:
            identifier = person["id"]
            box = validated_bbox(person["bbox"])
            center, body = bbox_center(box), bbox_diagonal(box)
            relation = person["counter_relation"]
            signed = float(np.dot(center - anchor, axis)) / body
            relation["side"] = (
                "resident_side"
                if signed > 0.15
                else "opposite_side" if signed < -0.15 else "ambiguous"
            )
            relation["distance_body_lengths"] = (
                float(np.linalg.norm(center - anchor)) / body
            )
            others = [other for other in active if other["id"] != identifier]
            if others:
                nearest = min(
                    others,
                    key=lambda other: float(
                        np.linalg.norm(
                            center - bbox_center(validated_bbox(other["bbox"]))
                        )
                    ),
                )
                nearest_box = validated_bbox(nearest["bbox"])
                relation["nearest_other_person_id"] = nearest["id"]
                relation["nearest_other_distance_body_lengths"] = float(
                    np.linalg.norm(center - bbox_center(nearest_box))
                ) / ((body + bbox_diagonal(nearest_box)) * 0.5)
            if identifier in assignments:
                person["role"], person["role_reason"], person["role_confidence"] = (
                    assignments[identifier]
                )
                relation["across_counter_person_ids"] = [
                    other["id"]
                    for other in others
                    if other["id"] in assignments
                    and assignments[other["id"]][0] != person["role"]
                ]
    return facts
