"""Camera-independent temporal candidates. No image model, labels or video IDs.

These are observable conditions, not proof of an accounting violation. Shipping
requires a separate video-level validation gate for every rule ID.
"""

from collections import defaultdict
import numpy as np

from .semantic_engine import collect_moments
from .perception.scene_geometry import center

TRACK_RULE_IDS = {
    "cashier_left_workplace",
    "cashier_returned_workplace",
    "cashier_away_with_client",
    "three_people_at_table",
    "two_clients_three_seconds",
}


def evaluate_track_rules(facts: dict, settings: dict | None = None) -> list[dict]:
    settings = settings or {}
    scene = collect_moments(facts, settings)
    hold = float(settings.get("track_hold_sec", 3.0))
    if hold < 2:
        raise ValueError("Temporal confirmation must be at least two seconds")
    dims = np.array([facts["video"]["width"], facts["video"]["height"]], float)
    scale = dims / np.linalg.norm(dims)
    cashiers = set(facts.get("roles", {}).get("cashier_ids", []))
    eligible = {
        p["id"]
        for row in facts["frames"]
        for p in row["persons"]
        if p.get("counted", False)
        and not p.get("uncertain", False)
        and not p.get("is_reflection", False)
    }
    client_ids = {
        p["id"]
        for row in facts["frames"]
        for p in row["persons"]
        if p["id"] in eligible and p.get("role") == "client_candidate"
    }
    workplace = scene["workplaces"][0] if scene["workplaces"] else None
    samples = defaultdict(list)
    # Do not infer absence from missing detections or bridge unobserved gaps.
    for row in facts["frames"]:
        t = float(row.get("actual_timestamp_sec", row["timestamp_sec"]))
        people = [
            p
            for p in row["persons"]
            if p["id"] in eligible
            and not p.get("is_reflection", False)
            and not p.get("uncertain", False)
        ]
        clients = [
            p for p in people if p["id"] in client_ids and p.get("near_table", False)
        ]
        residents = [p for p in people if p["id"] in cashiers]
        far = (
            workplace is not None
            and bool(residents)
            and all(
                np.linalg.norm(center(p["bbox"], scale) - workplace["center_diag"])
                >= workplace["radius_diag"] * 1.15
                for p in residents
            )
        )
        samples["cashier_away_with_client"].append((t, far and bool(clients)))
        samples["three_people_at_table"].append(
            (t, sum(p.get("near_table", False) for p in people) >= 3)
        )
        samples["two_clients_three_seconds"].append((t, len(clients) >= 2))
    events = []

    def add(rule, start, confirmation, description):
        events.append(
            dict(
                rule_id=rule,
                timecode_sec=float(start),
                first_seen=float(start),
                confirmed_at=float(confirmation),
                confidence=0.7,
                description=description,
            )
        )

    for rule, rows in samples.items():
        start = previous = None
        emitted = False
        for t, active in rows:
            if not active or (previous is not None and t - previous > 1.0):
                start, emitted = None, False
            if active:
                start = t if start is None else start
                if t - start >= hold and not emitted:
                    add(
                        rule,
                        start,
                        t,
                        {
                            "cashier_away_with_client": "Кандидат в кассиры находится вне исходного рабочего места, пока у стола виден клиент.",
                            "three_people_at_table": "У стола одновременно видны не менее трёх подтверждённых людей.",
                            "two_clients_three_seconds": "У стола одновременно видны два кандидата в клиенты не менее трёх секунд.",
                        }[rule],
                    )
                    emitted = True
            previous = t
    for m in scene["moments"]:
        if m["type"] != "cashier_left_workplace":
            continue
        add(
            "cashier_left_workplace",
            m["first_seen"],
            m["confirmed_at"],
            "Кандидат в кассиры удалился от исходного рабочего места; перемещение подтверждено двумя секундами наблюдений.",
        )
        if not workplace:
            continue
        start = previous = None
        for row in facts["frames"]:
            t = float(row.get("actual_timestamp_sec", row["timestamp_sec"]))
            if t <= m["confirmed_at"]:
                continue
            near = any(
                p["id"] in cashiers
                and not p.get("is_reflection", False)
                and p.get("counted", False)
                and not p.get("uncertain", False)
                and np.linalg.norm(center(p["bbox"], scale) - workplace["center_diag"])
                <= workplace["radius_diag"]
                for p in row["persons"]
            )
            if not near or (previous is not None and t - previous > 1.0):
                start = None
            if near:
                start = t if start is None else start
                if t - start >= 2.0:
                    add(
                        "cashier_returned_workplace",
                        start,
                        t,
                        "Кандидат в кассиры вернулся к исходному рабочему месту после наблюдаемого удаления.",
                    )
                    break
            previous = t
    # Merge repeated confirmations of the same observable condition within 5 s.
    merged = []
    for event in sorted(events, key=lambda e: (e["rule_id"], e["timecode_sec"])):
        if (
            merged
            and merged[-1]["rule_id"] == event["rule_id"]
            and event["timecode_sec"] - merged[-1]["timecode_sec"] < 5
        ):
            continue
        merged.append(event)
    return sorted(merged, key=lambda e: (e["timecode_sec"], e["rule_id"]))
