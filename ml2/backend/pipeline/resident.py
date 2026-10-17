"""One resident local model worker, bounded requests, no per-request reload."""

from __future__ import annotations
import multiprocessing as mp
import queue
import threading
import time
import uuid
from pathlib import Path
from .analysis_worker import run_local
from .budget import RuntimeBudget
from .perception import PerceptionConfig


class RuntimeBusy(RuntimeError):
    pass


def resident_worker(config_values: dict, incoming, outgoing) -> None:
    config = PerceptionConfig(**config_values)
    try:
        from .perception.detector import get_detector
        from .perception.semantic_model import get_semantic_model

        get_detector(config)
        semantic = get_semantic_model(
            config.fixture_model_path, config.torch_threads, config.device
        )
        outgoing.put(("ready", None, dict(detector_loads=1, vision_encoder_loads=1)))
    except Exception as exc:
        outgoing.put(("startup_error", None, dict(error_type=type(exc).__name__)))
        return
    while True:
        request = incoming.get()
        if request is None:
            return
        request_id, path, started = request
        budget = RuntimeBudget(
            started=started,
            adaptive_after_sec=config.adaptive_after_sec,
            stop_after_sec=config.stop_after_sec,
        )
        try:
            semantic.encoder.clear_video_cache()
            _, facts = run_local(
                path,
                config,
                budget=budget,
                on_event=lambda event: outgoing.put(("event", request_id, event)),
            )
            runtime = facts.get("runtime", {})
            result = dict(
                perception_complete=runtime.get("complete", True),
                warnings=runtime.get("warnings", []),
                error_type=None,
                sampling=facts.get("sampling", {}),
                timing=facts.get("timing", {}),
            )
        except Exception as exc:
            result = dict(
                perception_complete=False,
                warnings=["Local inference did not complete"],
                error_type=type(exc).__name__,
            )
        finally:
            semantic.encoder.clear_video_cache()
        result["cross_request_video_cache"] = False
        outgoing.put(("done", request_id, result))


class ResidentRuntime:
    def __init__(self, config: PerceptionConfig, *, worker=resident_worker):
        self.config = config
        self.context = mp.get_context("spawn")
        self.incoming = self.context.Queue()
        self.outgoing = self.context.Queue()
        self.process = self.context.Process(
            target=worker,
            args=(config.to_dict(), self.incoming, self.outgoing),
            daemon=True,
        )
        self.lock = threading.Lock()
        self.ready = False
        self.model_loads = {}

    def start(self, timeout: float = 60.0) -> None:
        self.process.start()
        try:
            kind, _, info = self.outgoing.get(timeout=timeout)
        except queue.Empty as exc:
            self.close()
            raise RuntimeError("Local model startup timed out") from exc
        if kind != "ready":
            self.close()
            raise RuntimeError("Local model startup error: " + info["error_type"])
        self.ready = True
        self.model_loads = info

    def analyze(self, path: str | Path) -> dict:
        if not self.ready or not self.process.is_alive():
            raise RuntimeError("Resident worker unavailable; restart service")
        if not self.lock.acquire(blocking=False):
            raise RuntimeBusy("One local inference request is already running")
        started = time.perf_counter()
        request_id = uuid.uuid4().hex
        events = []
        result = dict(
            perception_complete=False,
            error_type="TimeoutError",
            warnings=["Hard inference deadline reached"],
        )
        try:
            self.incoming.put((request_id, str(path), started))
            deadline = started + max(0.05, self.config.api_timeout_sec - 1.0)
            while time.perf_counter() < deadline:
                try:
                    kind, identifier, payload = self.outgoing.get(
                        timeout=min(0.2, max(0.001, deadline - time.perf_counter()))
                    )
                except queue.Empty:
                    if not self.process.is_alive():
                        result["error_type"] = "WorkerExited"
                        break
                    continue
                if identifier != request_id:
                    continue
                if kind == "event":
                    events.append(payload)
                elif kind == "done":
                    result = payload
                    break
            else:
                self.close()
            complete = result["perception_complete"] and bool(
                self.config.validated_rule_ids
            )
            if not self.config.validated_rule_ids:
                result["warnings"].append("No rule passed the validation gate")
            return dict(
                **result,
                events=events,
                elapsed_sec=time.perf_counter() - started,
                status="completed" if complete else "partial",
                analysis_complete=complete,
                enabled_rule_ids=self.config.validated_rule_ids or [],
            )
        finally:
            self.lock.release()

    def close(self) -> None:
        self.ready = False
        if self.process.pid is not None:
            if self.process.is_alive():
                self.process.terminate()
            self.process.join(timeout=0.1)
            if self.process.is_alive():
                self.process.kill()
        for channel in (self.incoming, self.outgoing):
            channel.cancel_join_thread()
            channel.close()
