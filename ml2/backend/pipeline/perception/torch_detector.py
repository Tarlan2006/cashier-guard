"""RT-DETR R18 inference from local Apache-2.0 weights only."""

import logging
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from transformers import AutoImageProcessor, RTDetrForObjectDetection

from .config import PerceptionConfig

LOG = logging.getLogger(__name__)
MODEL_INFO = {
    "name": "PekingU/rtdetr_r18vd",
    "revision": "ac77a11ff0170a41b771c03264987f8ce2b0d753",
    "license": "Apache-2.0",
    "runtime": "transformers/PyTorch, local_files_only=True",
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


class LocalPersonObjectDetector:
    backend_name = "pytorch"

    def __init__(self, config: PerceptionConfig):
        self.config = config
        directory = Path(config.model_path)
        if not directory.is_dir() or not (directory / "model.safetensors").is_file():
            raise FileNotFoundError(
                f"Download RT-DETR weights once into {directory}; inference never downloads weights"
            )
        torch.set_num_threads(config.torch_threads)
        torch.manual_seed(0)
        started = time.perf_counter()
        self.processor = AutoImageProcessor.from_pretrained(
            directory, local_files_only=True, backend="pil"
        )
        self.model = (
            RTDetrForObjectDetection.from_pretrained(directory, local_files_only=True)
            .to(config.device)
            .eval()
        )
        if config.channels_last:
            self.model.to(memory_format=torch.channels_last)
        # Dynamic anchor sizes allow configurable input resolution with the same weights.
        self.model.config.anchor_image_size = None
        self.load_sec = time.perf_counter() - started
        self.initialized_at = time.perf_counter()
        LOG.info(
            "Loaded %s on %s in %.3fs", MODEL_INFO["name"], config.device, self.load_sec
        )

    @torch.inference_mode()
    def predict_batch(
        self, frames_bgr: list[np.ndarray], *, object_threshold: float | None = None
    ) -> list[list[dict]]:
        if not frames_bgr:
            return []
        self.image_inferences = getattr(self, "image_inferences", 0) + len(frames_bgr)
        rgb = [cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) for frame in frames_bgr]
        inputs = self.processor(
            images=rgb,
            return_tensors="pt",
            size={"height": self.config.image_size, "width": self.config.image_size},
        ).to(self.config.device)
        if self.config.channels_last:
            inputs["pixel_values"] = inputs["pixel_values"].contiguous(
                memory_format=torch.channels_last
            )
        outputs = self.model(**inputs)
        object_gate = (
            self.config.object_threshold
            if object_threshold is None
            else object_threshold
        )
        processed = self.processor.post_process_object_detection(
            outputs, threshold=min(self.config.person_threshold, object_gate)
        )
        batches = []
        for result in processed:
            detections = []
            for score, label, box in zip(
                result["scores"].cpu().tolist(),
                result["labels"].cpu().tolist(),
                result["boxes"].cpu().tolist(),
            ):
                name = self.model.config.id2label[int(label)]
                threshold = (
                    self.config.person_threshold if name == "person" else object_gate
                )
                if score < threshold:
                    continue
                clipped = np.clip(box, 0, 1).tolist()
                if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
                    continue
                detections.append(
                    {
                        "class": name,
                        "bbox": [round(float(x), 6) for x in clipped],
                        "confidence": round(float(score), 6),
                    }
                )
            batches.append(_nms(detections, self.config.nms_iou))
        return batches
