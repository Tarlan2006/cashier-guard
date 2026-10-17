"""Local object/person perception, geometry and short-term tracking."""

from .config import PerceptionConfig, load_config
from pathlib import Path
from typing import Any


def perceive_video(
    path: str | Path,
    config: PerceptionConfig | None = None,
    output_path: str | Path | None = None,
    **kwargs: Any
) -> dict[str, Any]:
    from .run import perceive_video as run

    return run(path, config=config, output_path=output_path, **kwargs)


__all__ = ["PerceptionConfig", "load_config", "perceive_video"]
