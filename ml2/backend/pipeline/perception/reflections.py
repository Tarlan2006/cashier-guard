"""Video-local reflection hypotheses from complete geometry-only person tracks.

No image regions, identities, detector training or dataset labels are used. A
small box alone never marks a reflection: it must also have substantially lower
track confidence than a larger, simultaneous, reliable person track. Reflected
motion is additional evidence when enough non-stationary samples are available.
This remains a heuristic; it does not establish that an area is glass or floor.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .tracking import validated_bbox


@dataclass(frozen=True)
class ReflectionConfig:
    """Global thresholds, shared by every video and independent of camera zones."""

    min_observations: int = 3
    anchor_min_observations: int = 5
    anchor_min_confidence: float = 0.78
    candidate_max_confidence: float = 0.70
    min_confidence_gap: float = 0.12
    max_relative_scale: float = 0.72
    min_coobserved_fraction: float = 0.80
    motion_min_observations: int = 8
    motion_min_correlation: float = 0.85
    motion_min_spread_body_lengths: float = 0.06

    def __post_init__(self) -> None:
        if (
            min(
                self.min_observations,
                self.anchor_min_observations,
                self.motion_min_observations,
            )
            < 3
        ):
            raise ValueError("Reflection observation counts must be at least 3")
        for name in (
            "anchor_min_confidence",
            "candidate_max_confidence",
            "min_confidence_gap",
            "max_relative_scale",
            "min_coobserved_fraction",
            "motion_min_correlation",
        ):
            if not 0 < getattr(self, name) <= 1:
                raise ValueError(f"{name} must be in (0, 1]")
        if self.motion_min_spread_body_lengths <= 0:
            raise ValueError("motion_min_spread_body_lengths must be positive")


def _motion_evidence(
    candidate: dict,
    anchor: dict,
    common: list[float],
    dimensions: np.ndarray,
    config: ReflectionConfig,
) -> dict[str, Any]:
    """Fit a reflected similarity to simultaneous centered trajectories.

    Orthogonal Procrustes permits rotation of the mirror axis and uniform scale.
    Pixel aspect correction avoids an artificial dependence on portrait videos.
    A static or almost one-dimensional trajectory cannot establish a reflection.
    """
    evidence: dict[str, Any] = {
        "available": False,
        "supports_reflection": False,
        "coobserved_samples": len(common),
    }
    if len(common) < config.motion_min_observations:
        return evidence
    source = np.array([anchor["centers"][time] for time in common]) * dimensions
    target = np.array([candidate["centers"][time] for time in common]) * dimensions
    source -= np.mean(source, axis=0)
    target -= np.mean(target, axis=0)
    source_norm, target_norm = np.linalg.norm(source), np.linalg.norm(target)
    anchor_diagonal = anchor["pixel_diagonal"]
    source_spread = source_norm / np.sqrt(len(common)) / anchor_diagonal
    target_spread = target_norm / np.sqrt(len(common)) / candidate["pixel_diagonal"]
    if min(source_spread, target_spread) < config.motion_min_spread_body_lengths:
        evidence.update(
            source_spread_body_lengths=float(source_spread),
            target_spread_body_lengths=float(target_spread),
        )
        return evidence
    u, singular, vt = np.linalg.svd(source.T @ target)
    unconstrained = u @ vt
    source_singular = np.linalg.svd(source, compute_uv=False)
    target_singular = np.linalg.svd(target, compute_uv=False)
    # A line can be matched equally by a rotation or a reflection; do not call it
    # mirrored motion. Require measurable movement in the second direction.
    two_dimensional = (
        min(
            source_singular[1] / source_singular[0],
            target_singular[1] / target_singular[0],
        )
        >= 0.10
    )
    reflected = np.linalg.det(unconstrained) < 0
    correlation = float(np.sum(singular) / (source_norm * target_norm))
    evidence.update(
        available=True,
        correlation=correlation,
        reflected_transform=bool(reflected),
        two_dimensional=bool(two_dimensional),
        source_spread_body_lengths=float(source_spread),
        target_spread_body_lengths=float(target_spread),
        supports_reflection=bool(
            reflected
            and two_dimensional
            and correlation >= config.motion_min_correlation
        ),
    )
    return evidence


def annotate_reflections(
    facts: dict[str, Any], config: ReflectionConfig | dict[str, Any] | None = None
) -> dict[str, Any]:
    """Annotate existing observations in place, preserving every person/track.

    Each person receives ``is_reflection``, ``reflection_reason`` (nullable) and
    ``reflection_evidence``. ``facts['reflection_tracks']`` is a list containing
    one summary per ID. Call this before role assignment, people counts and event
    rules: those consumers must exclude people with ``is_reflection == True``.
    These flags are heuristic hypotheses, and all original observations remain
    available for review. Track confidence and scale use the complete video.
    """
    if isinstance(config, dict):
        config = ReflectionConfig(**config)
    config = config or ReflectionConfig()
    dimensions = np.array(
        [
            facts.get("video", {}).get("width", 1),
            facts.get("video", {}).get("height", 1),
        ],
        dtype=float,
    )
    if np.any(dimensions <= 0) or not np.all(np.isfinite(dimensions)):
        raise ValueError("video dimensions must be finite and positive")
    observations: dict[int, list[tuple[float, dict]]] = defaultdict(list)
    for frame in facts.get("frames", []):
        for person in frame.get("persons", []):
            observations[int(person["id"])].append(
                (float(frame["timestamp_sec"]), person)
            )

    tracks: dict[int, dict[str, Any]] = {}
    for track_id, rows in observations.items():
        boxes = np.array([validated_bbox(person["bbox"]) for _, person in rows])
        confidence = np.array([float(person["confidence"]) for _, person in rows])
        if (
            not np.all(np.isfinite(confidence))
            or np.any(confidence < 0)
            or np.any(confidence > 1)
        ):
            raise ValueError("Track confidences must be finite and within [0, 1]")
        sides = boxes[:, 2:] - boxes[:, :2]
        # sqrt(area) compares scale without choosing a camera's vertical axis.
        tracks[track_id] = {
            "mean_confidence": float(np.mean(confidence)),
            "observations": len(rows),
            "scale": float(np.median(np.sqrt(np.prod(sides, axis=1)))),
            "pixel_diagonal": float(
                np.median(np.linalg.norm(sides * dimensions, axis=1))
            ),
            "centers": {
                time: (box[:2] + box[2:]) * 0.5 for (time, _), box in zip(rows, boxes)
            },
        }

    summaries: list[dict[str, Any]] = []
    for track_id, candidate in sorted(tracks.items()):
        options: list[tuple[float, dict[str, Any]]] = []
        for anchor_id, anchor in tracks.items():
            if (
                track_id == anchor_id
                or anchor["observations"] < config.anchor_min_observations
                or anchor["mean_confidence"] < config.anchor_min_confidence
                or anchor["scale"] <= candidate["scale"]
            ):
                continue
            common = sorted(candidate["centers"].keys() & anchor["centers"].keys())
            coobserved_fraction = len(common) / candidate["observations"]
            if coobserved_fraction < config.min_coobserved_fraction:
                continue
            scale_ratio = candidate["scale"] / anchor["scale"]
            confidence_gap = anchor["mean_confidence"] - candidate["mean_confidence"]
            evidence = {
                "anchor_id": anchor_id,
                "mean_track_confidence": candidate["mean_confidence"],
                "anchor_mean_confidence": anchor["mean_confidence"],
                "confidence_gap": confidence_gap,
                "relative_scale_sqrt_area": scale_ratio,
                "coobserved_fraction": coobserved_fraction,
                "motion": _motion_evidence(
                    candidate, anchor, common, dimensions, config
                ),
            }
            options.append((confidence_gap + (1 - scale_ratio), evidence))
        evidence = (
            max(options, key=lambda item: item[0])[1]
            if options
            else {
                "mean_track_confidence": candidate["mean_confidence"],
                "anchor_id": None,
            }
        )
        enough_samples = candidate["observations"] >= config.min_observations
        lower_confidence = (
            candidate["mean_confidence"] <= config.candidate_max_confidence
            and evidence.get("confidence_gap", 0) >= config.min_confidence_gap
        )
        smaller_scale = (
            evidence.get("relative_scale_sqrt_area", 1) <= config.max_relative_scale
        )
        motion_support = evidence.get("motion", {}).get("supports_reflection", False)
        preserved_seed = any(
            person.get("reflection_seed", False) for _, person in observations[track_id]
        )
        mirror_supported = (
            enough_samples
            and smaller_scale
            and motion_support
            and evidence.get("confidence_gap", 0) >= 0.05
        )
        is_reflection = bool(
            enough_samples
            and lower_confidence
            and smaller_scale
            or preserved_seed
            or mirror_supported
        )
        reason = None
        if is_reflection:
            reason = (
                "same_location_reflection_fragment"
                if preserved_seed
                else "low_track_confidence_and_smaller_scale"
            )
            if motion_support:
                reason += "_with_mirrored_motion"
        for _, person in observations[track_id]:
            person.update(
                is_reflection=is_reflection,
                reflection_reason=reason,
                reflection_evidence=evidence.copy(),
            )
        summaries.append(
            {
                "id": track_id,
                "is_reflection": is_reflection,
                "reflection_reason": reason,
                "observations": candidate["observations"],
                "evidence": evidence,
            }
        )
    facts["reflection_tracks"] = summaries
    facts["reflection_filter"] = {
        "method": "complete_track_confidence_relative_scale_with_optional_mirrored_motion",
        "config": asdict(config),
        "limitation": "Heuristic reflection hypotheses; small/distant real people can remain ambiguous. "
        "No floor, glass surface or identity recognition is performed.",
    }
    return facts


def annotate_glass_context(
    path: str | Path, facts: dict, *, classifier: Any = None
) -> dict:
    """Add local SigLIP context support; never claim monocular depth evidence.

    Expanded crops describe glass-like background. Together with a smaller,
    co-observed track and short lifetime/score gap this can support a reflection
    hypothesis even when the detector itself is confident. No image coordinates
    or scene templates are fixed across videos.
    """
    from backend.pipeline.video import VideoReader
    from .fixtures import get_fixture_classifier

    observations = defaultdict(list)
    for frame in facts["frames"]:
        for person in frame["persons"]:
            observations[person["id"]].append((frame, person))
    summaries = {track["id"]: track for track in facts["reflection_tracks"]}
    classifier = classifier or get_fixture_classifier()
    with VideoReader(path) as reader:
        for identifier, rows in observations.items():
            summary = summaries[identifier]
            evidence = summary["evidence"]
            # Avoid classifying an already established hypothesis or a track
            # without a larger simultaneously reliable person.
            if summary["is_reflection"] or evidence.get("anchor_id") is None:
                continue
            span = rows[-1][0]["timestamp_sec"] - rows[0][0]["timestamp_sec"]
            short = span < 2.0
            scale = evidence.get("relative_scale_sqrt_area", 1)
            confidence = evidence["mean_track_confidence"]
            if not (
                scale < 0.80
                and confidence < 0.82
                or short
                and confidence < 0.70
                and scale < 1.0
            ):
                continue
            frame, person = rows[len(rows) // 2]
            box = np.asarray(person["bbox"])
            center, extent = (box[:2] + box[2:]) / 2, (box[2:] - box[:2]) * 1.25
            context = np.r_[
                np.maximum(0, center - extent), np.minimum(1, center + extent)
            ]
            sample = reader.read_at(
                frame.get("actual_timestamp_sec", frame["timestamp_sec"])
            )
            height, width = sample.frame_bgr.shape[:2]
            x1, y1, x2, y2 = np.round(context * [width, height, width, height]).astype(
                int
            )
            naming = classifier.classify([sample.frame_bgr[y1:y2, x1:x2]])
            scores = naming.get("class_scores", {})
            glass_margin = scores.get("reject_glass", -1.0) - max(
                scores.get("reject_surface", 1.0), scores.get("reject_other", 1.0)
            )
            support = glass_margin >= 0.01
            evidence["glass_context"] = {
                "source": "local_siglip_expanded_crop",
                "bbox": context.tolist(),
                "glass_vs_surface_other_margin": glass_margin,
                "supports_glass": support,
                "depth_estimated": False,
            }
            reason = "glass_context_smaller_coobserved_track" if support else None
            if support and (short or evidence.get("confidence_gap", 0) >= 0.07):
                summary.update(is_reflection=True, reflection_reason=reason)
            for _, person in rows:
                person.update(
                    is_reflection=summary["is_reflection"],
                    reflection_reason=summary["reflection_reason"],
                    reflection_evidence=evidence.copy(),
                )
    facts["reflection_filter"][
        "glass_context"
    ] = "local semantic support, not measured floor depth; no per-camera zones"
    return facts
