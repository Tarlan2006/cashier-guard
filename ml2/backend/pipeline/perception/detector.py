"""Local detector factory; default CPU runtime does not import PyTorch."""

import json
import logging
import time
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .config import PerceptionConfig

LOG = logging.getLogger(__name__)
MODEL_INFO = {
    "name": "PekingU/rtdetr_r18vd",
    "revision": "ac77a11ff0170a41b771c03264987f8ce2b0d753",
    "license": "Apache-2.0",
}


def _nms(detections: list[dict], threshold: float) -> list[dict]:
    kept: list[dict] = []
    for current in sorted(
        detections, key=lambda item: item["confidence"], reverse=True
    ):
        box = current["bbox"]
        duplicate = False
        for other in kept:
            if current["class"] != other["class"]:
                continue
            target = other["bbox"]
            intersection = max(
                0, min(box[2], target[2]) - max(box[0], target[0])
            ) * max(0, min(box[3], target[3]) - max(box[1], target[1]))
            area1 = (box[2] - box[0]) * (box[3] - box[1])
            area2 = (target[2] - target[0]) * (target[3] - target[1])
            if intersection / max(area1 + area2 - intersection, 1e-12) > threshold:
                duplicate = True
                break
        if not duplicate:
            kept.append(current)
    return kept


def preprocess_bgr(frame: np.ndarray, image_size: int) -> np.ndarray:
    """Match pinned RT-DETR PIL resize/rescale, with do_normalize=False."""
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    resized = Image.fromarray(rgb).resize(
        (image_size, image_size), Image.Resampling.BILINEAR
    )
    values = np.asarray(resized).astype(np.float32) * np.float32(1.0 / 255.0)
    return np.ascontiguousarray(values.transpose(2, 0, 1)[None])


class ONNXPersonObjectDetector:
    backend_name = "onnxruntime"

    def __init__(self, config: PerceptionConfig):
        import onnxruntime as ort

        self.config = config
        self.image_inferences = 0
        path = Path(config.model_path) / f"model_{config.image_size}.onnx"
        if not path.is_file():
            raise FileNotFoundError(
                f"Export local weights first: {path}; run scripts/export_perception_onnx.py"
            )
        if config.device != "cpu":
            raise ValueError(
                "This ONNX CPU build uses device=cpu. For GPU select backend=pytorch and device=cuda:0."
            )
        processor = json.loads(
            (Path(config.model_path) / "preprocessor_config.json").read_text(
                encoding="utf-8"
            )
        )
        if (
            processor.get("do_normalize")
            or processor.get("do_pad")
            or processor.get("resample") != 2
        ):
            raise ValueError(
                "ONNX preprocessing only supports the pinned PIL bilinear/rescale RT-DETR config"
            )
        if abs(float(processor.get("rescale_factor", 0)) - 1 / 255) > 1e-12:
            raise ValueError("Unexpected model rescale factor")
        self.labels = {
            int(key): value
            for key, value in json.loads(
                (Path(config.model_path) / "config.json").read_text(encoding="utf-8")
            )["id2label"].items()
        }
        started = time.perf_counter()
        options = ort.SessionOptions()
        options.intra_op_num_threads = config.torch_threads
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(
            str(path), sess_options=options, providers=["CPUExecutionProvider"]
        )
        if self.session.get_inputs()[0].shape != [
            1,
            3,
            config.image_size,
            config.image_size,
        ]:
            raise ValueError("ONNX input shape differs from config")
        self.load_sec = time.perf_counter() - started
        self.initialized_at = time.perf_counter()
        LOG.info("Loaded local ONNX %s on CPU in %.3fs", path.name, self.load_sec)

    def predict_batch(
        self, frames_bgr: list[np.ndarray], *, object_threshold: float | None = None
    ) -> list[list[dict]]:
        batches = []
        for frame in frames_bgr:
            self.image_inferences = getattr(self, "image_inferences", 0) + 1
            logits, predicted = self.session.run(
                ["logits", "pred_boxes"],
                {"pixel_values": preprocess_bgr(frame, self.config.image_size)},
            )
            flat_scores = (1 / (1 + np.exp(-np.clip(logits[0], -80, 80)))).ravel()
            queries, classes = logits.shape[1:]
            indices = np.argpartition(flat_scores, -queries)[-queries:]
            detections = []
            for index in indices:
                score = float(flat_scores[index])
                name = self.labels[int(index % classes)]
                object_gate = (
                    self.config.object_threshold
                    if object_threshold is None
                    else object_threshold
                )
                if score < (
                    self.config.person_threshold if name == "person" else object_gate
                ):
                    continue
                cx, cy, width, height = predicted[0, index // classes]
                box = np.clip(
                    [cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2],
                    0,
                    1,
                )
                if box[2] <= box[0] or box[3] <= box[1]:
                    continue
                detections.append(
                    {
                        "class": name,
                        "bbox": [round(float(x), 6) for x in box],
                        "confidence": round(score, 6),
                    }
                )
            batches.append(_nms(detections, self.config.nms_iou))
        return batches


@lru_cache(maxsize=1)
def _cached_detector(config_json: str):
    config = PerceptionConfig(**json.loads(config_json))
    if config.backend == "onnxruntime":
        return ONNXPersonObjectDetector(config)
    from .torch_detector import LocalPersonObjectDetector

    return LocalPersonObjectDetector(config)


def get_detector(config: PerceptionConfig):
    """Keep one resident model for repeated API calls; tracking is per video."""
    return _cached_detector(
        json.dumps(config.to_dict(), sort_keys=True, allow_nan=False)
    )
