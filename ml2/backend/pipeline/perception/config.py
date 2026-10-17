"""Local inference settings. Coordinates describe scene geometry, not pixel zones."""

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class PerceptionConfig:
    model_path: str = str(PROJECT_ROOT / "models/rtdetr_r18vd")
    backend: str = "onnxruntime"
    device: str = "cpu"
    image_size: int = 384
    batch_size: int = 1
    torch_threads: int = 2
    channels_last: bool = True
    sample_interval_sec: float = 0.5
    person_threshold: float = 0.45
    object_threshold: float = 0.55
    nms_iou: float = 0.75
    track_max_age_sec: float = 2.0
    track_min_hits: int = 2
    track_max_center_distance: float = 0.18
    track_min_iou: float = 0.05
    counter_geometry: dict[str, Any] | None = None
    refine_scene: bool = True
    reflection_config: dict[str, Any] | None = None
    fixture_model_path: str = str(PROJECT_ROOT / "models/siglip-base-patch16-224")
    anchor_vocabulary: str = "scene"
    role_method: str = "temporal"
    role_settings: dict[str, Any] | None = None
    state_engine_enabled: bool = True
    state_settings: dict[str, Any] | None = None
    scene_version: str = "v5"
    adaptive_after_sec: float = 150.0
    stop_after_sec: float = 168.0
    api_timeout_sec: float = 170.0
    validated_rule_ids: list[str] | None = None

    def __post_init__(self) -> None:
        if self.scene_version not in {"v4", "v5"}:
            raise ValueError("scene_version must be v4 or v5")
        if (
            not 0
            < self.adaptive_after_sec
            < self.stop_after_sec
            <= self.api_timeout_sec
        ):
            raise ValueError("Invalid adaptive/stop/API time budgets")
        if self.anchor_vocabulary not in {"scene", "legacy"}:
            raise ValueError("anchor_vocabulary must be scene or legacy")
        if self.role_method not in {"feature_softmax", "legacy_temporal", "temporal"}:
            raise ValueError(
                "role_method must be feature_softmax, legacy_temporal or temporal"
            )
        if self.backend not in {"onnxruntime", "pytorch"}:
            raise ValueError("backend must be onnxruntime or pytorch")
        if self.backend == "onnxruntime" and self.batch_size != 1:
            raise ValueError("The exported ONNX model uses batch_size=1")
        if self.device != "cpu" and not self.device.startswith(("cuda", "xpu", "mps")):
            raise ValueError("device must be cpu, cuda[:index], xpu[:index] or mps")
        if self.image_size < 256 or self.image_size % 32:
            raise ValueError("image_size must be a multiple of 32, at least 256")
        if min(self.batch_size, self.torch_threads, self.track_min_hits) < 1:
            raise ValueError(
                "batch_size, torch_threads and track_min_hits must be positive"
            )
        if self.sample_interval_sec != 0.5:
            raise ValueError("This facts schema requires a 0.5-second timeline")
        if not all(
            0 < value <= 1
            for value in (self.person_threshold, self.object_threshold, self.nms_iou)
        ):
            raise ValueError("thresholds must be in (0,1]")
        if self.track_max_age_sec <= 0 or self.track_max_center_distance <= 0:
            raise ValueError("tracking time and distance gates must be positive")
        if self.scene_version == "v5" and self.track_max_age_sec > 2.0:
            raise ValueError("v5 track joining cannot bridge more than two seconds")
        if self.reflection_config is not None:
            from .reflections import ReflectionConfig

            ReflectionConfig(**self.reflection_config)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_config(path: str | Path | None = None) -> PerceptionConfig:
    selected = path or os.environ.get("PERCEPTION_CONFIG")
    if not selected and (PROJECT_ROOT / "configs/perception.json").exists():
        selected = PROJECT_ROOT / "configs/perception.json"
    if not selected:
        return PerceptionConfig()
    with Path(selected).open(encoding="utf-8") as stream:
        values = json.load(stream)
    if not isinstance(values, dict):
        raise ValueError("Perception config must be a JSON object")
    for key in ("model_path", "fixture_model_path"):
        if key in values and not Path(values[key]).is_absolute():
            values[key] = str((PROJECT_ROOT / values[key]).resolve())
    return PerceptionConfig(**values)
