"""Streaming, local 0.5-second facts timeline for one oriented video."""

import argparse
import json
import logging
import time
from dataclasses import asdict
from pathlib import Path

from backend.pipeline.video import VideoReader

from .config import PerceptionConfig, load_config
from .counter import CounterObserver
from .roles import RoleAssigner
from .tracking import PersonTracker
from .appearance import clothing_histogram
from backend.pipeline.budget import RuntimeBudget, BudgetExpired

LOG = logging.getLogger(__name__)


def perceive_video(
    path: str | Path,
    config: PerceptionConfig | None = None,
    output_path: str | Path | None = None,
    *,
    detector=None,
    raw_output_path: str | Path | None = None,
    budget: RuntimeBudget | None = None,
) -> dict:
    """Return facts and optionally write facts.json. Never reads dataset labels.

    ``detector`` permits explicit reuse for a local batch service / benchmark.
    Only actual detections enter persons; track predictions are not visible facts.
    """
    started = time.perf_counter()
    config = config if config is not None else load_config()
    budget = budget or RuntimeBudget(
        started=started,
        adaptive_after_sec=config.adaptive_after_sec,
        stop_after_sec=config.stop_after_sec,
    )
    adaptive = config.scene_version == "v5"
    partial = False
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    # Import lazily so contracts, video utilities and tests do not load PyTorch.
    from .detector import MODEL_INFO, get_detector

    detector_request_started = time.perf_counter()
    if detector is None:
        detector = get_detector(config)
    new_detector = getattr(detector, "initialized_at", 0.0) >= detector_request_started
    images_before = getattr(detector, "image_inferences", 0)
    tracker = PersonTracker(
        max_age_sec=config.track_max_age_sec,
        min_hits=config.track_min_hits,
        max_center_distance=config.track_max_center_distance,
        min_iou=config.track_min_iou,
    )
    roles = RoleAssigner(config.counter_geometry)
    counter = CounterObserver(config.counter_geometry)
    rows, batch = [], []
    inference_sec = 0.0

    def process_batch() -> None:
        nonlocal inference_sec
        infer_started = time.perf_counter()
        batches = detector.predict_batch([sample.frame_bgr for sample in batch])
        inference_sec += time.perf_counter() - infer_started
        if len(batches) != len(batch):
            raise ValueError("Detector returned a different number of batch results")
        for sample, detections in zip(batch, batches):
            if adaptive:
                for obj in detections:
                    if obj["class"] == "person":
                        obj["clothing_histogram"] = clothing_histogram(
                            sample.frame_bgr, obj["bbox"]
                        )
            persons = tracker.update(
                [obj for obj in detections if obj["class"] == "person"],
                sample.timestamp_sec,
            )
            persons = roles.assign(persons, timestamp_sec=sample.timestamp_sec)
            objects = [obj for obj in detections if obj["class"] != "person"]
            rows.append(
                {
                    "timestamp_sec": sample.timestamp_sec,
                    "actual_timestamp_sec": sample.actual_timestamp_sec,
                    "persons": persons,
                    "objects": objects,
                    "counter": counter.update(persons, objects, sample.frame_bgr),
                }
            )
        if len(rows) % 40 == 0:
            LOG.info("%s: %d timeline samples processed", path.name, len(rows))
        batch.clear()

    with VideoReader(path) as reader:
        metadata = asdict(reader.metadata)
        schedule = (
            (
                lambda t: budget.interval(
                    t, reader.metadata.duration_sec, config.sample_interval_sec
                )
            )
            if adaptive
            else config.sample_interval_sec
        )
        try:
            for sample in reader.iter_samples(interval_sec=schedule):
                if adaptive:
                    budget.check()
                    if budget.remaining < 10.0:
                        partial = True
                        break
                batch.append(sample)
                if len(batch) == config.batch_size:
                    process_batch()
        except BudgetExpired:
            partial = True
        if batch:
            process_batch()
    if not rows:
        raise ValueError(f"No video samples decoded: {path}")
    detector_load_sec = detector.load_sec if new_detector else 0.0
    timeline_images = (
        getattr(detector, "image_inferences", images_before + len(rows)) - images_before
    )
    elapsed = time.perf_counter() - started
    result = {
        "schema_version": "1.0",
        "video": {"name": path.name, **metadata},
        "sample_interval_sec": config.sample_interval_sec,
        "coordinate_system": "normalized xyxy in orientation-corrected frames, origin top-left",
        "model": dict(MODEL_INFO, runtime=detector.backend_name),
        "config": config.to_dict(),
        "limitations": [
            "Roles are positional candidates, not verified identities or job titles.",
            "Uncalibrated counter geometry leaves roles unknown and counter changes empty.",
            "Objects are COCO classes; money, banknotes and cashier actions are not recognized.",
            "Detection gaps may create track ID changes; no invisible people are emitted.",
        ],
        "frames": rows,
        "timing": {
            "model_load_sec": detector_load_sec,
            "detector_inference_sec": inference_sec,
            "processing_sec": elapsed,
            "write_sec": 0.0,
            "total_sec": elapsed,
        },
    }
    result["runtime"] = dict(
        complete=not partial,
        adaptive_interval_changes=budget.changes,
        warnings=["Video processing stopped at the time budget"] if partial else [],
    )
    result["sampling_interval_by_time"] = {
        str(row["timestamp_sec"]): (
            rows[i]["timestamp_sec"] - rows[i - 1]["timestamp_sec"]
            if i
            else config.sample_interval_sec
        )
        for i, row in enumerate(rows)
    }
    if raw_output_path is not None:
        raw_output = Path(raw_output_path)
        raw_output.parent.mkdir(parents=True, exist_ok=True)
        raw_output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )
    if config.refine_scene:
        from .refine import refine_facts

        refine_facts(path, result, config, detector=detector, budget=budget)
        result["timing"]["scene_refinement_sec"] = result["refinement"]["total_sec"]
        result["timing"]["processing_sec"] = time.perf_counter() - started
        result["timing"]["total_sec"] = time.perf_counter() - started
    result["sampling"] = {
        "timeline_interval_sec": config.sample_interval_sec,
        "timeline_samples": len(rows),
        "timeline_detector_images": timeline_images,
        "additional_proposal_images": max(
            0,
            getattr(detector, "image_inferences", images_before + len(rows))
            - images_before
            - timeline_images,
        ),
        "video_detection_cache_used": False,
    }
    result["sampling"]["adaptive"] = adaptive
    result["sampling"]["interval_changes"] = budget.changes
    result["sampling"]["last_source_time_sec"] = rows[-1]["actual_timestamp_sec"]
    if output_path is not None:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        write_started = time.perf_counter()
        output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )
        if "events" in result:
            events_name = (
                output.name.replace(".facts.json", ".events.json")
                if output.name.endswith(".facts.json")
                else "events.json"
            )
            output.with_name(events_name).write_text(
                json.dumps(
                    {
                        "events": result.get("events", []),
                        "state_events": result.get(
                            "semantic_engine", result.get("state_engine", {})
                        ).get("events", []),
                        "state_engine": result.get(
                            "semantic_engine", result.get("state_engine", {})
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                    allow_nan=False,
                ),
                encoding="utf-8",
            )
        result["timing"]["write_sec"] = time.perf_counter() - write_started
        result["timing"]["total_sec"] = time.perf_counter() - started
        # Persist the measured write time. External benchmark also measures the
        # complete call including this final small metadata update.
        output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )
    LOG.info(
        "%s: %d samples, %.3fs total",
        path.name,
        len(rows),
        result["timing"]["total_sec"],
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path, default=Path("debug/facts.json"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    facts = perceive_video(args.video, load_config(args.config), args.output)
    print(
        json.dumps(
            {"frames": len(facts["frames"]), "timing": facts["timing"]}, indent=2
        )
    )


if __name__ == "__main__":
    main()
