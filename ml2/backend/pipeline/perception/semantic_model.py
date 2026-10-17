"""One local SigLIP vision session shared by fixed anchor/state prompt banks."""

from functools import lru_cache
from pathlib import Path
import numpy as np

from .fixtures import get_fixture_classifier


class LocalSemanticModel:
    def __init__(self, model_dir: str, threads: int = 2, device: str = "cpu"):
        self.encoder = get_fixture_classifier(model_dir, threads, device)
        with np.load(
            Path(model_dir) / "local_prompt_features.npz", allow_pickle=False
        ) as data:
            self.labels = data["labels"].astype(str)
            self.features = data["features"].astype(np.float32)

    def scores(self, crop: np.ndarray, domain: str) -> dict[str, float]:
        values = (self.features * self.encoder.encode_crop(crop)).sum(axis=1)
        names = sorted(
            {str(label) for label in self.labels if label.startswith(domain + ".")}
        )
        return {
            key.split(".", 1)[1]: float(
                values[self.labels == key].max()
                if domain == "table"
                else values[self.labels == key].mean()
            )
            for key in names
        }

    def classify(self, crop: np.ndarray, domain: str, min_margin: float = 0.01) -> dict:
        scores = self.scores(crop, domain)
        order = sorted(scores, key=scores.get, reverse=True)
        name = order[0]
        margin = scores[name] - scores[order[1]]
        return dict(
            state=name if margin >= min_margin and name != "unknown" else "unknown",
            candidate=name,
            margin=margin,
            scores=scores,
            probability_kind="uncalibrated_text_image_similarity",
        )


@lru_cache(maxsize=1)
def get_semantic_model(
    model_dir: str, threads: int = 2, device: str = "cpu"
) -> LocalSemanticModel:
    return LocalSemanticModel(model_dir, threads, device)
