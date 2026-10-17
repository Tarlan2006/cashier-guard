"""Temporal fixture proposals and local, reject-capable SigLIP crop naming.

COCO classes only propose boxes. They never determine a fixture's name.
All geometry is normalized to the orientation-corrected image. No dataset
IDs, calibrated polygons, audio or facial information are consulted.
"""

from __future__ import annotations

import logging
import hashlib
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path
from typing import Protocol, Sequence

import cv2
import numpy as np
from PIL import Image
from scipy.optimize import linear_sum_assignment

from backend.pipeline.video import VideoReader

LOG = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR = PROJECT_ROOT / "models/siglip-base-patch16-224"
FIXTURE_LABELS = {
    "counter_machine": "счётная машинка",
    "laptop": "ноутбук",
    "phone": "телефон",
    "monitor": "монитор",
    "bag": "сумка",
    "cash_register": "касса",
}
# Separate rejection prompts are essential: glass must not be forced into
# the nearest of the six requested names. These are not emitted classes.
PROMPTS = {
    "counter_machine": [
        "a photo of a currency counting machine",
        "a photo of a banknote counting machine",
        "a photo of an automatic money counter",
    ],
    "laptop": [
        "a photo of a laptop computer",
        "a photo of an open laptop on a desk",
        "a photo of a notebook computer",
    ],
    "phone": [
        "a photo of a mobile phone",
        "a photo of a smartphone on a desk",
        "a photo of a telephone",
    ],
    "monitor": [
        "a photo of a computer monitor",
        "a photo of a computer display screen",
        "a photo of a television screen",
    ],
    "bag": [
        "a photo of a handbag",
        "a photo of a carrying bag",
        "a photo of a suitcase",
    ],
    "cash_register": [
        "a photo of a cash register",
        "a photo of a point of sale cash register",
        "a photo of a checkout register",
    ],
    "reject_glass": [
        "a photo of a glass partition",
        "a photo of a transparent glass window",
        "a photo of a reflection in glass",
    ],
    "reject_surface": [
        "a photo of a desk surface",
        "a photo of a wall",
        "a photo of a chair",
    ],
    "reject_other": [
        "a photo of an unidentified object",
        "a photo of an empty counter",
        "a photo of a document on a desk",
    ],
}


def preprocess_crop_bgr(crop_bgr: np.ndarray) -> np.ndarray:
    """Pinned SigLIP PIL bicubic 224x224, rescale then normalize by .5."""
    if crop_bgr.ndim != 3 or crop_bgr.shape[2] != 3 or min(crop_bgr.shape[:2]) < 1:
        raise ValueError("Expected a nonempty BGR crop")
    rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
    resized = Image.fromarray(rgb).resize((224, 224), Image.Resampling.BICUBIC)
    # The pinned Transformers PIL backend rescales in float64, then casts
    # to float32 before normalization (avoids NumPy promotion differences).
    values = (np.asarray(resized).astype(np.float64) * (1 / 255)).astype(np.float32)
    values = (values - np.float32(0.5)) / np.float32(0.5)
    return np.ascontiguousarray(values.transpose(2, 0, 1)[None])


class CropClassifier(Protocol):
    def classify(self, crops_bgr: Sequence[np.ndarray]) -> dict: ...


class LocalSigLIPClassifier:
    """One ONNX image encoder and precomputed text features; no online load.

    Similarity and sigmoid scores are uncalibrated semantic support, never
    detection probabilities. Acceptance requires >=2 agreeing crop views and
    cosine margin >=.01 against every other name and rejection prompt.
    There is no assumed model-independent absolute cosine threshold; an
    explicit calibrated minimum can be supplied. Names remain hypotheses.
    """

    def clear_video_cache(self) -> None:
        """Keep model weights resident, discard all previous video's crop features."""
        if hasattr(self, "_feature_cache"):
            self._feature_cache.clear()

    def __init__(
        self,
        model_dir: str | Path = MODEL_DIR,
        *,
        threads: int = 2,
        device: str = "cpu",
        min_margin: float = 0.01,
        min_similarity: float | None = None,
    ) -> None:
        import onnxruntime as ort

        model_dir = Path(model_dir)
        graph, text = (
            model_dir / "vision_224.onnx",
            model_dir / "fixture_text_features.npz",
        )
        if not graph.is_file() or not text.is_file():
            raise FileNotFoundError(
                "Export local SigLIP first: scripts/export_siglip_zeroshot.py"
            )
        self.min_margin, self.min_similarity = min_margin, min_similarity
        with np.load(text, allow_pickle=False) as archive:
            self.prompt_features = archive["features"].astype(np.float32)
            self.prompt_labels = archive["labels"].astype(str)
            self.logit_scale = float(archive["logit_scale"].item())
            self.logit_bias = float(archive["logit_bias"].item())
        if set(self.prompt_labels) != set(PROMPTS):
            raise ValueError("Local text-vector vocabulary differs from source prompts")
        self.labels = list(PROMPTS)
        available = ort.get_available_providers()
        if device == "cpu":
            providers = ["CPUExecutionProvider"]
        elif device.startswith("cuda") and "CUDAExecutionProvider" in available:
            index = int(device.split(":", 1)[1]) if ":" in device else 0
            providers = [
                ("CUDAExecutionProvider", {"device_id": index}),
                "CPUExecutionProvider",
            ]
        else:
            raise ValueError(
                f"SigLIP ONNX provider unavailable for {device}: {available}"
            )
        options = ort.SessionOptions()
        options.intra_op_num_threads, options.inter_op_num_threads = threads, 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.session = ort.InferenceSession(
            str(graph), sess_options=options, providers=providers
        )

    def encode_crop(self, crop: np.ndarray) -> np.ndarray:
        if not hasattr(self, "_feature_cache"):
            self._feature_cache = OrderedDict()
        key = (crop.shape, hashlib.sha1(crop.tobytes()).digest())
        if key in self._feature_cache:
            return self._feature_cache[key]
        feature = self.session.run(
            ["image_features"], {"pixel_values": preprocess_crop_bgr(crop)}
        )[0][0]
        feature = feature / max(float(np.linalg.norm(feature)), 1e-12)
        self._feature_cache[key] = feature
        if len(self._feature_cache) > 512:
            self._feature_cache.popitem(last=False)
        return feature

    def classify(self, crops_bgr: Sequence[np.ndarray]) -> dict:
        if not crops_bgr:
            return {
                "class": "unclassified_fixture",
                "label": None,
                "reason": "no_crops",
            }
        prompt_scores = []
        for crop in crops_bgr:
            feature = self.encode_crop(crop)
            prompt_scores.append(feature @ self.prompt_features.T)
        # Average synonymous text prompts for the six names. Rejection uses
        # its strongest prompt to avoid averaging a glass signal with walls.
        values = np.asarray(prompt_scores)
        scores = np.stack(
            [
                (
                    values[:, self.prompt_labels == label].max(axis=1)
                    if label.startswith("reject_")
                    else values[:, self.prompt_labels == label].mean(axis=1)
                )
                for label in self.labels
            ],
            axis=1,
        )
        mean_scores = scores.mean(axis=0)
        index = int(mean_scores.argmax())
        candidate = self.labels[index]
        margin = float(mean_scores[index] - np.max(np.delete(mean_scores, index)))
        agreement = int(np.count_nonzero(scores.argmax(axis=1) == index))
        similarity = float(mean_scores[index])
        similarity_ok = self.min_similarity is None or similarity >= self.min_similarity
        output_names = getattr(self, "output_names", FIXTURE_LABELS)
        accepted = (
            candidate in output_names
            and len(crops_bgr) >= 2
            and agreement >= 2
            and margin >= self.min_margin
            and similarity_ok
        )
        sigmoid = float(
            1
            / (
                1
                + np.exp(
                    -np.clip(similarity * self.logit_scale + self.logit_bias, -80, 80)
                )
            )
        )
        reasons = []
        if candidate not in output_names:
            reasons.append(candidate)
        if len(crops_bgr) < 2 or agreement < 2:
            reasons.append("insufficient_view_agreement")
        if margin < self.min_margin:
            reasons.append("ambiguous_name_margin")
        if not similarity_ok:
            reasons.append("low_semantic_support")
        return {
            "class": candidate if accepted else "unclassified_fixture",
            "label": output_names[candidate] if accepted else None,
            "candidate_class": candidate,
            "reason": ";".join(reasons) if reasons else "accepted",
            "cosine_similarity": round(similarity, 6),
            "cosine_margin": round(margin, 6),
            "confidence": round(sigmoid, 6),
            "confidence_kind": "uncalibrated_siglip_sigmoid",
            "naming_status": "uncalibrated_hypothesis" if accepted else "unknown",
            "agreeing_views": agreement,
            "views": len(crops_bgr),
            "class_scores": {
                key: round(float(value), 6)
                for key, value in zip(self.labels, mean_scores)
            },
        }


@lru_cache(maxsize=1)
def get_fixture_classifier(
    model_dir: str = str(MODEL_DIR), threads: int = 2, device: str = "cpu"
) -> LocalSigLIPClassifier:
    return LocalSigLIPClassifier(model_dir, threads=threads, device=device)


def _iou(first: np.ndarray, second: np.ndarray) -> float:
    intersection = np.maximum(
        0.0, np.minimum(first[2:], second[2:]) - np.maximum(first[:2], second[:2])
    ).prod()
    area1, area2 = (
        np.maximum(0.0, first[2:] - first[:2]).prod(),
        np.maximum(0.0, second[2:] - second[:2]).prod(),
    )
    return float(intersection / max(area1 + area2 - intersection, 1e-12))


def find_fixture_tracks(
    facts: dict,
    *,
    min_presence: float = 0.65,
    max_center_drift: float = 0.05,
    max_scale_drift: float = 0.20,
) -> list[dict]:
    """Class-independent object association, followed by full-video stability.

    Presence counts actual detections, never interpolated track predictions.
    A second persistence path handles occlusion/dropout: detections in at
    least min_presence of ten temporal bins, the same minimum timeline span,
    and >=20% of min_presence actual detection coverage. A short-lived
    object cannot become a fixture just by remaining still.
    """
    rows = facts.get("frames", [])
    if not rows:
        return []
    tracks: list[dict] = []
    for row_index, row in enumerate(rows):
        objects = row.get("objects", [])
        # Static proposal identity can survive a long detection dropout.
        # No boxes are emitted during such a gap. Geometry gates still apply.
        active = tracks
        costs = np.full((len(active), len(objects)), 1e6)
        for ti, track in enumerate(active):
            previous = np.asarray(track["hits"][-1][2]["bbox"], dtype=float)
            for oi, obj in enumerate(objects):
                box = np.asarray(obj["bbox"], dtype=float)
                overlap = _iou(previous, box)
                distance = np.linalg.norm(
                    (previous[:2] + previous[2:] - box[:2] - box[2:]) / 2
                )
                area_ratio = (
                    np.maximum(1e-9, box[2:] - box[:2]).prod()
                    / np.maximum(1e-9, previous[2:] - previous[:2]).prod()
                )
                if overlap >= 0.35 and distance <= 0.06 and 0.4 <= area_ratio <= 2.5:
                    costs[ti, oi] = 1 - overlap
        assigned: set[int] = set()
        if costs.size:
            for ti, oi in zip(*linear_sum_assignment(costs)):
                if costs[ti, oi] < 1e6:
                    active[int(ti)]["hits"].append(
                        (row_index, int(oi), objects[int(oi)])
                    )
                    assigned.add(int(oi))
        for oi, obj in enumerate(objects):
            if oi not in assigned:
                tracks.append({"hits": [(row_index, oi, obj)]})
    result = []
    for track in tracks:
        hits = track["hits"]
        boxes = np.asarray([obj["bbox"] for _, _, obj in hits], dtype=float)
        centers = (boxes[:, :2] + boxes[:, 2:]) / 2
        sizes = boxes[:, 2:] - boxes[:, :2]
        median_center, median_size = np.median(centers, axis=0), np.median(
            sizes, axis=0
        )
        center_drift = float(
            np.quantile(np.linalg.norm(centers - median_center, axis=1), 0.9)
        )
        scale_drift = float(
            np.quantile(
                np.max(
                    np.abs(sizes - median_size) / np.maximum(median_size, 1e-9), axis=1
                ),
                0.9,
            )
        )
        presence = len(hits) / len(rows)
        bins = min(10, len(rows))
        temporal_coverage = (
            len({min(bins - 1, i * bins // len(rows)) for i, _, _ in hits}) / bins
        )
        span = (hits[-1][0] - hits[0][0] + 1) / len(rows)
        persistent = presence >= min_presence or (
            presence >= 0.2 * min_presence
            and len(hits) >= 3
            and temporal_coverage >= min_presence
            and span >= min_presence
        )
        if (
            persistent
            and center_drift <= max_center_drift
            and scale_drift <= max_scale_drift
        ):
            result.append(
                {
                    "id": len(result) + 1,
                    "fixture_id": len(result) + 1,
                    "hits": hits,
                    "bbox": np.median(boxes, axis=0).round(6).tolist(),
                    "presence_fraction": round(presence, 6),
                    "temporal_bin_coverage": round(temporal_coverage, 6),
                    "timeline_span_fraction": round(span, 6),
                    "center_drift_p90": round(center_drift, 6),
                    "relative_size_drift_p90": round(scale_drift, 6),
                }
            )
    return result


def _select_views(hits: list[tuple]) -> list[tuple]:
    """Choose temporal thirds' highest-score actual boxes, at most 3."""
    if not hits:
        return []
    selected = []
    for indices in np.array_split(np.arange(len(hits)), min(3, len(hits))):
        best = max(
            indices, key=lambda index: float(hits[int(index)][2].get("confidence", 0.0))
        )
        selected.append(hits[int(best)])
    return selected


def annotate_fixtures(
    path: str | Path,
    facts: dict,
    *,
    classifier: CropClassifier | None = None,
    model_dir: str | Path = MODEL_DIR,
    threads: int = 2,
    device: str = "cpu",
    min_presence: float = 0.65,
    max_center_drift: float = 0.05,
    max_scale_drift: float = 0.20,
) -> dict:
    """Annotate detected fixed objects and counter_machine facts in place.

    Transient proposals keep their original class and bounding boxes. Fixture
    metadata is emitted only on actual object detections; it is never filled
    across a visibility gap. The median top-level box is a track summary.
    """
    tracks = find_fixture_tracks(
        facts,
        min_presence=min_presence,
        max_center_drift=max_center_drift,
        max_scale_drift=max_scale_drift,
    )
    for row in facts.get("frames", []):
        row["counter_machine"] = None
    facts["fixtures"] = []
    facts["rejected_fixture_proposals"] = []
    if not tracks:
        return facts
    classifier = classifier or get_fixture_classifier(str(model_dir), threads, device)
    with VideoReader(path) as reader:
        for track in tracks:
            area = float(
                np.prod(np.asarray(track["bbox"])[2:] - np.asarray(track["bbox"])[:2])
            )
            if area > 0.10:
                facts["rejected_fixture_proposals"].append(
                    {
                        "bbox": track["bbox"],
                        "reason": "oversize_furniture_proposal",
                        "area_fraction": area,
                    }
                )
                continue
            crops, crop_times = [], []
            for row_index, _, obj in _select_views(track["hits"]):
                row = facts["frames"][row_index]
                sample = reader.read_at(
                    float(row.get("actual_timestamp_sec", row["timestamp_sec"]))
                )
                if any(
                    abs(sample.actual_timestamp_sec - timestamp) < 1e-8
                    for timestamp in crop_times
                ):
                    continue
                height, width = sample.frame_bgr.shape[:2]
                box = np.asarray(obj["bbox"], dtype=float)
                # No broad padding: surrounding screens/glass can dominate
                # SigLIP if a crop contains much more than the proposed box.
                x1, y1 = np.floor(box[:2] * [width, height]).astype(int)
                x2, y2 = np.ceil(box[2:] * [width, height]).astype(int)
                x1, y1, x2, y2 = max(x1, 0), max(y1, 0), min(x2, width), min(y2, height)
                if x2 > x1 and y2 > y1:
                    crops.append(sample.frame_bgr[y1:y2, x1:x2])
                    crop_times.append(sample.actual_timestamp_sec)
            naming = classifier.classify(crops)
            summary = {key: value for key, value in track.items() if key != "hits"}
            summary.update(naming)
            summary["crop_timestamps_sec"] = crop_times
            summary["raw_coco_classes"] = sorted(
                {obj.get("coco_class", obj["class"]) for _, _, obj in track["hits"]}
            )
            summary["coco_class"] = summary["raw_coco_classes"]
            if naming.get("candidate_class") == "reject_surface":
                summary["reason"] = "furniture_or_surface_rejected"
                facts["rejected_fixture_proposals"].append(summary)
                continue
            facts["fixtures"].append(summary)
            for row_index, _, obj in track["hits"]:
                obj["coco_class"] = obj.get("coco_class", obj["class"])
                obj.update(
                    {
                        "class": naming["class"],
                        "fixture": True,
                        "fixture_id": track["fixture_id"],
                        "label": naming.get("label"),
                        "naming_reason": naming.get("reason"),
                        "naming_status": naming.get(
                            "naming_status", "uncalibrated_hypothesis"
                        ),
                        "naming_confidence": naming.get("confidence"),
                        "naming_confidence_kind": naming.get("confidence_kind"),
                    }
                )
                if naming["class"] == "counter_machine":
                    current = facts["frames"][row_index]["counter_machine"]
                    machine = {
                        "bbox": list(obj["bbox"]),
                        "fixture_id": track["fixture_id"],
                        "confidence": naming.get("confidence"),
                        "confidence_kind": naming.get("confidence_kind"),
                        "naming_status": naming.get(
                            "naming_status", "uncalibrated_hypothesis"
                        ),
                        "source": "temporally_fixed_proposal_local_siglip",
                    }
                    if current is None or float(machine["confidence"] or 0) > float(
                        current["confidence"] or 0
                    ):
                        facts["frames"][row_index]["counter_machine"] = machine
            LOG.info(
                "Fixture #%d: %s from %s, %.1f%% presence",
                track["fixture_id"],
                naming["class"],
                summary["raw_coco_classes"],
                100 * track["presence_fraction"],
            )
    facts["fixture_naming"] = {
        "model": "google/siglip-base-patch16-224",
        "runtime": "onnxruntime",
        "revision": "7fd15f0689c79d79e38b1c2e2e2370a7bf2761ed",
        "license": "Apache-2.0",
        "vocabulary": getattr(classifier, "output_names", FIXTURE_LABELS),
        "rejection_prompts": {
            key: value
            for key, value in getattr(classifier, "prompts", PROMPTS).items()
            if key.startswith("reject_")
        },
        "method": "full-video temporal presence and normalized geometry; <=3 local oriented crop views",
        "naming_policy": {
            "status": "uncalibrated_hypothesis",
            "min_agreeing_distinct_source_views": 2,
            "min_cosine_margin_against_all_names_and_rejections": getattr(
                classifier, "min_margin", 0.01
            ),
            "min_absolute_cosine": getattr(classifier, "min_similarity", None),
        },
        "thresholds": {
            "min_presence": min_presence,
            "max_center_drift": max_center_drift,
            "max_relative_scale_drift": max_scale_drift,
            "dropout_persistence": "same minimum 10-bin coverage and timeline span; >=20% of min_presence actual detections; >=3 hits",
        },
        "limitations": [
            "Similarity is uncalibrated; unknown/rejected fixtures are retained.",
            "A fixture must first be proposed by COCO; missed boxes are not hallucinated.",
            "Disappearance cannot be distinguished from occlusion by proposal boxes alone.",
            "Transient classes remain raw COCO proposals, not verified object identities.",
        ],
    }
    return facts
