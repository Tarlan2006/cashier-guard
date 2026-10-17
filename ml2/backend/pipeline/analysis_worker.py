"""Spawn-safe, local analysis worker. Parent owns the hard return deadline."""

import logging
import time
from pathlib import Path

from backend.pipeline.budget import RuntimeBudget
from backend.pipeline.perception import PerceptionConfig, perceive_video
from backend.pipeline.video import extract_jpegs
from backend.schemas import Event


def event_from_candidate(path: str | Path, candidate: dict, catalog: dict) -> Event:
    timestamp = float(candidate["timecode_sec"])
    evidence = extract_jpegs(
        path, [max(0.0, timestamp - 1.0), timestamp, timestamp + 1.0]
    )
    if not 1 <= len(evidence) <= 3:
        raise ValueError("An event needs 1-3 source JPEGs")
    return Event(
        type=catalog["type"],
        rule_id=candidate["rule_id"],
        timecode_sec=timestamp,
        description=candidate["description"],
        confidence=float(candidate["confidence"]),
        frames=[jpg for _, jpg in evidence],
        frame_timecodes_sec=[t for t, _ in evidence],
        first_seen=timestamp,
        confirmed_at=float(candidate.get("confirmed_at", timestamp)),
    )


def run_local(
    path: str | Path, config: PerceptionConfig, *, budget=None, on_event=None
) -> tuple[list[Event], dict]:
    import json
    from .semantic_engine import evaluate_semantic_states
    from .track_rules import TRACK_RULE_IDS, evaluate_track_rules
    from .zone_linear import get_linear_zone_model

    budget = budget or RuntimeBudget(
        adaptive_after_sec=config.adaptive_after_sec,
        stop_after_sec=config.stop_after_sec,
    )
    catalog_path = Path(__file__).resolve().parents[2] / "rules/catalog.yaml"
    catalog = {
        row["id"]: row for row in json.loads(catalog_path.read_text(encoding="utf-8"))
    }
    allowed = set(config.validated_rule_ids or [])
    if not allowed <= set(catalog):
        raise ValueError("Validated rule ID is absent from the catalog")
    facts = perceive_video(path, config, budget=budget)
    events = []

    def emit(candidate):
        if candidate["rule_id"] not in allowed:
            return
        budget.check()
        event = event_from_candidate(path, candidate, catalog[candidate["rule_id"]])
        events.append(event)
        if on_event:
            on_event(event)

    if allowed & TRACK_RULE_IDS and budget.remaining > 1.0:
        for candidate in evaluate_track_rules(facts, config.state_settings):
            if candidate["rule_id"] in allowed:
                emit(candidate)
    semantic_rules = allowed - TRACK_RULE_IDS
    if semantic_rules and budget.remaining > 1.0:
        heads = (config.state_settings or {}).get("zone_classifier_path")
        if not heads:
            raise ValueError(
                "Validated zone rules require local linear classifier heads"
            )
        head_path = Path(heads)
        if not head_path.is_absolute():
            head_path = Path(__file__).resolve().parents[2] / head_path
        model = get_linear_zone_model(
            config.fixture_model_path,
            str(head_path),
            config.torch_threads,
            config.device,
        )
        evaluate_semantic_states(
            path,
            facts,
            model,
            config.state_settings,
            budget=budget,
            on_event=emit,
            active_rules=semantic_rules,
        )
    return events, facts


def analysis_worker(path: str, config_values: dict, queue, started: float) -> None:
    """Only trusted local pickle messages; no model/video service requests."""
    config = PerceptionConfig(**config_values)
    budget = RuntimeBudget(
        started=started,
        adaptive_after_sec=config.adaptive_after_sec,
        stop_after_sec=config.stop_after_sec,
    )
    try:
        events, facts = run_local(
            path,
            config,
            budget=budget,
            on_event=lambda event: queue.put(("event", event)),
        )
        queue.put(
            (
                "done",
                dict(
                    complete=facts.get("runtime", {}).get("complete", True),
                    warnings=facts.get("runtime", {}).get("warnings", []),
                    sampling=facts.get("sampling", {}),
                    timing=facts.get("timing", {}),
                ),
            )
        )
    except Exception as exc:
        if isinstance(exc, (FileNotFoundError, ValueError)):
            logging.info("Local input could not be completed: %s", type(exc).__name__)
        else:
            logging.exception("Local analysis returned partial evidence")
        queue.put(
            (
                "partial",
                dict(
                    complete=False,
                    warnings=[f"{type(exc).__name__}: {exc}"],
                    error_type=type(exc).__name__,
                ),
            )
        )


def supervise(
    path: str | Path, config: PerceptionConfig, *, worker=analysis_worker
) -> dict:
    import multiprocessing as mp
    import queue as queues

    started = time.perf_counter()
    context = mp.get_context("spawn")
    queue = context.Queue()
    process = context.Process(
        target=worker, args=(str(path), config.to_dict(), queue, started), daemon=True
    )
    events = []
    metadata = dict(complete=False, warnings=[])
    try:
        process.start()
        # Reserve termination/queue cleanup within the outer return budget.
        deadline = started + max(0.05, config.api_timeout_sec - 1.0)
        while time.perf_counter() < deadline:
            try:
                kind, payload = queue.get(
                    timeout=min(0.2, max(0.001, deadline - time.perf_counter()))
                )
            except queues.Empty:
                if not process.is_alive():
                    break
                continue
            if kind == "event":
                events.append(payload)
            elif kind in {"done", "partial"}:
                metadata = payload
                break
        else:
            metadata["warnings"].append(
                "Hard API time budget reached; returning collected events"
            )
        if not metadata["complete"] and not metadata["warnings"]:
            metadata["warnings"].append(
                "Worker stopped before complete analysis; returning collected events"
            )
    except Exception as exc:
        metadata.update(complete=False, warnings=[f"{type(exc).__name__}: {exc}"])
    finally:
        if process.pid is not None:
            if process.is_alive():
                process.terminate()
            process.join(timeout=0.1)
            if process.is_alive():
                process.kill()
        queue.cancel_join_thread()
        queue.close()
    # No status=failed and no fabricated success on timeout or an unreadable file.
    return dict(
        verdict=(
            "нарушение"
            if events
            else ("нарушений нет" if metadata["complete"] else None)
        ),
        status="completed" if metadata["complete"] else "partial",
        events=events,
        analysis_complete=metadata["complete"],
        warnings=metadata["warnings"],
        elapsed_sec=time.perf_counter() - started,
        sampling=metadata.get("sampling", {}),
        timing=metadata.get("timing", {}),
        error_type=metadata.get("error_type"),
    )
