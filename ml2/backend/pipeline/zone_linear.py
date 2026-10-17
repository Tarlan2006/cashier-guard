"""Frozen SigLIP crop encoder plus a local numeric logistic state head.

Artifacts use NPZ (no pickle execution); only independently validated heads
may be enabled. Missing heads yield unknown, never a zero-shot fallback.
"""

from functools import lru_cache
from pathlib import Path
import numpy as np
from .perception.fixtures import get_fixture_classifier


class LinearZoneModel:
    def __init__(self, encoder, directory: str | Path):
        self.encoder = encoder
        self.heads = {}
        for domain in ("table", "safe"):
            path = Path(directory) / f"{domain}_linear.npz"
            if path.is_file():
                with np.load(path, allow_pickle=False) as data:
                    self.heads[domain] = {key: data[key].copy() for key in data.files}

    def classify(self, crop: np.ndarray, domain: str, min_margin: float = 0.01) -> dict:
        if domain not in self.heads:
            return dict(
                state="unknown",
                candidate="unknown",
                margin=0.0,
                scores={"unknown": 1.0},
                probability_kind="missing_linear_head",
            )
        head = self.heads[domain]
        x = (self.encoder.encode_crop(crop) - head["mean"]) / head["scale"]
        logit = float((head["coef"] * x).sum() + head["intercept"].item())
        probability = float(1 / (1 + np.exp(-np.clip(logit, -50, 50))))
        negative, positive = {"table": ("empty", "items"), "safe": ("closed", "open")}[
            domain
        ]
        scores = {negative: 1 - probability, positive: probability, "unknown": 0.0}
        candidate = positive if probability >= 0.5 else negative
        margin = abs(2 * probability - 1)
        return dict(
            state=candidate if margin >= max(0.2, min_margin) else "unknown",
            candidate=candidate,
            margin=margin,
            scores=scores,
            probability_kind="uncalibrated_weak_label_logistic",
        )


@lru_cache(maxsize=1)
def get_linear_zone_model(
    model_dir: str, head_dir: str, threads: int = 2, device: str = "cpu"
):
    return LinearZoneModel(get_fixture_classifier(model_dir, threads, device), head_dir)
