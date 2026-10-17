"""Keep visible onset timestamps separate from later confirmation timestamps."""

from collections import defaultdict
import numpy as np

from .tracking import bbox_iou, validated_bbox


def annotate_first_seen(facts: dict) -> dict:
    people = defaultdict(list)
    objects = defaultdict(list)
    previous = {}
    next_object_id = 1
    for row in facts["frames"]:
        timestamp = float(row.get("actual_timestamp_sec", row["timestamp_sec"]))
        for person in row["persons"]:
            people[person["id"]].append((timestamp, person))
        used = set()
        for obj in row["objects"]:
            if obj.get("fixture_id") is not None:
                identifier = f"fixture:{obj['fixture_id']}"
            else:
                matches = [
                    (bbox_iou(validated_bbox(obj["bbox"]), item["box"]), key)
                    for key, item in previous.items()
                    if key not in used
                    and item["class"] == obj["class"]
                    and timestamp - item["time"] <= 1.0
                ]
                matches = [match for match in matches if match[0] >= 0.35]
                if matches:
                    identifier = max(matches)[1]
                else:
                    identifier = f"object:{next_object_id}"
                    next_object_id += 1
            used.add(identifier)
            obj["object_id"] = identifier
            previous[identifier] = dict(
                box=validated_bbox(obj["bbox"]),
                time=timestamp,
                **{"class": obj["class"]},
            )
            objects[identifier].append((timestamp, obj))
    events = []
    for identifier, rows in people.items():
        first = min(time for time, _ in rows)
        confirmed = min(
            (
                time
                for time, p in rows
                if p.get("event_eligible", p.get("confirmed", False))
                and not p.get("is_reflection", False)
                and not p.get("uncertain", False)
            ),
            default=None,
        )
        for _, person in rows:
            person.update(first_seen=first, confirmed_at=confirmed)
        if confirmed is not None:
            events.append(
                dict(
                    type="person_appeared",
                    track_id=identifier,
                    timecode_sec=first,
                    first_seen=first,
                    confirmed_at=confirmed,
                    evidence_kind="observed_track_onset",
                )
            )
    for identifier, rows in objects.items():
        times = sorted({time for time, _ in rows})
        first = times[0]
        confirmed = times[1] if len(times) >= 2 else None
        for _, obj in rows:
            obj.update(first_seen=first, confirmed_at=confirmed)
        if confirmed is not None:
            events.append(
                dict(
                    type="object_appeared",
                    object_id=identifier,
                    object_class=rows[0][1]["class"],
                    timecode_sec=first,
                    first_seen=first,
                    confirmed_at=confirmed,
                    evidence_kind="object_proposal_onset_not_verified_identity",
                )
            )
    facts["events"] = sorted(
        events, key=lambda event: (event["timecode_sec"], event["type"])
    )
    facts["event_time_convention"] = (
        "visible condition onset; confirmation stored separately; no +2s shift"
    )
    return facts
