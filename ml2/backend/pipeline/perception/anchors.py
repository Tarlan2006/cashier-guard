"""Local small static scene anchors, with conservative semantic rejection."""

from copy import copy
from functools import lru_cache
from pathlib import Path
import time

import cv2
import numpy as np

from backend.pipeline.video import VideoReader
from .fixtures import get_fixture_classifier
from .proposals import small_object_proposals, proposal_crops
from .scene_vocab import SCENE_LABELS, SCENE_PROMPTS
from .tracking import bbox_iou


def sanitize_scene_fixtures(facts: dict) -> None:
    """Retain unsupported proposals in audit without publishing named fixtures."""
    unknown = {
        obj["id"]
        for obj in facts.get("fixtures", [])
        if obj["class"] == "unclassified_fixture"
    }
    facts.setdefault("rejected_fixture_proposals", []).extend(
        obj for obj in facts.get("fixtures", []) if obj["id"] in unknown
    )
    facts["fixtures"] = [
        obj for obj in facts.get("fixtures", []) if obj["id"] not in unknown
    ]
    for frame in facts["frames"]:
        frame["safe"] = None
        for obj in frame["objects"]:
            if obj.get("fixture_id") in unknown:
                obj["class"] = obj.get("coco_class", obj["class"])
                obj["fixture_candidate"] = True
                obj["fixture"] = False
                obj.pop("fixture_id", None)
            elif obj.get("fixture") and obj["class"] == "safe":
                frame["safe"] = dict(
                    bbox=obj["bbox"],
                    fixture_id=obj["fixture_id"],
                    naming_status=obj.get("naming_status"),
                    source="temporally_fixed_proposal_local_siglip",
                )


@lru_cache(maxsize=1)
def get_scene_classifier(model_dir: str, threads: int = 2, device: str = "cpu"):
    """Share the vision session; only the small frozen text vocabulary differs."""
    classifier = copy(get_fixture_classifier(model_dir, threads, device))
    with np.load(
        Path(model_dir) / "scene_text_features.npz", allow_pickle=False
    ) as data:
        classifier.prompt_features = data["features"].astype(np.float32)
        classifier.prompt_labels = data["labels"].astype(str)
    if set(classifier.prompt_labels) != set(SCENE_PROMPTS):
        raise ValueError("Scene vocabulary differs from its frozen local text archive")
    classifier.labels = list(SCENE_PROMPTS)
    classifier.output_names = SCENE_LABELS
    classifier.prompts = SCENE_PROMPTS
    return classifier


def discover_scene_anchors(path: str | Path, facts: dict, detector, classifier) -> dict:
    """Search the whole image, never a camera-specific polygon or video ID.

    Only machine and safe are required anchors. Laptop/phone proposals also
    receive semantic names when supported. A missing/rejected anchor remains
    unknown. The area cap applies to the expanded crop as well as its seed.
    """
    started = time.perf_counter()
    present = {item["class"] for item in facts.get("fixtures", [])}
    if {"counter_machine", "safe"} <= present:
        return facts
    tracks, views = small_object_proposals(path, facts, detector)
    selected, examined = [], []
    for track in tracks:
        if any(
            bbox_iou(np.asarray(track["box"]), np.asarray(obj["bbox"])) >= 0.5
            and obj["class"] in SCENE_LABELS
            for obj in facts.get("fixtures", [])
        ):
            continue
        screening = classifier.classify(proposal_crops(track, views)[:1])
        if screening.get("candidate_class") not in set(SCENE_LABELS) | {
            "reject_bag",
            "reject_monitor",
        }:
            continue
        for factor in (1.0, 1.3, 1.6):
            center = (track["box"][:2] + track["box"][2:]) / 2
            radius = (track["box"][2:] - track["box"][:2]) * factor / 2
            box = np.r_[np.maximum(0, center - radius), np.minimum(1, center + radius)]
            if np.prod(box[2:] - box[:2]) > 0.10:
                continue
            expanded = dict(track, box=box)
            crops = proposal_crops(expanded, views)
            naming = classifier.classify(crops)
            examined.append(
                dict(
                    bbox=box.tolist(),
                    context_scale=factor,
                    candidate=naming.get("candidate_class"),
                    name=naming["class"],
                    margin=naming.get("cosine_margin"),
                    reason=naming.get("reason"),
                )
            )
            name = naming["class"]
            if name not in SCENE_LABELS or name in present:
                continue
            identifier = (
                max((obj["id"] for obj in facts["fixtures"]), default=0)
                + len(selected)
                + 1
            )
            summary = dict(
                id=identifier,
                fixture_id=identifier,
                bbox=box.round(6).tolist(),
                bbox_kind="small_semantic_context_envelope",
                coco_class=sorted(track["classes"]),
                crop_timestamps_sec=[views[i]["timestamp_sec"] for i in track["views"]],
                context_scale=factor,
                source="local_multiscale_rtdetr_siglip",
                **naming
            )
            references = [
                cv2.resize(cv2.cvtColor(c, cv2.COLOR_BGR2GRAY), (64, 64)).astype(
                    np.float32
                )
                for c in crops
            ]
            selected.append((summary, references, float(np.mean(track["confidences"]))))
            present.add(name)
            break
        if {"counter_machine", "safe"} <= present:
            break
    # Verify all added anchors in a single local decoding pass on the same
    # 0.5s grid. A top-level fixture is a summary; row boxes need visibility.
    if selected:
        facts["fixtures"].extend(summary for summary, _, _ in selected)
        with VideoReader(path) as reader:
            for sample, row in zip(
                reader.iter_samples(0.5), facts["frames"], strict=True
            ):
                h, w = sample.frame_bgr.shape[:2]
                for summary, references, detection_conf in selected:
                    box = summary["bbox"]
                    x1, y1, x2, y2 = np.round(np.asarray(box) * [w, h, w, h]).astype(
                        int
                    )
                    patch = cv2.resize(
                        cv2.cvtColor(
                            sample.frame_bgr[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY
                        ),
                        (64, 64),
                    ).astype(np.float32)
                    ncc = max(
                        float(cv2.matchTemplate(patch, ref, cv2.TM_CCOEFF_NORMED)[0, 0])
                        for ref in references
                    )
                    if ncc < 0.65:
                        continue
                    obj = dict(
                        **{"class": summary["class"]},
                        bbox=box,
                        fixture=True,
                        fixture_id=summary["id"],
                        confidence=detection_conf,
                        naming_confidence=summary["confidence"],
                        naming_status=summary["naming_status"],
                        observed=True,
                        source=summary["source"],
                        appearance_ncc=ncc
                    )
                    row["objects"].append(obj)
                    if summary["class"] in {"counter_machine", "safe"}:
                        row[summary["class"]] = dict(
                            bbox=box,
                            fixture_id=summary["id"],
                            confidence=summary["confidence"],
                            confidence_kind=summary["confidence_kind"],
                            naming_status=summary["naming_status"],
                            appearance_ncc=ncc,
                        )
    facts["scene_anchor_search"] = dict(
        method="three_views_whole_image_plus_overlapping_tiles",
        max_full_frame_area=0.10,
        context_scales=[1.0, 1.3, 1.6],
        stable_candidates=len(tracks),
        examined_contexts=examined,
        total_sec=time.perf_counter() - started,
        missing_required=sorted({"counter_machine", "safe"} - present),
    )
    return facts
