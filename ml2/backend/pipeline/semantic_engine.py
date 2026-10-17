"""Observable semantic zone conditions. No dataset numbers, labels or times."""

from collections import defaultdict
from pathlib import Path
import math

import cv2
import numpy as np

from backend.pipeline.budget import BudgetExpired
from backend.pipeline.video import VideoReader
from .perception.anchors_v2 import crop_box
from .perception.scene_geometry import center, desk_box

RULES = {
    "left_items": "items_after_cashier_left",
    "previous_items": "previous_items_with_new_client",
    "safe_open": "safe_open_while_working",
    "two_clients": "two_clients_three_seconds",
    "unlocked": "unlocked_laptop_after_cashier_left",
}


def _time(row: dict) -> float:
    return float(row.get("actual_timestamp_sec", row["timestamp_sec"]))


def collect_moments(facts: dict, settings: dict | None = None) -> dict:
    settings = settings or {}
    frames = facts["frames"]
    dimensions = np.asarray([facts["video"]["width"], facts["video"]["height"]], float)
    scale = dimensions / np.linalg.norm(dimensions)
    cashiers = set(facts.get("roles", {}).get("cashier_ids", []))
    clients = {
        p["id"]
        for row in frames
        for p in row["persons"]
        if p.get("role") == "client_candidate"
        and not p.get("uncertain", False)
        and not p.get("is_reflection", False)
    }
    tracks = defaultdict(list)
    for row in frames:
        for p in row["persons"]:
            if not p.get("is_reflection", False):
                tracks[p["id"]].append((_time(row), p))
    moments = []
    workplaces = []
    # One scene workplace is shared across cashier-role fragments. Changing
    # a track ID cannot move the workplace along with the departing person.
    for key in [min(cashiers)] if cashiers else []:
        by_time = defaultdict(list)
        for cashier in cashiers:
            for t, p in tracks.get(cashier, []):
                by_time[t].append(p)
        rows = [
            (t, max(people, key=lambda p: p["confidence"]))
            for t, people in sorted(by_time.items())
        ]
        if not rows:
            continue
        early = [p for t, p in rows if t <= rows[0][0] + 3.0]
        origin = np.median([center(p["bbox"], scale) for p in early], axis=0)
        # The short side approximates the occupied seat/torso footprint;
        # the long side changes strongly when a person stands up or recedes.
        body = float(
            np.median(
                [
                    np.min(
                        (np.asarray(p["bbox"])[2:] - np.asarray(p["bbox"])[:2]) * scale
                    )
                    for p in early
                ]
            )
        )
        radius = max(
            0.035, min(0.15, float(settings.get("workspace_radius_body", 0.5)) * body)
        )
        workplaces.append(
            dict(
                track_id=key,
                center_diag=origin.tolist(),
                radius_diag=radius,
                source="early_resident_body_geometry",
            )
        )
        far_since = None
        near_since = rows[0][0]
        armed = False
        previous = rows[0][0]
        for t, p in rows:
            distance = float(np.linalg.norm(center(p["bbox"], scale) - origin))
            if t - previous > max(
                1.0, float(facts.get("sample_interval_sec", 0.5)) * 2
            ):
                far_since = None
            if distance <= radius:
                near_since = t if near_since is None else near_since
                if t - near_since >= 2.0:
                    armed = True
                far_since = None
            elif distance >= radius * 1.15:
                near_since = None
                if armed:
                    far_since = t if far_since is None else far_since
            # In the hysteresis band the previous far state persists. Its
            # confirmation must not depend on crossing the outer edge again.
            if far_since is not None and t - far_since >= 2.0:
                moments.append(
                    dict(
                        type="cashier_left_workplace",
                        track_id=key,
                        first_seen=far_since,
                        timecode_sec=far_since,
                        confirmed_at=t,
                    )
                )
                armed = False
                far_since = None
            previous = t
    for key in clients:
        rows = tracks[key]
        near = [(t, p) for t, p in rows if p.get("near_table", False)]
        if not near:
            continue
        first = near[0][0]
        confirmed = next(
            (t for t, p in near if p.get("role") == "client_candidate"), None
        )
        if confirmed is None:
            continue
        predecessors = [
            other
            for other in clients
            if other != key
            and tracks[other][-1][0] < first
            and tracks[other][-1][0] >= first - 30.0
        ]
        moments.append(
            dict(
                type="new_client_at_table",
                track_id=key,
                first_seen=first,
                timecode_sec=first,
                confirmed_at=confirmed,
                previous_client_ids=predecessors,
            )
        )
    # Three-second overlap is confirmed using distinct observed source times;
    # its event onset is backdated to the first overlap, not confirmation.
    episodes = []
    for row in frames:
        ids = sorted(
            {
                p["id"]
                for p in row["persons"]
                if p["id"] in clients
                and p.get("near_table", False)
                and not p.get("is_reflection", False)
                and not p.get("uncertain", False)
            }
        )
        if len(ids) < 2:
            continue
        t = _time(row)
        if not episodes or t - episodes[-1][-1][0] > 1.0:
            episodes.append([])
        episodes[-1].append((t, ids))
    for rows in episodes:
        if rows[-1][0] - rows[0][0] >= 3.0:
            moments.append(
                dict(
                    type="two_clients_overlap",
                    track_ids=rows[0][1],
                    first_seen=rows[0][0],
                    timecode_sec=rows[0][0],
                    confirmed_at=rows[0][0] + 3.0,
                    overlap_sec=rows[-1][0] - rows[0][0],
                )
            )
    zones = {"table": desk_box(facts), "safe": None, "laptop": None, "door": None}
    for name in ("safe", "laptop"):
        boxes = [o["bbox"] for o in facts.get("fixtures", []) if o["class"] == name]
        if boxes:
            zones[name] = boxes[0]
    return dict(
        zones=zones,
        workplaces=workplaces,
        moments=sorted(moments, key=lambda m: m["timecode_sec"]),
        tracks=tracks,
    )


def _table_crops(image: np.ndarray, box, fixtures: list[dict]) -> list[np.ndarray]:
    crop = crop_box(image, box).copy()
    if crop.size == 0:
        return []
    # Hide the fixed equipment from the loose-item question. Proof JPEGs are
    # always the untouched original frames, not these classifier inputs.
    h, w = image.shape[:2]
    ch, cw = crop.shape[:2]
    b = np.asarray(box, float)
    for obj in fixtures:
        if obj["class"] not in {"counter_machine", "safe", "laptop", "phone"}:
            continue
        ob = np.asarray(obj["bbox"], float)
        lo = np.maximum(ob[:2], b[:2])
        hi = np.minimum(ob[2:], b[2:])
        if np.any(hi <= lo):
            continue
        xy1 = np.floor((lo - b[:2]) / (b[2:] - b[:2]) * [cw, ch]).astype(int)
        xy2 = np.ceil((hi - b[:2]) / (b[2:] - b[:2]) * [cw, ch]).astype(int)
        fill = np.median(crop.reshape(-1, 3), axis=0).astype(np.uint8)
        crop[xy1[1] : xy2[1], xy1[0] : xy2[0]] = fill
    # Shared grid, independent of the camera/video. Whole view plus four
    # quadrants make small banknotes/items less likely to vanish on resizing.
    return [crop] + [
        crop[
            round(y * ch) : round((y + 0.5) * ch), round(x * cw) : round((x + 0.5) * cw)
        ]
        for y in (0.0, 0.5)
        for x in (0.0, 0.5)
    ]


def semantic_window(
    reader,
    model,
    domain: str,
    box,
    times: list[float],
    facts: dict,
    *,
    budget=None,
    min_margin: float = 0.01
) -> dict:
    views = []
    source_times = []
    for time in times:
        if budget:
            budget.check()
        sample = reader.read_at(time)
        if any(abs(sample.actual_timestamp_sec - t) < 1e-6 for t in source_times):
            continue
        source_times.append(sample.actual_timestamp_sec)
        crops = (
            _table_crops(sample.frame_bgr, box, facts.get("fixtures", []))
            if domain == "table"
            else [crop_box(sample.frame_bgr, box)]
        )
        predictions = []
        for index, crop in enumerate(crops):
            if budget:
                budget.check()
            if crop.size:
                predictions.append(
                    dict(tile=index, **model.classify(crop, domain, min_margin))
                )
        # One spatial tile must carry the same state across distinct frames.
        views.append(
            dict(time_sec=sample.actual_timestamp_sec, predictions=predictions)
        )
    return consensus_from_views(views, domain, min_margin)


def consensus_from_views(
    views: list[dict], domain: str, min_margin: float = 0.01
) -> dict:
    """Reapply a global acceptance margin to saved model scores, without fitting."""
    views = [
        dict(
            time_sec=v["time_sec"],
            predictions=[
                dict(
                    p,
                    state=(
                        p.get("candidate", p["state"])
                        if p["margin"] >= min_margin
                        else "unknown"
                    ),
                )
                for p in v["predictions"]
            ],
        )
        for v in views
    ]
    states = []
    if len(views) >= 2:
        for tile in {p["tile"] for v in views for p in v["predictions"]}:
            observations = [
                p for v in views for p in v["predictions"] if p["tile"] == tile
            ]
            for state in {p["state"] for p in observations} - {"unknown", "held"}:
                agreeing = [p for p in observations if p["state"] == state]
                if len(agreeing) >= 2:
                    states.append(
                        (float(np.mean([p["margin"] for p in agreeing])), state, tile)
                    )
    if domain == "table" and any(s[1] == "items" for s in states):
        margin, state, tile = max(s for s in states if s[1] == "items")
    elif domain == "table":
        empty = [s for s in states if s[1] == "empty"]
        if any(s[2] == 0 for s in empty) or len({s[2] for s in empty}) >= 4:
            margin, state, tile = max(empty)
        else:
            margin, state, tile = 0.0, "unknown", None
    elif states:
        margin, state, tile = max(states)
    else:
        margin, state, tile = 0.0, "unknown", None
    return dict(
        domain=domain,
        state=state,
        margin=margin,
        tile=tile,
        views=views,
        first_seen=min((v["time_sec"] for v in views), default=None),
        confidence_kind="uncalibrated_semantic_margin",
    )


def _safe_probe_times(reader, box, frames, *, budget=None) -> list[float]:
    changes = []
    previous = None
    for sample in reader.iter_samples(1.0):
        if budget:
            budget.check()
        patch = cv2.resize(
            cv2.cvtColor(crop_box(sample.frame_bgr, box), cv2.COLOR_BGR2GRAY), (32, 32)
        )
        if previous is not None:
            change = float(np.mean(cv2.absdiff(patch, previous) > 20))
            changes.append((change, sample.actual_timestamp_sec))
        previous = patch
    end = _time(frames[-1])
    selected = [0.0, end / 2, max(0.0, end - 0.5)]
    for score, time in sorted(changes, reverse=True):
        if score < 0.01:
            break
        if all(abs(time - t) >= 1.5 for t in selected):
            selected.append(max(0.0, time - 0.5))
        if len(selected) >= 6:
            break
    return sorted(selected)


def evaluate_semantic_states(
    path: str | Path,
    facts: dict,
    model,
    settings: dict | None = None,
    *,
    budget=None,
    on_event=None,
    active_rules: set[str] | None = None,
    window_evaluator=None
) -> dict:
    """At most key windows receive model inference; pixel change only proposes them."""
    settings = settings or {}
    window_evaluator = window_evaluator or semantic_window
    active = set(RULES.values()) if active_rules is None else set(active_rules)
    if not active <= set(RULES.values()):
        raise ValueError("Unknown semantic rule ID")
    scene = collect_moments(facts, settings)
    result = dict(
        version="semantic-state-v1",
        zones=scene["zones"],
        workplaces=scene["workplaces"],
        moments=scene["moments"],
        events=[],
        states=[],
        complete=True,
        evaluable={rule: False for rule in RULES.values()},
        limitations=[
            "Zone/state/role outputs are uncalibrated visual hypotheses.",
            "Box height is a pose proxy; doors and access rights are not recognized.",
            "Unknown/unreadable state never becomes a positive rule.",
        ],
    )
    facts["semantic_engine"] = result
    cashiers = set(facts.get("roles", {}).get("cashier_ids", []))
    clients = {
        p["id"]
        for row in facts["frames"]
        for p in row["persons"]
        if p.get("role") == "client_candidate"
        and not p.get("uncertain", False)
        and not p.get("is_reflection", False)
    }
    table, safe, laptop = (scene["zones"][k] for k in ("table", "safe", "laptop"))
    result["evaluable"][RULES["left_items"]] = bool(cashiers and table)
    result["evaluable"][RULES["previous_items"]] = bool(cashiers and table and clients)
    result["evaluable"][RULES["two_clients"]] = bool(cashiers and clients)
    result["evaluable"][RULES["unlocked"]] = bool(cashiers and laptop)

    def emit(
        rule: str,
        moment: dict,
        description: str,
        states: list[dict],
        extra: dict | None = None,
    ):
        time = float(moment["first_seen"])
        confidence = min(
            0.99,
            min(
                (1.0 / (1.0 + math.exp(-s["margin"] / 0.02)) for s in states),
                default=0.9,
            ),
        )
        event = dict(
            rule_id=rule,
            type="violation",
            timecode_sec=time,
            first_seen=time,
            confirmed_at=max(
                float(moment["confirmed_at"]),
                max(
                    (max(v["time_sec"] for v in s["views"]) for s in states),
                    default=time,
                ),
            ),
            description=description,
            confidence=confidence,
            evidence_states=[
                dict(
                    domain=s["domain"],
                    state=s["state"],
                    margin=s["margin"],
                    tile=s["tile"],
                )
                for s in states
            ],
            **(extra or {})
        )
        # One episode per rule within five seconds; no video-specific suppression.
        if any(
            e["rule_id"] == rule and abs(e["timecode_sec"] - time) < 5.0
            for e in result["events"]
        ):
            return
        result["events"].append(event)
        if on_event:
            on_event(event)

    windows = {}

    def state(reader, domain, box, times):
        key = (domain, tuple(box), tuple(round(float(t), 4) for t in times))
        if key not in windows:
            answer = window_evaluator(
                reader,
                model,
                domain,
                box,
                times,
                facts,
                budget=budget,
                min_margin=float(settings.get("semantic_min_margin", 0.01)),
            )
            windows[key] = answer
            result["states"].append(answer)
        return windows[key]

    try:
        with VideoReader(path) as reader:
            for moment in scene["moments"]:
                if budget:
                    budget.check()
                t = moment["first_seen"]
                if moment["type"] == "cashier_left_workplace":
                    if table and RULES["left_items"] in active:
                        before = state(
                            reader,
                            "table",
                            table,
                            [max(0.0, t - 1.0), max(0.0, t - 0.5)],
                        )
                        after = state(reader, "table", table, [t, t + 0.5])
                        if before["state"] == after["state"] == "items":
                            emit(
                                RULES["left_items"],
                                moment,
                                "После удаления кандидата в кассиры из рабочей зоны на столе остаются предметы.",
                                [before, after],
                            )
                    if laptop and RULES["unlocked"] in active:
                        after = state(reader, "laptop", laptop, [t, t + 0.5])
                        if after["state"] == "unlocked":
                            emit(
                                RULES["unlocked"],
                                moment,
                                "После выхода кандидата в кассиры из рабочей зоны на экране ноутбука видно рабочее окно.",
                                [after],
                            )
                elif (
                    moment["type"] == "new_client_at_table"
                    and moment["previous_client_ids"]
                    and table
                    and RULES["previous_items"] in active
                ):
                    before = state(
                        reader, "table", table, [max(0.0, t - 1.0), max(0.0, t - 0.5)]
                    )
                    after = state(reader, "table", table, [t, t + 0.5])
                    if before["state"] == after["state"] == "items":
                        emit(
                            RULES["previous_items"],
                            moment,
                            "При появлении нового клиента у стола продолжают наблюдаться предметы, видимые до его подхода.",
                            [before, after],
                        )
                elif (
                    moment["type"] == "two_clients_overlap"
                    and RULES["two_clients"] in active
                ):
                    emit(
                        RULES["two_clients"],
                        moment,
                        "Два подтверждённых клиентских трека одновременно находятся у стола не менее трёх секунд.",
                        [],
                        dict(
                            track_ids=moment["track_ids"],
                            overlap_sec=moment["overlap_sec"],
                        ),
                    )
            if safe and cashiers and RULES["safe_open"] in active:
                for t in _safe_probe_times(
                    reader, safe, facts["frames"], budget=budget
                ):
                    rows = [
                        row for row in facts["frames"] if abs(_time(row) - t) <= 1.0
                    ]
                    working = any(
                        p["id"] in cashiers
                        and p.get("near_table", False)
                        and not p.get("uncertain", False)
                        for row in rows
                        for p in row["persons"]
                    )
                    if not working:
                        continue
                    answer = state(reader, "safe", safe, [t, t + 0.5])
                    if answer["state"] in {"open", "closed"}:
                        result["evaluable"][RULES["safe_open"]] = True
                    if answer["state"] == "open":
                        emit(
                            RULES["safe_open"],
                            dict(first_seen=answer["first_seen"], confirmed_at=t + 0.5),
                            "Дверца найденного сейфа выглядит открытой, пока кандидат в кассиры находится у стола.",
                            [answer],
                        )
    except BudgetExpired:
        result["complete"] = False
        facts.setdefault("runtime", {}).update(complete=False)
        facts["runtime"].setdefault("warnings", []).append(
            "Semantic states stopped at local deadline"
        )
    result["events"].sort(key=lambda e: (e["timecode_sec"], e["rule_id"]))
    return result
