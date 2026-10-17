"""Video-local track repair and time hysteresis; no identities or camera zones."""

from collections import defaultdict

import numpy as np

from .tracking import bbox_center, bbox_diagonal, bbox_iou, validated_bbox
from .appearance import color_distance


def _rows(facts: dict) -> dict:
    tracks = defaultdict(list)
    for frame in facts.get("frames", []):
        for person in frame["persons"]:
            tracks[person["id"]].append((float(frame["timestamp_sec"]), person))
    return dict(tracks)


def repair_tracks(
    facts: dict,
    *,
    max_gap_sec: float = 2.0,
    require_appearance: bool = True,
    max_color_distance: float = 0.45
) -> dict:
    """Suppress nested/split duplicates, then join unambiguous nearby fragments.

    Suppressed detections remain in frame.suppressed_persons. Repaired IDs are
    video-local geometric associations, not assertions of personal identity.
    """
    tracks = _rows(facts)
    dimensions = np.array(
        [
            facts.get("video", {}).get("width", 1),
            facts.get("video", {}).get("height", 1),
        ],
        dtype=float,
    )
    joins = []
    for frame in facts["frames"]:
        people = sorted(
            frame["persons"],
            key=lambda p: (len(tracks[p["id"]]), p["confidence"]),
            reverse=True,
        )
        kept = []
        suppressed = frame.setdefault("suppressed_persons", [])
        for person in people:
            person.setdefault("source_track_ids", [person["id"]])
            person.setdefault("source_track_id", person["id"])
            person.setdefault("raw_bbox", list(person["bbox"]))
            box = validated_bbox(person["bbox"])
            duplicate = None
            for other in kept:
                target = validated_bbox(other["bbox"])
                intersection = np.maximum(
                    0, np.minimum(box[2:], target[2:]) - np.maximum(box[:2], target[:2])
                ).prod()
                areas = [np.prod(box[2:] - box[:2]), np.prod(target[2:] - target[:2])]
                containment = intersection / max(min(areas), 1e-12)
                scale = max(
                    np.linalg.norm((box[2:] - box[:2]) * dimensions),
                    np.linalg.norm((target[2:] - target[:2]) * dimensions),
                )
                distance = np.linalg.norm(
                    (bbox_center(box) - bbox_center(target)) * dimensions
                ) / max(scale, 1e-9)
                short = len(tracks[person["id"]]) <= 3 and len(tracks[other["id"]]) >= 5
                sizes = np.maximum(box[2:] - box[:2], target[2:] - target[:2])
                edge_alignment = float(np.min(np.abs(box - target) / np.tile(sizes, 2)))
                split = short and distance < 0.45 and edge_alignment < 0.30
                if containment >= 0.80 and distance < 0.5 or split:
                    duplicate = other
                    break
            if duplicate is None:
                kept.append(person)
            else:
                suppressed.append(
                    dict(
                        person,
                        suppression_reason="duplicate_person_box",
                        duplicate_of_id=duplicate["id"],
                    )
                )
                # Split parts form one observed envelope, never a second person.
                if intersection <= 0:
                    duplicate["bbox"] = np.r_[
                        np.minimum(box[:2], target[:2]), np.maximum(box[2:], target[2:])
                    ].tolist()
                duplicate["source_track_ids"] = sorted(
                    set(duplicate["source_track_ids"] + person["source_track_ids"])
                )
        frame["persons"] = sorted(kept, key=lambda p: p["id"])
    # Recompute after suppressions. Mutual best continuation prevents a merge
    # when two equally plausible people are present at the same endpoint.
    while True:
        tracks = _rows(facts)
        options = []
        for first_id, first in tracks.items():
            for next_id, following in tracks.items():
                gap = following[0][0] - first[-1][0]
                if first_id == next_id or not 0 < gap <= max_gap_sec:
                    continue
                appearance = color_distance(
                    first[-1][1].get("clothing_histogram"),
                    following[0][1].get("clothing_histogram"),
                )
                if require_appearance and (
                    appearance is None or appearance > max_color_distance
                ):
                    continue
                a = validated_bbox(first[-1][1]["bbox"])
                b = validated_bbox(following[0][1]["bbox"])
                scale_a = np.linalg.norm((a[2:] - a[:2]) * dimensions)
                scale_b = np.linalg.norm((b[2:] - b[:2]) * dimensions)
                ratio = scale_b / scale_a
                distance = np.linalg.norm(
                    (bbox_center(a) - bbox_center(b)) * dimensions
                ) / max((scale_a + scale_b) / 2, 1e-9)
                if 0.4 <= ratio <= 2.5 and distance <= 1.0:
                    options.append((distance + 0.1 * gap, first_id, next_id, gap))
        if not options:
            break
        options.sort()
        unique = [
            option
            for option in options
            if not any(
                other != option
                and (other[1] == option[1] or other[2] == option[2])
                and other[0] <= option[0] + 0.15
                for other in options
            )
        ]
        if not unique:
            break
        score, first_id, next_id, gap = unique[0]
        for frame in facts["frames"]:
            for person in frame["persons"]:
                if person["id"] == next_id:
                    person["id"] = first_id
        joins.append(
            {
                "from_id": next_id,
                "to_id": first_id,
                "gap_sec": gap,
                "reason": (
                    "unique_geometry_and_clothing_continuation"
                    if require_appearance
                    else "unique_geometric_track_continuation"
                ),
            }
        )
    tracks = _rows(facts)
    for identifier, rows in tracks.items():
        sources = sorted({source for _, p in rows for source in p["source_track_ids"]})
        seed_rows = [p for _, p in rows if p.get("is_reflection", False)]
        seed_box = (
            np.median([p["bbox"] for p in seed_rows], axis=0) if seed_rows else None
        )
        for _, person in rows:
            person["source_track_ids"] = sources
            # Do not wash out a reliable low-confidence reflection fragment
            # merely by averaging it with a more confident fragment at the
            # same location. Require overlapping geometry, not just joined ID.
            if (
                seed_box is not None
                and bbox_iou(validated_bbox(person["bbox"]), seed_box) >= 0.5
            ):
                person["reflection_seed"] = True
    facts["track_repair"] = {
        "method": "nested_or_short_split_box_suppression_and_unique_geometric_continuation",
        "joins": joins,
        "max_gap_sec": max_gap_sec,
        "suppressed_boxes": sum(
            len(f.get("suppressed_persons", [])) for f in facts["frames"]
        ),
    }
    return facts


def apply_hysteresis(facts: dict, *, min_age_sec: float = 2.0) -> dict:
    """Require 2 seconds of evidence before counting or event/role eligibility.

    A track with gaps is retained but its age resets after a >1 s detection
    gap. Later short, ambiguous tracks remain uncertain instead of deleted.
    """
    start = facts["frames"][0]["timestamp_sec"] if facts["frames"] else 0
    source_times = {
        f["timestamp_sec"]: f.get("actual_timestamp_sec", f["timestamp_sec"])
        for f in facts["frames"]
    }
    for _, rows in _rows(facts).items():
        first, last = rows[0][0], rows[-1][0]
        segment_start, previous = first, first
        observed_sources = set()
        short_late = first - start >= min_age_sec and last - first < 5.0
        for timestamp, person in rows:
            allowed_gap = max(
                1.0,
                1.5
                * float(
                    facts.get("sampling_interval_by_time", {}).get(str(timestamp), 0.5)
                ),
            )
            if timestamp - previous > allowed_gap:
                segment_start = timestamp
                observed_sources.clear()
            observed_sources.add(source_times[timestamp])
            age = max(0.0, source_times[timestamp] - source_times[segment_start])
            reflection = person.get("is_reflection", False)
            eligible = (
                age + 1e-8 >= min_age_sec
                and len(observed_sources) >= 3
                and not reflection
            )
            person.update(
                track_age_sec=round(age, 6),
                track_lifetime_sec=last - first,
                confirmation_time_sec=segment_start + min_age_sec,
                track_confirmed=eligible,
                event_eligible=eligible and not short_late,
                counted=eligible,
                uncertain=bool(short_late and not reflection),
                uncertainty_reason=(
                    "short_late_track_ambiguous_support"
                    if short_late and not reflection
                    else None
                ),
                status=(
                    "reflection"
                    if reflection
                    else (
                        "tentative"
                        if not eligible
                        else "uncertain" if short_late else "confirmed"
                    )
                ),
            )
            previous = timestamp
    facts["hysteresis"] = {
        "min_observed_age_sec": min_age_sec,
        "max_gap_sec": 1.0,
        "causal": True,
        "startup_delay_sec": min_age_sec,
    }
    return facts
