"""Temporal role evidence, with a single-person scenario and weak anchor prior."""

from collections import defaultdict
import numpy as np

from .scene_geometry import center, desk_box, distance_to_box

DEFAULT_WEIGHTS = {
    "first_confirmed": 0.40,
    "presence": 0.30,
    "first_seen": 0.15,
    "seated_proxy": 0.10,
    "anchor_proximity": 0.05,
}


def assign_temporal_roles(facts: dict, settings: dict | None = None) -> dict:
    settings = settings or {}
    weights = settings.get("temporal_weights", DEFAULT_WEIGHTS)
    if (
        set(weights) != set(DEFAULT_WEIGHTS)
        or any(v < 0 for v in weights.values())
        or sum(weights.values()) <= 0
    ):
        raise ValueError("Invalid temporal role weights")
    weights = {key: value / sum(weights.values()) for key, value in weights.items()}
    frames = facts["frames"]
    duration = max(float(facts["video"]["duration_sec"]), 0.5)
    dims = np.asarray([facts["video"]["width"], facts["video"]["height"]], float)
    scale = dims / np.linalg.norm(dims)
    tracks = defaultdict(list)
    for index, frame in enumerate(frames):
        t = float(frame.get("actual_timestamp_sec", frame["timestamp_sec"]))
        for p in frame["persons"]:
            p.update(
                role="unknown",
                cashier_prob=0.0,
                client_prob=0.0,
                role_confidence=0.0,
                role_reason="insufficient_temporal_evidence",
                probability_kind="uncalibrated_temporal_softmax",
            )
            if not p.get("is_reflection", False) and p.get("observed", True):
                tracks[p["id"]].append((index, t, p))
    confirmed = {
        key: rows
        for key, rows in tracks.items()
        if any(p.get("track_confirmed", p.get("counted", False)) for _, _, p in rows)
    }
    interval = float(facts.get("sample_interval_sec", 0.5))
    source_times = [
        float(f.get("actual_timestamp_sec", f["timestamp_sec"])) for f in frames
    ]
    durations = [
        (
            max(0.0, source_times[i + 1] - t)
            if i + 1 < len(source_times)
            else min(interval, max(0.0, duration - t))
        )
        for i, t in enumerate(source_times)
    ]
    evidence = {}
    for key, rows in confirmed.items():
        evidence[key] = dict(
            first=rows[0][1],
            last=rows[-1][1],
            confirmed=min(
                t
                for _, t, p in rows
                if p.get("track_confirmed", p.get("counted", False))
            ),
            presence=min(
                1.0, sum(durations[i] for i in {i for i, _, _ in rows}) / duration
            ),
            height=float(np.median([p["bbox"][3] - p["bbox"][1] for _, _, p in rows])),
        )
    residents = {
        key: e
        for key, e in evidence.items()
        if e["presence"] >= settings.get("min_resident_fraction", 0.5)
        and not all(p.get("uncertain", False) for _, _, p in confirmed[key])
    }
    first_confirm = min((e["confirmed"] for e in residents.values()), default=0.0)
    first_seen = min((e["first"] for e in residents.values()), default=0.0)
    standing = (
        float(np.quantile([e["height"] for e in evidence.values()], 0.8))
        if evidence
        else 1.0
    )
    anchors = [
        center(o["bbox"], scale)
        for o in facts.get("fixtures", [])
        if o["class"] in {"counter_machine", "safe"}
    ]
    scores = []
    identifiers = list(residents)
    features = {}
    for key in identifiers:
        e = evidence[key]
        rows = confirmed[key]
        seated = float(
            np.mean(
                [
                    np.clip(
                        1.0 - (p["bbox"][3] - p["bbox"][1]) / max(standing, 1e-6), 0, 1
                    )
                    for _, _, p in rows
                ]
            )
        )
        close = (
            float(
                np.mean(
                    [
                        max(
                            0.0,
                            1.0
                            - min(
                                np.linalg.norm(center(p["bbox"], scale) - a)
                                for a in anchors
                            )
                            / 0.3,
                        )
                        for _, _, p in rows
                    ]
                )
            )
            if anchors
            else 0.0
        )
        f = dict(
            first_confirmed=float(e["confirmed"] <= first_confirm + 0.25),
            presence=e["presence"],
            first_seen=float(e["first"] <= first_seen + 0.25),
            seated_proxy=seated,
            anchor_proximity=close,
        )
        features[key] = f
        scores.append(sum(weights[name] * f[name] for name in weights))
    logits = np.asarray(
        scores + [float(settings.get("temporal_unknown_score", 0.45))]
    ) / float(settings.get("temporal_temperature", 0.10))
    probs = np.exp(logits - logits.max())
    probs /= probs.sum()
    cashier = None
    if identifiers:
        best = int(probs.argmax())
        if (
            best < len(identifiers)
            and probs[best] >= float(settings.get("min_probability", 0.6))
            and probs[best] - np.max(np.delete(probs, best))
            >= float(settings.get("min_margin", 0.2))
        ):
            cashier = identifiers[best]
    # One confirmed actor (including intervals after that actor leaves) is the
    # user-specified single-person scenario, without needing scene anchors.
    max_confirmed = max(
        (
            sum(
                p["id"] in confirmed
                and p.get("track_confirmed", p.get("counted", False))
                for p in row["persons"]
            )
            for row in frames
        ),
        default=0,
    )
    solo = max_confirmed <= 1 and bool(residents)
    if solo:
        cashier = identifiers[0]
        probs[:] = 0.0
        probs[0] = 0.99
        probs[-1] = 0.01
    table = desk_box(facts)
    for key, rows in confirmed.items():
        cp = (
            0.99
            if solo
            else (float(probs[identifiers.index(key)]) if key in identifiers else 0.0)
        )
        e = evidence[key]
        coobserved = (
            any(
                any(p["id"] == cashier for p in frames[i]["persons"])
                for i, _, _ in rows
            )
            if cashier is not None
            else False
        )
        later = (
            not solo
            and cashier is not None
            and key != cashier
            and coobserved
            and e["first"] > evidence[cashier]["first"] + 0.25
        )
        near = (
            [
                distance_to_box(center(p["bbox"]), table, scale)
                <= float(settings.get("client_near_table_diag", 0.08))
                for _, _, p in rows
            ]
            if table
            else [False] * len(rows)
        )
        # Door recognition is unavailable: later first detection is explicitly
        # a timing proxy, not a claim that a door was recognized.
        client_score = (
            0.55 * float(later)
            + 0.30 * float(any(near))
            + 0.15 * min(1.0, (e["last"] - e["first"]) / 3.0)
        )
        pl = (
            float(1.0 / (1.0 + np.exp(-(client_score - 0.55) / 0.10))) * (1.0 - cp)
            if later
            else 0.0
        )
        client_track = later and any(near) and pl >= 0.6
        for near_now, (_, _, p) in zip(near, rows):
            p.update(
                cashier_prob=cp,
                client_prob=pl,
                role_features=features.get(key, {}),
                near_table=bool(near_now),
                height_to_standing_median=e["height"] / max(standing, 1e-6),
            )
            if (
                (key == cashier or solo)
                and p.get("counted", False)
                and not p.get("uncertain", False)
            ):
                p.update(
                    role="cashier_candidate",
                    role_confidence=cp,
                    role_reason=(
                        "single_confirmed_occupant_scenario_not_identity"
                        if solo
                        else "earliest_confirmed_long_resident"
                    ),
                )
            elif client_track and p.get("track_confirmed", p.get("counted", False)):
                p.update(
                    role="client_candidate",
                    role_confidence=pl,
                    role_uncertain=p.get("uncertain", False),
                    role_reason="confirmed_later_track_observed_near_desk",
                )
    facts["roles"] = dict(
        method="temporal_roles_v2",
        client_role_scope="track_after_confirmation",
        cashier_id=cashier,
        single_actor_scenario=solo,
        cashier_ids=(
            list(confirmed) if solo else [cashier] if cashier is not None else []
        ),
        weights=weights,
        track_evidence={str(k): e for k, e in evidence.items()},
        track_features={str(k): v for k, v in features.items()},
        unknown_probability=float(probs[-1]),
        desk_bbox=table,
        standing_height_reference=standing,
        probability_kind="uncalibrated_temporal_softmax",
        limitations=[
            "Box height is a pose proxy affected by perspective, not recognized sitting.",
            "First detection is an arrival proxy; door location is unknown.",
            "Role scores are not calibrated identity/job probabilities.",
        ],
    )
    return facts
