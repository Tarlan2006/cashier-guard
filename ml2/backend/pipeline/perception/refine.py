"""Full-video local scene hypotheses, before any event processing."""

import time
from pathlib import Path

from .config import PerceptionConfig
from .fixtures import annotate_fixtures
from .reflections import annotate_reflections, annotate_glass_context
from .scene_tracks import repair_tracks, apply_hysteresis
from .roles import infer_scene_roles


def refine_facts(
    path: str | Path,
    facts: dict,
    config: PerceptionConfig | None = None,
    *,
    classifier=None,
    detector=None,
    anchor_classifier=None,
    budget=None
) -> dict:
    """Preserve raw evidence, repair tracks and annotate local scene hypotheses.

    ``classifier`` is injectable for offline tests and explicit model reuse.
    The source is reread for bounded proposal views and fixed-patch visibility.
    """
    config = config or PerceptionConfig()
    if config.scene_version == "v5":
        from .refine_v5 import refine_v5

        return refine_v5(path, facts, config, budget=budget, detector=detector)
    facts["config"] = config.to_dict()
    started = time.perf_counter()
    annotate_reflections(facts, config.reflection_config)
    repair_tracks(facts, max_gap_sec=3.0, require_appearance=False)
    annotate_reflections(facts, config.reflection_config)
    if classifier is None:
        from .fixtures import get_fixture_classifier

        classifier = get_fixture_classifier(
            config.fixture_model_path, config.torch_threads, config.device
        )
    annotate_glass_context(path, facts, classifier=classifier)
    apply_hysteresis(facts)
    reflection_sec = time.perf_counter() - started
    naming_started = time.perf_counter()
    if config.anchor_vocabulary == "scene" and anchor_classifier is None:
        from .anchors import get_scene_classifier

        anchor_classifier = get_scene_classifier(
            config.fixture_model_path, config.torch_threads, config.device
        )
    anchor_classifier = anchor_classifier or classifier
    annotate_fixtures(
        path,
        facts,
        classifier=anchor_classifier,
        model_dir=config.fixture_model_path,
        threads=config.torch_threads,
        device=config.device,
    )
    if detector is None:
        from .detector import get_detector

        detector = get_detector(config)
    if config.anchor_vocabulary == "scene":
        from .anchors import discover_scene_anchors, sanitize_scene_fixtures

        sanitize_scene_fixtures(facts)
        discover_scene_anchors(path, facts, detector, anchor_classifier)
    else:
        from .proposals import discover_counter_machine

        discover_counter_machine(path, facts, detector, classifier)
    fixture_sec = time.perf_counter() - naming_started
    role_started = time.perf_counter()
    if config.role_method == "feature_softmax":
        from .prob_roles import assign_probabilistic_roles

        assign_probabilistic_roles(facts, config.role_settings)
    else:
        infer_scene_roles(facts)
    from .counter import refine_counter_facts

    refine_counter_facts(facts)
    for frame in facts["frames"]:
        frame["people_count"] = sum(person["counted"] for person in frame["persons"])
        frame["certain_people_count"] = sum(
            person["counted"] and not person["uncertain"] for person in frame["persons"]
        )
        frame["uncertain_people_count"] = sum(
            person["counted"] and person["uncertain"] for person in frame["persons"]
        )
        frame["reflection_count"] = sum(
            person["is_reflection"] for person in frame["persons"]
        )
    from .timestamps import annotate_first_seen

    annotate_first_seen(facts)
    if config.state_engine_enabled:
        from backend.pipeline.state_engine import build_state_events

        build_state_events(facts, config.state_settings)
    facts["schema_version"] = "1.3"
    facts["refinement"] = {
        "version": "perception-v4",
        "reflection_sec": reflection_sec,
        "fixture_sec": fixture_sec,
        "roles_counter_counts_sec": time.perf_counter() - role_started,
        "total_sec": time.perf_counter() - started,
        "scope": "Heuristic local scene facts; roles and fixture names are candidates, not verified identities.",
    }
    facts["limitations"] = [
        "Reflections are confidence/relative-scale hypotheses, not a segmentation of glass or floor.",
        "Low-confidence real people may resemble reflections; all original tracks remain available.",
        "Roles are uncalibrated temporal/positional feature hypotheses from scene anchors; ambiguity stays unknown.",
        "Fixture names are local SigLIP crop hypotheses with rejection; transient COCO names remain unverified.",
        "Uncalibrated counter geometry leaves counter changes empty; no cash transfers are inferred.",
        "Detection gaps may create ID changes; undetected people or objects are not invented.",
    ]
    return facts
