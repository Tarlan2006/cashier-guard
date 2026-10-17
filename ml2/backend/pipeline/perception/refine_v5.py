"""Bounded local scene pass with temporal roles and semantic zone candidates."""

from pathlib import Path
import time

from backend.pipeline.budget import BudgetExpired, RuntimeBudget
from .scene_tracks import repair_tracks, apply_hysteresis
from .reflections import annotate_reflections, annotate_glass_context
from .roles_v2 import assign_temporal_roles
from .timestamps import annotate_first_seen


def refine_v5(
    path: str | Path,
    facts: dict,
    config,
    *,
    budget: RuntimeBudget | None = None,
    detector=None
) -> dict:
    started = time.perf_counter()
    facts["config"] = config.to_dict()
    budget = budget or RuntimeBudget(
        adaptive_after_sec=config.adaptive_after_sec,
        stop_after_sec=config.stop_after_sec,
    )
    runtime = facts.setdefault("runtime", dict(complete=True, warnings=[]))
    annotate_reflections(facts, config.reflection_config)
    repair_tracks(facts, max_gap_sec=2.0, require_appearance=True)
    annotate_reflections(facts, config.reflection_config)
    apply_hysteresis(facts)
    # Fast facts are available even if the optional semantic stage exhausts
    # the budget. No anchor names are fabricated when that stage is skipped.
    facts.setdefault("fixtures", [])
    assign_temporal_roles(facts, config.role_settings)
    annotate_first_seen(facts)
    try:
        budget.check()
        from .semantic_model import get_semantic_model
        from .anchors_v2 import discover_scene_anchors_v5

        model = get_semantic_model(
            config.fixture_model_path, config.torch_threads, config.device
        )
        if budget.remaining > 8.0:
            annotate_glass_context(path, facts, classifier=model.encoder)
            apply_hysteresis(facts)
        if detector is None:
            from .detector import get_detector

            detector = get_detector(config)
        discover_scene_anchors_v5(path, facts, model, detector, budget=budget)
        assign_temporal_roles(facts, config.role_settings)
        annotate_first_seen(facts)
    except BudgetExpired:
        runtime["complete"] = False
        runtime.setdefault("warnings", []).append(
            "Scene refinement stopped at local time budget"
        )
    for row in facts["frames"]:
        row["people_count"] = sum(p["counted"] for p in row["persons"])
        row["certain_people_count"] = sum(
            p["counted"] and not p["uncertain"] for p in row["persons"]
        )
        row["uncertain_people_count"] = sum(
            p["counted"] and p["uncertain"] for p in row["persons"]
        )
        row["reflection_count"] = sum(p["is_reflection"] for p in row["persons"])
        row["counter_machine"] = row.get("counter_machine")
        row["safe"] = row.get("safe")
    from .counter import refine_counter_facts

    refine_counter_facts(facts)
    facts["schema_version"] = "1.4"
    facts["refinement"] = dict(
        version="perception-v5",
        total_sec=time.perf_counter() - started,
        fixture_sec=facts.get("anchor_pass", {}).get("total_sec", 0.0),
        scope="local multiframe anchors, clothing associations and temporal role hypotheses",
    )
    return facts
