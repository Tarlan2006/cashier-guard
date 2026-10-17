"""Camera-independent multiscale proposals for small stationary desk objects."""

from pathlib import Path
import time

import cv2
import numpy as np

from backend.pipeline.video import VideoReader
from .tracking import bbox_iou, validated_bbox


def small_object_proposals(
    path: str | Path, facts: dict, detector, *, max_candidates: int = 24, budget=None
) -> tuple[list[dict], list[dict]]:
    """Three views, whole frame + overlapping half-frame tiles, no fixed zones.

    COCO only proposes geometry. Candidates occupy <=10% of the full image and
    must be detected in >=2 distinct temporal views with consistent geometry.
    Large furniture and long-lived empty table surfaces are never proposed.
    """
    frames = facts["frames"]
    indices = sorted(set(int(round((len(frames) - 1) * q)) for q in (0.1, 0.5, 0.9)))
    views = []
    with VideoReader(path) as reader:
        for index in indices:
            if budget:
                budget.check()
            row = frames[index]
            sample = reader.read_at(
                row.get("actual_timestamp_sec", row["timestamp_sec"])
            )
            if any(
                abs(view["timestamp_sec"] - sample.actual_timestamp_sec) < 1e-8
                for view in views
            ):
                continue
            views.append(
                {
                    "frame_bgr": sample.frame_bgr,
                    "timestamp_sec": sample.actual_timestamp_sec,
                }
            )
    candidates = []
    for view_index, view in enumerate(views):
        frame = view["frame_bgr"]
        height, width = frame.shape[:2]
        tiles = [(0.0, 0.0, 1.0, 1.0)] + [
            (x, y, x + 0.5, y + 0.5) for y in (0.0, 0.25, 0.5) for x in (0.0, 0.25, 0.5)
        ]
        found = []
        for x1, y1, x2, y2 in tiles:
            if budget:
                budget.check()
            crop = frame[
                round(y1 * height) : round(y2 * height),
                round(x1 * width) : round(x2 * width),
            ]
            detections = detector.predict_batch([crop], object_threshold=0.20)[0]
            for item in detections:
                if item["class"] == "person":
                    continue
                box = np.array(item["bbox"]) * [x2 - x1, y2 - y1, x2 - x1, y2 - y1] + [
                    x1,
                    y1,
                    x1,
                    y1,
                ]
                area = float(np.prod(box[2:] - box[:2]))
                if not 0.0005 <= area <= 0.10:
                    continue
                if any(bbox_iou(box, old["box"]) >= 0.55 for old in found):
                    continue
                found.append(
                    {
                        "box": box,
                        "confidence": item["confidence"],
                        "coco_class": item["class"],
                    }
                )
        for item in sorted(found, key=lambda obj: obj["confidence"], reverse=True):
            eligible = [
                track
                for track in candidates
                if view_index not in track["views"]
                and bbox_iou(item["box"], track["box"]) >= 0.40
            ]
            if eligible:
                track = max(eligible, key=lambda obj: bbox_iou(item["box"], obj["box"]))
                track["boxes"].append(item["box"])
                track["views"].append(view_index)
                track["confidences"].append(item["confidence"])
                track["classes"].add(item["coco_class"])
                track["box"] = np.median(track["boxes"], axis=0)
            else:
                candidates.append(
                    {
                        "box": item["box"],
                        "boxes": [item["box"]],
                        "views": [view_index],
                        "confidences": [item["confidence"]],
                        "classes": {item["coco_class"]},
                    }
                )
    stable = [track for track in candidates if len(track["views"]) >= 2]
    stable.sort(
        key=lambda track: (len(track["views"]), float(np.mean(track["confidences"]))),
        reverse=True,
    )
    result = []
    for track in stable:
        if any(bbox_iou(track["box"], other["box"]) >= 0.55 for other in result):
            continue
        result.append(track)
        if len(result) == max_candidates:
            break
    return result, views


def proposal_crops(track: dict, views: list[dict]) -> list[np.ndarray]:
    crops = []
    for index in track["views"]:
        image = views[index]["frame_bgr"]
        h, w = image.shape[:2]
        x1, y1, x2, y2 = np.round(track["box"] * [w, h, w, h]).astype(int)
        if min(h, y2) > max(0, y1) and min(w, x2) > max(0, x1):
            crops.append(image[max(0, y1) : min(h, y2), max(0, x1) : min(w, x2)])
    return crops


def discover_counter_machine(
    path: str | Path,
    facts: dict,
    detector,
    classifier,
    *,
    budget=None,
    proposal_data=None,
    publish_timeline: bool = True
) -> dict:
    """Name a stable small proposal at shared context scales, then verify views.

    Per-frame publication needs local appearance support from an observed
    source frame. It never fills invisible gaps merely because a fixture exists.
    """
    if any(item["class"] == "counter_machine" for item in facts.get("fixtures", [])):
        return facts
    started = time.perf_counter()
    tracks, views = (
        proposal_data
        if proposal_data is not None
        else small_object_proposals(path, facts, detector, budget=budget)
    )
    examined, selected = [], None
    for track in tracks:
        if budget:
            budget.check()
        screening = classifier.classify(proposal_crops(track, views)[:1])
        candidate = screening.get("candidate_class")
        if candidate not in {"counter_machine", "bag", "monitor", "cash_register"}:
            continue
        for factor in (1.0, 1.3, 1.6):
            if budget:
                budget.check()
            center = (track["box"][:2] + track["box"][2:]) / 2
            radius = (track["box"][2:] - track["box"][:2]) * factor / 2
            box = np.r_[np.maximum(0, center - radius), np.minimum(1, center + radius)]
            if np.prod(box[2:] - box[:2]) > 0.10:
                continue
            expanded = dict(track, box=box)
            crops = proposal_crops(expanded, views)
            naming = classifier.classify(crops)
            examined.append(
                {
                    "bbox": box.tolist(),
                    "context_scale": factor,
                    "candidate": naming.get("candidate_class"),
                    "class": naming["class"],
                    "reason": naming.get("reason"),
                    "margin": naming.get("cosine_margin"),
                }
            )
            if naming["class"] == "counter_machine":
                selected = (expanded, crops, naming, factor)
                break
        if selected is not None:
            break
    facts["fixture_proposal_search"] = {
        "method": "three_temporal_views_whole_frame_plus_3x3_overlapping_half_frame_tiles",
        "max_full_frame_area": 0.10,
        "context_scales": [1.0, 1.3, 1.6],
        "stable_candidates": len(tracks),
        "examined_contexts": examined,
        "total_sec": time.perf_counter() - started,
    }
    if selected is None:
        return facts
    track, crops, naming, factor = selected
    identifier = max((obj["id"] for obj in facts["fixtures"]), default=0) + 1
    box = track["box"].round(6).tolist()
    mean_detection = float(np.mean(track["confidences"]))
    fixture = {
        "id": identifier,
        "fixture_id": identifier,
        "bbox": box,
        "bbox_kind": "small_semantic_context_envelope",
        "coco_class": sorted(track["classes"]),
        "crop_timestamps_sec": [
            views[index]["timestamp_sec"] for index in track["views"]
        ],
        "context_scale": factor,
        "source": "local_multiscale_rtdetr_siglip",
        **naming,
    }
    facts["fixtures"].append(fixture)
    if not publish_timeline:
        for row in facts["frames"]:
            if any(
                abs(row.get("actual_timestamp_sec", row["timestamp_sec"]) - t) < 0.04
                for t in fixture["crop_timestamps_sec"]
            ):
                row["counter_machine"] = dict(
                    bbox=box, fixture_id=identifier, source="confirmed_keyframe_anchor"
                )
        facts["fixture_proposal_search"]["total_sec"] = time.perf_counter() - started
        return facts
    # Several actual temporal views form appearance references. NCC is image
    # evidence for this fixed proposal, not a fresh semantic classification.
    references = [
        cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (64, 64)).astype(np.float32)
        for crop in crops
    ]
    with VideoReader(path) as reader:
        for sample, row in zip(reader.iter_samples(0.5), facts["frames"], strict=True):
            if budget:
                budget.check()
            h, w = sample.frame_bgr.shape[:2]
            x1, y1, x2, y2 = np.round(np.array(box) * [w, h, w, h]).astype(int)
            patch = cv2.resize(
                cv2.cvtColor(sample.frame_bgr[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY),
                (64, 64),
            ).astype(np.float32)
            ncc = max(
                float(cv2.matchTemplate(patch, reference, cv2.TM_CCOEFF_NORMED)[0, 0])
                for reference in references
            )
            if ncc < 0.65:
                continue
            machine = {
                "bbox": box,
                "fixture_id": identifier,
                "confidence": naming["confidence"],
                "confidence_kind": naming["confidence_kind"],
                "naming_status": naming["naming_status"],
                "source": "local_multiscale_rtdetr_siglip_with_static_appearance_verification",
                "appearance_ncc": ncc,
                "bbox_kind": "small_semantic_context_envelope",
            }
            row["counter_machine"] = machine
            row["objects"].append(
                {
                    "class": "counter_machine",
                    "bbox": box,
                    "confidence": mean_detection,
                    "fixture": True,
                    "fixture_id": identifier,
                    "label": naming["label"],
                    "naming_status": naming["naming_status"],
                    "naming_confidence": naming["confidence"],
                    "observed": True,
                    "source": machine["source"],
                    "appearance_ncc": ncc,
                }
            )
    facts["fixture_proposal_search"]["total_sec"] = time.perf_counter() - started
    return facts
