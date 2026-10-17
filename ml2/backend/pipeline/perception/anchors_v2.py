"""One bounded multiframe anchor pass; shape/color only support local semantics."""

from pathlib import Path
import time
import cv2
import numpy as np

from backend.pipeline.video import VideoReader
from .fixtures import find_fixture_tracks
from .scene_vocab import SCENE_LABELS
from .tracking import bbox_iou


def crop_box(image: np.ndarray, box) -> np.ndarray:
    h, w = image.shape[:2]
    x1, y1, x2, y2 = np.round(np.asarray(box) * [w, h, w, h]).astype(int)
    return image[max(0, y1) : min(h, y2), max(0, x1) : min(w, x2)]


def gray_shape(image: np.ndarray, box) -> dict:
    crop = crop_box(image, box)
    if crop.size == 0:
        return dict(gray_fraction=0.0, vertical_aspect=0.0)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    gray = float(
        np.mean((hsv[:, :, 1] < 60) & (hsv[:, :, 2] > 30) & (hsv[:, :, 2] < 235))
    )
    return dict(
        gray_fraction=gray, vertical_aspect=crop.shape[0] / max(crop.shape[1], 1)
    )


def gray_rectangles(image: np.ndarray) -> list[np.ndarray]:
    h, w = image.shape[:2]
    ratio = min(1.0, 640 / max(h, w))
    small = cv2.resize(image, (round(w * ratio), round(h * ratio)))
    sh, sw = small.shape[:2]
    edges = cv2.Canny(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), 45, 130)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    found = []
    for contour in cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)[0]:
        x, y, bw, bh = cv2.boundingRect(contour)
        area = bw * bh / (sw * sh)
        if not 0.003 <= area <= 0.10 or not 0.8 <= bh / max(bw, 1) <= 3.5:
            continue
        rectangularity = cv2.contourArea(contour) / max(bw * bh, 1)
        box = np.asarray([x / sw, y / sh, (x + bw) / sw, (y + bh) / sh])
        shape = gray_shape(image, box)
        if rectangularity >= 0.45 and shape["gray_fraction"] >= 0.30:
            found.append((rectangularity * shape["gray_fraction"], box))
    found.sort(key=lambda item: item[0], reverse=True)
    kept = []
    for _, box in found:
        if not any(bbox_iou(box, old) >= 0.55 for old in kept):
            kept.append(box)
        if len(kept) >= 12:
            break
    return kept


def discover_anchors_once(
    path: str | Path,
    facts: dict,
    model,
    *,
    budget=None,
    max_candidates: int = 10,
    max_encodings: int = 18,
    extra_proposals: list[dict] | None = None,
    same_run_proposals: bool = False
) -> dict:
    started = time.perf_counter()
    indices = sorted(
        {round((len(facts["frames"]) - 1) * q) for q in (0.05, 0.25, 0.5, 0.75, 0.95)}
    )
    views = []
    with VideoReader(path) as reader:
        for index in indices:
            if budget:
                budget.check()
            row = facts["frames"][index]
            sample = reader.read_at(
                row.get("actual_timestamp_sec", row["timestamp_sec"])
            )
            if not any(abs(t - sample.actual_timestamp_sec) < 1e-6 for t, _ in views):
                views.append((sample.actual_timestamp_sec, sample.frame_bgr))
    proposals = []
    for track in find_fixture_tracks(facts, min_presence=0.4):
        box = np.asarray(track["bbox"])
        if 0.0005 <= np.prod(box[2:] - box[:2]) <= 0.10:
            classes = {obj["class"] for _, _, obj in track["hits"]}
            device = bool(classes & {"suitcase", "tvmonitor", "laptop"})
            proposals.append(
                dict(
                    box=box,
                    priority=2.0 + track["presence_fraction"],
                    source="static_detector_box",
                    device_candidate=device,
                )
            )
    for track in extra_proposals or []:
        proposals.append(
            dict(
                box=track["box"],
                priority=3.5,
                source="same_run_tiled_detector",
                device_candidate=True,
            )
        )
    # Only proposals discovered in the first pass of THIS invocation can seed
    # its bounded fallback. Never consume fixtures left in an evaluation cache.
    for fixture in facts.get("fixtures", []) if same_run_proposals else []:
        box = np.asarray(fixture["bbox"])
        if np.prod(box[2:] - box[:2]) <= 0.10:
            proposals.append(
                dict(
                    box=box,
                    priority=5.0 if fixture["class"] == "counter_machine" else 4.0,
                    source="same_run_static_proposal",
                    device_candidate=fixture["class"] == "counter_machine",
                )
            )
    gray_tracks = []
    for view_index, (_, image) in enumerate(views):
        for box in gray_rectangles(image):
            matches = [
                tr
                for tr in gray_tracks
                if view_index not in tr["views"] and bbox_iou(box, tr["box"]) >= 0.5
            ]
            if matches:
                tr = max(matches, key=lambda tr: bbox_iou(box, tr["box"]))
                tr["boxes"].append(box)
                tr["views"].append(view_index)
                tr["box"] = np.median(tr["boxes"], axis=0)
            else:
                gray_tracks.append(dict(box=box, boxes=[box], views=[view_index]))
    for tr in gray_tracks:
        if len(tr["views"]) >= min(2, len(views)):
            proposals.append(
                dict(
                    box=tr["box"],
                    priority=1.0 + len(tr["views"]) / max(len(views), 1),
                    source="static_gray_rectangle",
                )
            )
    proposals.sort(key=lambda p: p["priority"], reverse=True)
    kept = []
    for p in proposals:
        if not any(bbox_iou(p["box"], old["box"]) >= 0.65 for old in kept):
            kept.append(p)
        if len(kept) >= max_candidates:
            break
    accepted = []
    audit = []
    encodings = 0
    found_names = set()
    for proposal in kept:
        if encodings >= max_encodings:
            break
        if budget:
            budget.check()
        box = proposal["box"]
        # One screening view; only promising, still-missing names get a second
        # temporal view. Naming is not repeated on every timeline sample.
        source_views = [views[len(views) // 2], views[0]]
        crops = [crop_box(image, box) for _, image in source_views]
        screening = model.scores(crops[0], "anchor")
        encodings += 1
        winner = max(screening, key=screening.get)
        if winner in found_names or winner == "phone":
            continue
        shape = gray_shape(source_views[0][1], box)
        safe_ambiguous = (
            shape["gray_fraction"] >= 0.8
            and 0.8 <= shape["vertical_aspect"] <= 3.5
            and screening["safe"] >= max(screening.values()) - 0.035
            and "safe" not in found_names
        )
        if (
            winner not in {"counter_machine", "safe", "laptop", "reject_bag"}
            and not safe_ambiguous
        ):
            audit.append(
                dict(
                    bbox=box.tolist(),
                    candidate=winner,
                    scores=screening,
                    accepted=None,
                    source=proposal["source"],
                )
            )
            continue
        if safe_ambiguous:
            c = (box[:2] + box[2:]) / 2
            r = (box[2:] - box[:2]) * 0.75
            context = np.r_[np.maximum(0, c - r), np.minimum(1, c + r)]
            if np.prod(context[2:] - context[:2]) <= 0.10:
                box = context
                crops = [crop_box(image, box) for _, image in source_views]
        scores = []
        shapes = []
        for crop, (_, image) in zip(crops, source_views):
            if budget:
                budget.check()
            values = model.scores(crop, "anchor")
            encodings += 1
            shape = gray_shape(image, box)
            shapes.append(shape)
            # A gray vertical shape only breaks a close semantic tie; it can
            # never turn a strongly rejected chair/window into a safe.
            if (
                shape["gray_fraction"] >= 0.30
                and 0.8 <= shape["vertical_aspect"] <= 3.5
            ):
                values["safe"] += 0.008 * min(1.0, shape["gray_fraction"]) + 0.002
            scores.append(values)
        names = list(scores[0]) if scores else []
        mean = {name: float(np.mean([s[name] for s in scores])) for name in names}
        order = sorted(mean, key=mean.get, reverse=True)
        if not order:
            continue
        name = order[0]
        margin = mean[name] - mean[order[1]]
        votes = sum(max(s, key=s.get) == name for s in scores)
        accepted_name = (
            name if name in SCENE_LABELS and votes >= 2 and margin >= 0.004 else None
        )
        legacy = None
        if accepted_name is None or proposal.get("device_candidate", False):
            legacy = model.encoder.classify(crops[:3])
            if legacy.get("class") == "counter_machine":
                accepted_name = "counter_machine"
        # A person can obscure a fixed object in one of two views. A third
        # distinct temporal crop may supply the second vote; it is not a
        # relaxation of semantic acceptance and is used for every scene.
        if (
            accepted_name is None
            and encodings < max_encodings
            and (safe_ambiguous or proposal.get("device_candidate", False))
        ):
            late = crop_box(views[-1][1], box)
            crops.append(late)
            encodings += 1
            extra = model.scores(late, "anchor")
            scores.append(extra)
            mean = {n: float(np.mean([s[n] for s in scores])) for n in names}
            order = sorted(mean, key=mean.get, reverse=True)
            name = order[0]
            margin = mean[name] - mean[order[1]]
            votes = sum(max(s, key=s.get) == name for s in scores)
            if name in SCENE_LABELS and votes >= 2 and margin >= 0.004:
                accepted_name = name
            legacy = model.encoder.classify(crops)
            if legacy.get("class") == "counter_machine":
                accepted_name = "counter_machine"
        if accepted_name == "safe":
            doors = [model.scores(crop, "safe") for crop in crops]
            if (
                sum(max(d["open"], d["closed"]) - d["unknown"] >= 0.01 for d in doors)
                < 2
            ):
                accepted_name = None
        audit.append(
            dict(
                bbox=box.tolist(),
                candidate=name,
                margin=margin,
                votes=votes,
                shape=shapes,
                scores=mean,
                accepted=accepted_name,
                source=proposal["source"],
            )
        )
        if accepted_name:
            found_names.add(accepted_name)
            accepted.append(
                dict(
                    **{"class": accepted_name},
                    bbox=box.round(6).tolist(),
                    score=(
                        margin
                        if legacy is None
                        else max(margin, float(legacy.get("cosine_margin", 0.0)))
                    ),
                    source=proposal["source"],
                    crop_timestamps_sec=[t for t, _ in source_views]
                    + ([views[-1][0]] if len(crops) > 2 else []),
                    naming_status="uncalibrated_multiframe_hypothesis",
                    confidence_kind="uncalibrated_similarity_margin",
                    confidence=float(1 / (1 + np.exp(-margin / 0.02))),
                    wall_relation="unknown"
                )
            )
    # Choose at most one box per name and avoid assigning two identities to
    # the same crop. Every rejected proposal remains in the audit.
    selected = []
    names = set()
    for obj in sorted(accepted, key=lambda o: o["score"], reverse=True):
        if obj["class"] == "safe":
            sb = np.asarray(obj["bbox"])
            sa = float(np.prod(sb[2:] - sb[:2]))
            part_of_device = False
            for machine in [a for a in accepted if a["class"] == "counter_machine"]:
                mb = np.asarray(machine["bbox"])
                c = (mb[:2] + mb[2:]) / 2
                r = (mb[2:] - mb[:2]) * 0.75
                envelope = np.r_[c - r, c + r]
                intersection = float(
                    np.maximum(
                        0,
                        np.minimum(sb[2:], envelope[2:])
                        - np.maximum(sb[:2], envelope[:2]),
                    ).prod()
                )
                if intersection / max(sa, 1e-9) >= 0.5:
                    part_of_device = True
            if part_of_device:
                continue
        if obj["class"] in names or any(
            bbox_iou(np.asarray(obj["bbox"]), np.asarray(old["bbox"])) >= 0.55
            for old in selected
        ):
            continue
        obj["id"] = obj["fixture_id"] = len(selected) + 1
        selected.append(obj)
        names.add(obj["class"])
    facts["fixtures"] = selected
    for row in facts["frames"]:
        row["counter_machine"] = row["safe"] = None
        # Summary boxes are not fabricated per-frame observations.
        for obj in selected:
            if obj["class"] in {"counter_machine", "safe"} and any(
                abs(row.get("actual_timestamp_sec", row["timestamp_sec"]) - t) < 0.04
                for t in obj["crop_timestamps_sec"]
            ):
                row[obj["class"]] = dict(
                    bbox=obj["bbox"],
                    fixture_id=obj["id"],
                    source="confirmed_keyframe_anchor",
                )
    facts["anchor_pass"] = dict(
        version="multiframe-v4-occlusion",
        keyframe_times_sec=[t for t, _ in views],
        image_score_calls=encodings,
        total_sec=time.perf_counter() - started,
        proposals=audit,
        min_margin=0.004,
        max_area_fraction=0.10,
        per_timeline_semantic_inference=False,
    )
    return facts


def discover_scene_anchors_v5(path, facts, model, detector, *, budget=None):
    """Fresh bounded pass, with one three-keyframe fallback for missing anchors."""
    from .proposals import small_object_proposals, discover_counter_machine

    started = time.perf_counter()
    facts["fixtures"] = []
    discover_anchors_once(path, facts, model, budget=budget)
    initial = dict(facts["anchor_pass"])
    present = {obj["class"] for obj in facts["fixtures"]}
    proposal_data = None
    if not {"counter_machine", "safe", "laptop"} <= present and (
        budget is None or budget.remaining > 12.0
    ):
        tracks, views = small_object_proposals(
            path, facts, detector, max_candidates=12, budget=budget
        )
        proposal_data = (tracks, views)
        discover_anchors_once(
            path,
            facts,
            model,
            budget=budget,
            extra_proposals=tracks,
            same_run_proposals=True,
        )
        facts["anchor_pass"]["initial_pass"] = initial
        facts["anchor_pass"]["fallback_stable_proposals"] = len(tracks)
    if (
        not any(obj["class"] == "counter_machine" for obj in facts["fixtures"])
        and proposal_data is not None
    ):
        discover_counter_machine(
            path,
            facts,
            detector,
            model.encoder,
            budget=budget,
            proposal_data=proposal_data,
            publish_timeline=False,
        )
    facts["anchor_pass"]["total_sec"] = time.perf_counter() - started
    facts["anchor_pass"]["previous_video_results_used"] = False
    return facts
