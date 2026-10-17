"""Describe observed changes around calibrated counter geometry, never cash transfers."""

from collections import Counter
import math

import cv2
import numpy as np

from .roles import RoleAssigner
from .tracking import validated_bbox


class CounterObserver:
    def __init__(self, geometry: dict | None):
        self.geometry = geometry
        self.previous_people: set[int] | None = None
        self.previous_objects: dict[str, int] | None = None
        self.previous_surface: np.ndarray | None = None
        self.line: np.ndarray | None = None
        self.near_threshold = 2.0
        self.surface_mask: np.ndarray | None = None
        if geometry is None:
            return
        # The same normalized line/reference contract is used by positional roles.
        # Validate once, including distinct endpoints, before processing any frames.
        RoleAssigner(geometry)
        self.line = np.asarray(geometry["line"], dtype=float)
        self.near_threshold = float(geometry.get("near_distance_body_lengths", 2.0))
        polygon = geometry.get("surface_polygon")
        if polygon is not None:
            vertices = np.asarray(polygon, dtype=float)
            if (
                vertices.ndim != 2
                or vertices.shape[0] < 3
                or vertices.shape[1] != 2
                or not np.isfinite(vertices).all()
                or ((vertices < 0) | (vertices > 1)).any()
            ):
                raise ValueError(
                    "surface_polygon must contain at least 3 normalized (x,y) vertices"
                )
            if cv2.contourArea(vertices.astype(np.float32)) <= 1e-9:
                raise ValueError("surface_polygon has zero area")
            mask = np.zeros((128, 128), dtype=np.uint8)
            cv2.fillPoly(mask, [np.round(vertices * 127).astype(np.int32)], 1)
            self.surface_mask = mask.astype(bool)
            if not self.surface_mask.any():
                raise ValueError("surface_polygon has zero rasterized area")

    def update(
        self, persons: list[dict], objects: list[dict], frame_bgr: np.ndarray | None
    ) -> dict:
        """Observe geometry; ``None`` skips image differences for facts refinement."""
        if self.geometry is None:
            return {
                "status": "uncalibrated",
                "changes": [],
                "reason": "Counter geometry is unknown; changes around the counter line are not inferred.",
            }
        people: set[int] = set()
        for person in persons:
            if (
                person.get("is_reflection", False)
                or person.get("observed") is False
                or not person.get("counted", True)
                or person.get("uncertain", False)
            ):
                continue
            distance = person.get("counter_relation", {}).get("distance_body_lengths")
            if (
                distance is not None
                and math.isfinite(float(distance))
                and 0 <= float(distance) <= self.near_threshold
            ):
                people.add(person["id"])
        assert self.line is not None
        vector = self.line[1] - self.line[0]
        length_squared = float(np.dot(vector, vector))
        observed_objects: Counter[str] = Counter()
        for obj in objects:
            box = validated_bbox(obj["bbox"])
            center = (box[:2] + box[2:]) / 2
            body = max(float(np.linalg.norm(box[2:] - box[:2])), 1e-6)
            fraction = float(np.dot(center - self.line[0], vector) / length_squared)
            closest = self.line[0] + np.clip(fraction, 0.0, 1.0) * vector
            distance = float(np.linalg.norm(center - closest))
            if distance / body <= self.near_threshold:
                observed_objects[obj["class"]] += 1
        counts = dict(observed_objects)
        changes = []
        if self.previous_people is not None and people != self.previous_people:
            changes.append(
                {
                    "kind": "observed_near_counter_person_ids_changed",
                    "newly_observed_ids": sorted(people - self.previous_people),
                    "no_longer_observed_ids": sorted(self.previous_people - people),
                    "meaning": "Observed track-ID set change; detection gaps or reassociation may contribute.",
                }
            )
        if self.previous_objects is not None and counts != self.previous_objects:
            changes.append(
                {
                    "kind": "observed_near_counter_object_counts_changed",
                    "before": self.previous_objects,
                    "after": counts,
                    "meaning": "Detection-count change; item transfer is not established.",
                }
            )
        appearance = None
        if self.surface_mask is not None and frame_bgr is not None:
            if frame_bgr.ndim != 3 or frame_bgr.shape[2] != 3 or frame_bgr.size == 0:
                raise ValueError("frame_bgr must be a nonempty BGR frame")
            gray = cv2.cvtColor(cv2.resize(frame_bgr, (128, 128)), cv2.COLOR_BGR2GRAY)
            if self.previous_surface is not None:
                fraction = float(
                    (
                        cv2.absdiff(gray, self.previous_surface)[self.surface_mask] > 25
                    ).mean()
                )
                appearance = {
                    "changed_fraction": round(fraction, 6),
                    "kind": "appearance_difference",
                }
                if fraction >= 0.1:
                    changes.append(
                        {
                            "kind": "counter_surface_appearance_changed",
                            "changed_fraction": round(fraction, 6),
                            "meaning": "Visible appearance change, including possible motion, occlusion or lighting.",
                        }
                    )
            self.previous_surface = gray
        self.previous_people, self.previous_objects = people, counts
        return {
            "status": "calibrated",
            "observed_near_person_ids": sorted(people),
            "observed_object_counts_near_line": counts,
            "appearance": appearance,
            "changes": changes,
        }


def refine_counter_facts(facts: dict) -> dict:
    """Recompute counter facts after full-video reflection/fixture/role refinement.

    Only explicitly configured geometry is used. This routine never estimates a
    line from a machine or reloads video. Canonical object classes and final
    person relations replace obsolete COCO counts and reflected track IDs.
    Already measured surface appearance and its change records are retained;
    they cannot be recalculated from boxes. Without geometry no counter changes
    are claimed, even when automatic positional role candidates are available.
    The input is updated and returned.
    """
    geometry = facts.get("config", {}).get("counter_geometry")
    observer = CounterObserver(geometry)
    frames = sorted(facts.get("frames", []), key=lambda frame: frame["timestamp_sec"])
    # Reflection classification is a full-track decision. Older or external
    # facts can carry that flag on only a subset of rows: exclude the whole ID.
    reflected_ids = {
        str(person["id"])
        for frame in frames
        for person in frame.get("persons", [])
        if person.get("is_reflection", False) and person.get("id") is not None
    }
    for frame in frames:
        previous = frame.get("counter") or {}
        persons = [
            person
            for person in frame.get("persons", [])
            if str(person.get("id")) not in reflected_ids
        ]
        refined = observer.update(persons, frame.get("objects", []), None)
        if "appearance" in previous:
            refined["appearance"] = previous["appearance"]
        if geometry is not None:
            refined["changes"].extend(
                change
                for change in previous.get("changes", [])
                if change.get("kind") == "counter_surface_appearance_changed"
            )
        frame["counter"] = refined
    return facts
