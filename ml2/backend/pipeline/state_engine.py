"""Generic state transitions over local facts; no dataset IDs or target labels.

The rules produce review candidates, not legal conclusions. A stationary
person is not a recognized seated pose; a detection gap is not a verified
departure. Uncertain roles/anchors never become positive role-based rules.
"""

from collections import defaultdict
import math
from typing import Any

import numpy as np

RULE_IDS = (
    "table_object_after_cashier_leaves_desk",
    "second_person_with_stationary_cashier",
    "two_client_candidates",
)


def _time(frame: dict) -> float:
    return float(frame.get("actual_timestamp_sec", frame["timestamp_sec"]))


def _usable(person: dict) -> bool:
    return (
        not person.get("is_reflection", False)
        and not person.get("uncertain", False)
        and person.get("observed", True)
    )


def build_state_events(facts: dict, settings: dict | None = None) -> dict[str, Any]:
    settings = settings or {}
    gap_sec = float(settings.get("confirmation_sec", 2.0))
    before_after_sec = float(settings.get("snapshot_sec", 1.0))
    desk_radius = float(settings.get("desk_radius_diag", 0.18))
    desk_hysteresis = float(settings.get("desk_hysteresis_diag", 0.02))
    if (
        gap_sec < 2
        or before_after_sec <= 0
        or not 0 < desk_radius < 1
        or not 0 <= desk_hysteresis < 1 - desk_radius
    ):
        raise ValueError(
            "State confirmation must be >=2 seconds and snapshots positive"
        )
    frames = facts.get("frames", [])
    if not frames:
        return dict(zones={}, moments=[], events=[], limitations=["empty timeline"])
    dimensions = np.asarray([facts["video"]["width"], facts["video"]["height"]], float)
    scale = dimensions / np.linalg.norm(dimensions)
    center = lambda box: (np.asarray(box[:2]) + np.asarray(box[2:])) / 2 * scale
    fixtures = facts.get("fixtures", [])
    zones = {
        name: dict(known=False, source=None)
        for name in ("table", "safe", "laptop", "door")
    }
    for name in ("safe", "laptop"):
        boxes = [obj["bbox"] for obj in fixtures if obj["class"] == name]
        if boxes:
            zones[name] = dict(
                known=True, bboxes=boxes, source="local_siglip_fixture_hypothesis"
            )
    desk_boxes = [
        obj["bbox"] for obj in fixtures if obj["class"] in {"counter_machine", "laptop"}
    ]
    if desk_boxes:
        zones["table"] = dict(
            known=True,
            anchor_bboxes=desk_boxes,
            radius_diag=desk_radius,
            source="neighborhood_of_desk_objects_not_verified_table_boundary",
        )
    # A door cannot be obtained reliably from a person-only COCO detector.
    # Explicit optional normalized geometry may be provided for a new camera.
    if settings.get("door_bbox") is not None:
        zones["door"] = dict(
            known=True,
            bbox=settings["door_bbox"],
            source="explicit_scene_configuration",
        )
    tracks = defaultdict(list)
    for i, frame in enumerate(frames):
        for person in frame.get("persons", []):
            if _usable(person):
                tracks[person["id"]].append((i, _time(frame), person))
    # An onset is retained only after future confirmation; tentative boxes
    # before confirmation supply timing, not an independently counted person.
    tracks = {
        key: rows
        for key, rows in tracks.items()
        if any(row[2].get("event_eligible", False) for row in rows)
    }
    cashiers = {
        p["id"]
        for f in frames
        for p in f.get("persons", [])
        if p.get("role") == "cashier_candidate" and _usable(p)
    }
    clients = {
        p["id"]
        for f in frames
        for p in f.get("persons", [])
        if p.get("role") == "client_candidate" and _usable(p)
    }
    moments = []
    for identifier, rows in tracks.items():
        first = rows[0][1]
        confirmed = min(t for _, t, p in rows if p.get("event_eligible", False))
        if first > _time(frames[0]) + 0.25:
            kind = "client_appeared" if identifier in clients else "person_appeared"
            moments.append(
                dict(
                    type=kind,
                    track_id=identifier,
                    first_seen=first,
                    timecode_sec=first,
                    confirmed_at=confirmed,
                    evidence_kind="first_detected_frame",
                )
            )
        # A return after a confirmed gap starts a new visibility episode.
        for row_index, (_, last_time, _) in enumerate(rows):
            next_time = (
                rows[row_index + 1][1] if row_index + 1 < len(rows) else math.inf
            )
            if (
                next_time - last_time < gap_sec + 0.25
                or _time(frames[-1]) - last_time < gap_sec + 0.25
            ):
                continue
            absent = next((f for f in frames if _time(f) > last_time), None)
            if absent is None:
                continue
            onset = _time(absent)
            kind = (
                "cashier_disappeared"
                if identifier in cashiers
                else (
                    "client_disappeared"
                    if identifier in clients
                    else "person_disappeared"
                )
            )
            moments.append(
                dict(
                    type=kind,
                    track_id=identifier,
                    first_seen=onset,
                    timecode_sec=onset,
                    confirmed_at=onset + gap_sec,
                    evidence_kind="box_absence_not_verified_exit",
                )
            )
        if identifier in cashiers and desk_boxes:
            # Leaving the workplace does not require leaving the camera view.
            # First establish residence near desk objects, then require a
            # sustained outward transition. The gray band preserves state.
            near_since, far_since, previous_time = None, None, None
            armed = False
            for _, time, person in rows:
                distance = min(
                    float(np.linalg.norm(center(person["bbox"]) - center(b)))
                    for b in desk_boxes
                )
                if previous_time is not None and time - previous_time > 1.0:
                    near_since, far_since, armed = None, None, False
                if distance <= desk_radius:
                    near_since = time if near_since is None else near_since
                    far_since = None
                    armed = armed or time - near_since >= gap_sec
                elif distance >= desk_radius + desk_hysteresis:
                    near_since = None
                    if armed:
                        far_since = time if far_since is None else far_since
                        if time - far_since >= gap_sec:
                            moments.append(
                                dict(
                                    type="cashier_left_desk",
                                    track_id=identifier,
                                    first_seen=far_since,
                                    timecode_sec=far_since,
                                    confirmed_at=time,
                                    evidence_kind="observed_exit_from_desk_anchor_neighborhood",
                                    radius_diag=desk_radius,
                                    outer_radius_diag=desk_radius + desk_hysteresis,
                                )
                            )
                            armed, far_since = False, None
                previous_time = time
    moments.sort(key=lambda event: (event["timecode_sec"], event["type"]))

    def snapshot(timestamp: float, lo: float, hi: float) -> dict:
        rows = [f for f in frames if timestamp + lo <= _time(f) <= timestamp + hi]
        people = sorted(
            {
                p["id"]
                for f in rows
                for p in f.get("persons", [])
                if _usable(p) and p["id"] in tracks
            }
        )
        objects = sorted(
            {
                obj.get("object_id", obj["class"])
                for f in rows
                for obj in f.get("objects", [])
            }
        )
        zone_states = {}
        for name, zone in zones.items():
            if not zone["known"]:
                zone_states[name] = dict(known=False)
                continue
            boxes = zone.get("bboxes", zone.get("anchor_bboxes", [zone.get("bbox")]))
            anchors = [center(b) for b in boxes if b is not None]
            radius = float(zone.get("radius_diag", 0.18))
            nearby = sorted(
                {
                    obj.get("object_id", obj["class"])
                    for f in rows
                    for obj in f.get("objects", [])
                    if any(
                        np.linalg.norm(center(obj["bbox"]) - a) <= radius
                        for a in anchors
                    )
                }
            )
            zone_states[name] = dict(known=True, object_ids=nearby)
        return dict(person_ids=people, object_ids=objects, zones=zone_states)

    events = []
    for moment in moments:
        t = moment["timecode_sec"]
        moment["before"] = snapshot(t, -before_after_sec, -0.001)
        moment["after"] = snapshot(t, 0.0, before_after_sec)
        moment["state_change"] = {
            "person_ids_added": sorted(
                set(moment["after"]["person_ids"]) - set(moment["before"]["person_ids"])
            ),
            "person_ids_removed": sorted(
                set(moment["before"]["person_ids"]) - set(moment["after"]["person_ids"])
            ),
            "zones": {},
        }
        for name in zones:
            prior, later = (
                moment["before"]["zones"][name],
                moment["after"]["zones"][name],
            )
            if not prior["known"] or not later["known"]:
                moment["state_change"]["zones"][name] = dict(known=False)
            else:
                moment["state_change"]["zones"][name] = dict(
                    known=True,
                    object_ids_added=sorted(
                        set(later["object_ids"]) - set(prior["object_ids"])
                    ),
                    object_ids_removed=sorted(
                        set(prior["object_ids"]) - set(later["object_ids"])
                    ),
                )
        before = [f for f in frames if t - before_after_sec <= _time(f) < t]
        after = [f for f in frames if t <= _time(f) <= t + before_after_sec]
        if (
            moment["type"] in {"cashier_disappeared", "cashier_left_desk"}
            and zones["table"]["known"]
        ):
            loose = defaultdict(list)
            furniture = {
                "chair",
                "dining table",
                "diningtable",
                "couch",
                "bed",
                "refrigerator",
                "counter_machine",
                "safe",
                "laptop",
                "monitor",
                "tvmonitor",
                "tv",
            }
            for frame in after:
                for obj in frame.get("objects", []):
                    name = obj["class"]
                    if name == "unclassified_fixture":
                        name = obj.get("coco_class", name)
                    if (
                        not isinstance(name, str)
                        or name in furniture
                        or name == "unclassified_fixture"
                    ):
                        continue
                    if (
                        np.prod(
                            np.asarray(obj["bbox"])[2:] - np.asarray(obj["bbox"])[:2]
                        )
                        > 0.1
                    ):
                        continue
                    if (
                        min(
                            np.linalg.norm(center(obj["bbox"]) - center(b))
                            for b in desk_boxes
                        )
                        <= desk_radius
                    ):
                        loose[obj.get("object_id", name)].append((_time(frame), name))
            prior_ids = {
                obj.get("object_id", obj["class"])
                for frame in before
                for obj in frame.get("objects", [])
            }
            remaining = {
                key: rows[0][1]
                for key, rows in loose.items()
                if key in prior_ids and len({t for t, _ in rows}) >= 2
            }
            if remaining:
                events.append(
                    dict(
                        rule_id=RULE_IDS[0],
                        type="review_candidate",
                        timecode_sec=t,
                        first_seen=t,
                        confirmed_at=max(moment["confirmed_at"], t + 0.5),
                        track_id=moment["track_id"],
                        visible_facts=(
                            "Cashier candidate moved outside the desk-anchor neighborhood; small object proposals remain."
                            if moment["type"] == "cashier_left_desk"
                            else "Cashier-candidate box disappeared; small object proposals remain near desk anchors."
                        ),
                        object_classes=remaining,
                        certainty="unclear",
                    )
                )
        if (
            moment["type"] in {"person_appeared", "client_appeared"}
            and moment["track_id"] not in cashiers
        ):
            stationary_cashiers = []
            for cashier in cashiers:
                points = [
                    (time, center(p["bbox"]))
                    for _, time, p in tracks.get(cashier, [])
                    if t - before_after_sec <= time < t
                ]
                visible_after = any(
                    p["id"] == cashier and _usable(p)
                    for f in after
                    for p in f.get("persons", [])
                )
                speeds = [
                    np.linalg.norm(b[1] - a[1]) / (b[0] - a[0])
                    for a, b in zip(points, points[1:])
                    if b[0] > a[0]
                ]
                if (
                    visible_after
                    and speeds
                    and float(np.mean(np.asarray(speeds) <= 0.015)) >= 0.75
                ):
                    stationary_cashiers.append(cashier)
            if stationary_cashiers:
                events.append(
                    dict(
                        rule_id=RULE_IDS[1],
                        type="review_candidate",
                        timecode_sec=t,
                        first_seen=t,
                        confirmed_at=moment["confirmed_at"],
                        track_id=moment["track_id"],
                        cashier_ids=stationary_cashiers,
                        certainty="unclear",
                        visible_facts="A confirmed additional track first appears while a cashier candidate remains nearly stationary; sitting is not established.",
                    )
                )
    overlap = []
    for frame in frames:
        ids = sorted(
            {
                p["id"]
                for p in frame["persons"]
                if p["id"] in clients and p["id"] in tracks and _usable(p)
            }
        )
        if len(ids) >= 2:
            overlap.append((_time(frame), ids))
    # Require >=2 seconds of observed overlap, then backdate to its first frame.
    episodes = []
    for row in overlap:
        if not episodes or row[0] - episodes[-1][-1][0] > 1.0:
            episodes.append([])
        episodes[-1].append(row)
    for rows in episodes:
        if rows[-1][0] - rows[0][0] >= gap_sec:
            t = rows[0][0]
            events.append(
                dict(
                    rule_id=RULE_IDS[2],
                    type="review_candidate",
                    timecode_sec=t,
                    first_seen=t,
                    confirmed_at=t + gap_sec,
                    track_ids=rows[0][1],
                    certainty="unclear",
                    visible_facts="Two client-candidate tracks are concurrently visible; role probabilities are uncalibrated.",
                )
            )
    result = dict(
        version="state-engine-v1",
        zones=zones,
        moments=moments,
        events=sorted(events, key=lambda e: (e["timecode_sec"], e["rule_id"])),
        timestamp_policy="condition first_seen, with confirmation time stored separately",
        limitations=[
            "No seated-pose model: stationary motion is only a proxy.",
            "A missing box may be an occlusion or detector miss, not an exit.",
            "Door unknown without explicit scene geometry.",
            "COCO object proposals cannot establish cash, stamps or document contents.",
            "Role and scene-anchor errors propagate; candidates require manual review.",
        ],
    )
    facts["state_engine"] = result
    return result
