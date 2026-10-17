"""Uncalibrated feature softmax for roles, with an explicit unknown option."""

from collections import defaultdict
from typing import Any

import numpy as np

DEFAULT_WEIGHTS = {
    "presence": 0.35,
    "machine_proximity": 0.25,
    "safe_proximity": 0.20,
    "stationarity": 0.20,
}
DEFAULT_CLIENT_WEIGHTS = {
    "later_arrival": 0.30,
    "opposite_side": 0.45,
    "table_proximity": 0.25,
}


def _softmax(values: list[float], temperature: float) -> np.ndarray:
    logits = np.asarray(values, dtype=float) / temperature
    exponent = np.exp(logits - logits.max())
    return exponent / exponent.sum()


def _anchors(facts: dict, name: str) -> list[np.ndarray]:
    return [
        np.asarray(obj["bbox"], float)
        for obj in facts.get("fixtures", [])
        if obj["class"] == name
    ]


def assign_probabilistic_roles(facts: dict, settings: dict | None = None) -> dict:
    """Feature scores, not learned or calibrated real-world probabilities.

    Presence denominator is the union of time with a visible eligible person.
    Every distance/speed is normalized by the oriented frame diagonal. The
    cashier softmax includes unknown. Client probabilities are independent per
    track (binary softmax), allowing two concurrent client candidates.
    """
    settings = settings or {}
    weights = settings.get("weights", DEFAULT_WEIGHTS)
    client_weights = settings.get("client_weights", DEFAULT_CLIENT_WEIGHTS)
    temperature = float(settings.get("temperature", 0.10))
    unknown_score = float(settings.get("unknown_score", 0.55))
    threshold = float(settings.get("min_probability", 0.60))
    margin = float(settings.get("min_margin", 0.20))
    distance_scale = float(settings.get("near_distance_diag", 0.25))
    stationary_speed = float(settings.get("stationary_speed_diag_sec", 0.015))
    if temperature <= 0 or distance_scale <= 0 or stationary_speed <= 0:
        raise ValueError("Role temperature and geometric scales must be positive")
    if set(weights) != set(DEFAULT_WEIGHTS) or set(client_weights) != set(
        DEFAULT_CLIENT_WEIGHTS
    ):
        raise ValueError("Role feature weight names differ from the documented schema")
    for mapping in (weights, client_weights):
        if (
            any(not np.isfinite(value) or value < 0 for value in mapping.values())
            or sum(mapping.values()) <= 0
        ):
            raise ValueError("Role weights must be finite, nonnegative and nonempty")
    weights = {key: value / sum(weights.values()) for key, value in weights.items()}
    client_weights = {
        key: value / sum(client_weights.values())
        for key, value in client_weights.items()
    }
    frames = facts["frames"]
    dimensions = np.array([facts["video"]["width"], facts["video"]["height"]], float)
    diagonal = float(np.linalg.norm(dimensions))
    scale = dimensions / diagonal
    tracks = defaultdict(list)
    for index, frame in enumerate(frames):
        for person in frame["persons"]:
            person.update(
                role="unknown",
                role_reason="insufficient_role_evidence",
                role_confidence=0.0,
                cashier_prob=0.0,
                client_prob=0.0,
                probability_kind="uncalibrated_feature_softmax",
            )
            if person.get("is_reflection", False) or person.get("observed") is False:
                continue
            box = np.asarray(person["bbox"], float)
            tracks[person["id"]].append(
                (
                    index,
                    float(frame.get("actual_timestamp_sec", frame["timestamp_sec"])),
                    (box[:2] + box[2:]) / 2 * scale,
                    person,
                )
            )
    eligible = {
        key: rows
        for key, rows in tracks.items()
        if len(rows) >= 3 and rows[-1][1] - rows[0][1] >= 2.0
    }
    union = {index for rows in eligible.values() for index, _, _, _ in rows}
    machine_boxes, safe_boxes, laptop_boxes = (
        _anchors(facts, name) for name in ("counter_machine", "safe", "laptop")
    )
    centers = lambda boxes: [((b[:2] + b[2:]) / 2) * scale for b in boxes]
    machines, safes, laptops = (
        centers(machine_boxes),
        centers(safe_boxes),
        centers(laptop_boxes),
    )
    features, scores, summaries = {}, [], {}
    for identifier, rows in eligible.items():
        locations = np.asarray([row[2] for row in rows])

        def proximity(points):
            if not points:
                return 0.0
            distances = np.min(
                np.linalg.norm(
                    locations[:, None, :] - np.asarray(points)[None, :, :], axis=2
                ),
                axis=1,
            )
            return float(np.mean(np.clip(1 - distances / distance_scale, 0, 1)))

        stationary = []
        for previous, current in zip(rows, rows[1:]):
            dt = current[1] - previous[1]
            if 0 < dt <= 1.0:
                stationary.append(
                    float(
                        np.linalg.norm(current[2] - previous[2]) / dt
                        <= stationary_speed
                    )
                )
        feature = dict(
            presence=len({row[0] for row in rows}) / max(1, len(union)),
            machine_proximity=proximity(machines),
            safe_proximity=proximity(safes),
            stationarity=float(np.mean(stationary)) if stationary else 0.0,
        )
        features[identifier] = feature
        scores.append(sum(weights[key] * feature[key] for key in weights))
        summaries[identifier] = dict(
            first_seen=rows[0][1], center=np.median(locations, axis=0)
        )
    identifiers = list(eligible)
    probabilities = (
        _softmax(scores + [unknown_score], temperature) if scores else np.array([1.0])
    )
    cashier = None
    if identifiers and (machines or safes):
        leader = int(np.argmax(probabilities))
        if leader < len(identifiers):
            runner_up = float(np.max(np.delete(probabilities, leader)))
            track_id = identifiers[leader]
            uncertain = any(
                row[3].get("uncertain", False) for row in eligible[track_id]
            )
            if (
                probabilities[leader] >= threshold
                and probabilities[leader] - runner_up >= margin
                and not uncertain
            ):
                cashier = track_id
    # A line through two distinct desk objects is a positional desk proxy.
    # With no laptop/machine pair the opposite-side condition is unavailable.
    desk_line = None
    if machines and laptops:
        a, b = np.asarray(machines[0]), np.asarray(laptops[0])
        if np.linalg.norm(b - a) >= 0.03:
            desk_line = (a, b)
    for index, identifier in enumerate(identifiers):
        rows = eligible[identifier]
        cashier_prob = float(probabilities[index])
        client_prob = 0.0
        client_features = {key: 0.0 for key in DEFAULT_CLIENT_WEIGHTS}
        if cashier is not None and identifier != cashier and desk_line is not None:
            a, b = desk_line
            direction = b - a
            signed = lambda point: float(
                (direction[0] * (point - a)[1] - direction[1] * (point - a)[0])
                / np.linalg.norm(direction)
            )
            reference_side = signed(summaries[cashier]["center"])
            if abs(reference_side) > 0.01:
                opposite = np.mean(
                    [signed(row[2]) * np.sign(reference_side) < -0.01 for row in rows]
                )
                later = (
                    summaries[identifier]["first_seen"]
                    - summaries[cashier]["first_seen"]
                    >= 1.0
                )
                midpoint = (a + b) / 2
                near = float(
                    np.mean(
                        [
                            max(
                                0.0,
                                1 - np.linalg.norm(row[2] - midpoint) / distance_scale,
                            )
                            for row in rows
                        ]
                    )
                )
                client_features = dict(
                    later_arrival=float(later),
                    opposite_side=float(opposite),
                    table_proximity=near,
                )
                score = sum(
                    client_weights[key] * client_features[key] for key in client_weights
                )
                conditional = float(_softmax([score, unknown_score], temperature)[0])
                client_prob = conditional * (1 - cashier_prob)
        for _, _, _, person in rows:
            person.update(
                cashier_prob=cashier_prob,
                client_prob=client_prob,
                role_features=features[identifier],
                client_features=client_features,
            )
            if not person.get("counted", True) or person.get("uncertain", False):
                person["role_reason"] = "tentative_or_uncertain_track"
            elif identifier == cashier:
                person.update(
                    role="cashier_candidate",
                    role_confidence=cashier_prob,
                    role_reason="feature_softmax_leader_above_probability_and_margin_thresholds",
                )
            elif client_prob >= threshold and 2 * client_prob - 1 >= margin:
                person.update(
                    role="client_candidate",
                    role_confidence=client_prob,
                    role_reason="later_arrival_on_opposite_side_of_desk_anchor_proxy",
                )
    if not facts.get("config", {}).get("counter_geometry"):
        for frame in frames:
            for person in frame["persons"]:
                # Remove stale v3 relations. These distances are explicitly to
                # static scene summaries; they do not claim current visibility.
                relation = {
                    "status": "uncalibrated",
                    "source": "static_scene_anchor_summaries",
                }
                if not person.get("is_reflection", False):
                    b = np.asarray(person["bbox"], float)
                    point = (b[:2] + b[2:]) / 2 * scale
                    for name, points in (
                        ("counter_machine", machines),
                        ("safe", safes),
                    ):
                        relation[f"{name}_distance_diag"] = min(
                            (float(np.linalg.norm(point - a)) for a in points),
                            default=None,
                        )
                person["counter_relation"] = relation
    facts["roles"] = dict(
        method="feature_softmax_v1",
        candidate_only=True,
        cashier_id=cashier,
        track_features={str(key): value for key, value in features.items()},
        unknown_probability=float(probabilities[-1]),
        weights=weights,
        client_weights=client_weights,
        temperature=temperature,
        unknown_score=unknown_score,
        min_probability=threshold,
        min_margin=margin,
        desk_line_source="machine_laptop_anchor_proxy" if desk_line else None,
        probability_kind="uncalibrated_feature_softmax",
        limitations=[
            "No role ground truth was used to fit/calibrate these weights.",
            "Stationarity is a motion feature, not recognized sitting/standing pose.",
            "The desk proxy is not a verified table boundary.",
        ],
    )
    return facts
