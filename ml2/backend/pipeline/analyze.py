"""Local rule API; only explicitly validated catalog rules can emit events.

``analyze_video`` preserves the teammate's list[Event] interface. API adapters
should use ``analyze_report`` to expose partial analysis and warnings as well.
No labels, reference timecodes or per-video exceptions enter this module.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from backend.pipeline.analysis_worker import event_from_candidate, supervise
from backend.pipeline.perception import PerceptionConfig
from backend.pipeline.perception.config import load_config
from backend.schemas import Event

CATALOG_PATH = Path(__file__).resolve().parents[2] / "rules" / "catalog.yaml"


class AnalysisIncomplete(RuntimeError):
    """A list-only caller must not mistake a processing error for no events."""

    def __init__(self, message: str, report=None):
        super().__init__(message)
        self.report = report


def _catalog() -> dict[str, dict]:
    rows = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    catalog = {row["id"]: row for row in rows}
    if len(catalog) != len(rows):
        raise ValueError("Duplicate rule IDs in catalog")
    return catalog


def analyze_report(
    path: str | Path, *, config: PerceptionConfig | None = None
) -> dict[str, Any]:
    """Return JSON-safe verdict, events, completion status, timing and warnings.

    The subprocess returns evidence already collected at the hard deadline.
    ``partial`` must be displayed by the adapter: an empty event list from an
    incomplete run is not a guarantee that the video was completely checked.
    Windows launch scripts must use their normal ``if __name__ == '__main__'``
    guard when invoking this multiprocessing API.
    """
    started = time.perf_counter()
    selected = config or load_config()
    report = supervise(path, selected)
    report["perception_complete"] = report.get("analysis_complete", True)
    report["events"] = [event.to_dict() for event in report["events"]]
    report["enabled_rule_ids"] = list(selected.validated_rule_ids or [])
    if not report["enabled_rule_ids"]:
        report["warnings"].append("No validated rules enabled; perception only")
        report.update(status="partial", analysis_complete=False)
        if not report["events"]:
            report["verdict"] = None
    report["elapsed_sec"] = time.perf_counter() - started
    return report


def analyze_video(
    path: str | Path, *, config: PerceptionConfig | None = None, runtime=None
) -> list[Event]:
    """Return only confirmed events from enabled rules, with 1–3 source JPEGs."""
    report = (
        runtime.analyze(path)
        if runtime is not None
        else supervise(path, config or load_config())
    )
    if not report.get("perception_complete", report.get("analysis_complete", True)):
        raise AnalysisIncomplete(
            "Local analysis was incomplete; use analyze_report for collected evidence and diagnostics",
            report,
        )
    return report["events"]


def analyze_facts(
    path: str | Path, facts: dict[str, Any], *, config: PerceptionConfig | None = None
) -> list[Event]:
    """Adapt already evaluated facts from this exact video without inference.

    This helper consumes semantic-engine events, never person-presence facts.
    Only enabled catalog IDs are published; unknown or disabled candidates are
    excluded. Source video frames are decoded locally with orientation handling.
    """
    video = Path(path)
    if not video.is_file():
        raise FileNotFoundError(video)
    source = facts.get("video", {}).get("name")
    if source is not None and source != video.name:
        raise ValueError(
            f"Facts video name {source!r} does not match input {video.name!r}"
        )
    selected = config or load_config()
    catalog = _catalog()
    allowed = set(selected.validated_rule_ids or [])
    if not allowed <= set(catalog):
        raise ValueError("Validated rule ID is absent from catalog")
    events = []
    for candidate in facts.get("semantic_engine", {}).get("events", []):
        rule = candidate["rule_id"]
        if rule in allowed:
            events.append(event_from_candidate(video, candidate, catalog[rule]))
    return sorted(events, key=lambda event: (event.timecode_sec, event.rule_id))
