"""Scheduling/storage checks; actual codecs and subprocess cleanup have separate media tests."""
import asyncio
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main, media, pipeline
from app.config import Settings
from app.main import create_app
from app.models import AnalysisResult

KEY = "test-normalization-key"
HEADERS = {"X-API-Key": KEY}


def settings(tmp_path, **values):
    return Settings(api_key=KEY, mode="demo", storage=tmp_path / "storage", **values)


def install_pipeline(monkeypatch):
    async def inspect(path, **kwargs):
        return SimpleNamespace(duration_sec=2.0, start_time=0.0)

    async def analyze(path, duration, config, scenario, stage):
        assert path.name.endswith(".normalized.mp4")
        assert path.exists()
        stage("analyzing")
        return AnalysisResult(verdict="no_violation", violations=[])

    monkeypatch.setattr(media, "inspect_video", inspect)
    monkeypatch.setattr(pipeline, "analyze", analyze)


def submit(client, content=b"source", name="clip.mkv"):
    response = client.post("/api/v1/analyze", files={"file": (name, content)}, headers=HEADERS)
    assert response.status_code == 202, response.text
    return response.json()["job_id"]


def wait(client, job_id):
    for _ in range(250):
        result = client.get(f"/api/v1/jobs/{job_id}", headers=HEADERS).json()
        if result["status"] != "processing":
            return result
        time.sleep(0.01)
    pytest.fail("Processing did not terminate")


def no_inputs(config):
    assert not list(config.storage.glob("*.upload"))
    assert not list(config.storage.glob("*.normalized.mp4"))


def test_normalization_slots_and_wait_share_total_deadline(tmp_path, monkeypatch):
    install_pipeline(monkeypatch)
    calls = []
    running = 0
    maximum = 0

    async def normalize(source, output, info, *, timeout, max_bytes):
        nonlocal running, maximum
        running += 1
        maximum = max(maximum, running)
        calls.append(timeout)
        output.write_bytes(b"partial")
        try:
            await asyncio.sleep(60)
        finally:
            running -= 1

    monkeypatch.setattr(media, "normalize_video", normalize)
    config = settings(tmp_path, workers=2, normalization_workers=1, timeout=0.12)
    with TestClient(create_app(config)) as client:
        first, second = submit(client), submit(client)
        for job_id in (first, second):
            result = wait(client, job_id)
            assert result["error_code"] == "TIMEOUT"
            assert result["verdict"] is None
            assert result["timings_sec"]["total"] < 0.35
        assert maximum == 1 and running == 0
        assert calls and all(0 < remaining <= 0.12 for remaining in calls)
        assert not client.app.state.normalization_reservations
        no_inputs(config)
        async def quick(source, output, info, **kwargs):
            output.write_bytes(b"ready")
            return info
        monkeypatch.setattr(media, "normalize_video", quick)
        assert wait(client, submit(client))["status"] == "done"


def test_timeout_waits_for_converter_shutdown_before_deleting_files(tmp_path, monkeypatch):
    install_pipeline(monkeypatch)
    child_stopped = []

    async def normalize(source, output, info, **kwargs):
        output.write_bytes(b"partial")
        try:
            await asyncio.sleep(60)
        finally:
            # Model asynchronous subprocess kill/reap, including its final output write.
            assert source.exists() and output.exists()
            await asyncio.sleep(0.025)
            output.write_bytes(b"last bytes before process exits")
            child_stopped.append(True)

    monkeypatch.setattr(media, "normalize_video", normalize)
    config = settings(tmp_path, timeout=0.08)
    with TestClient(create_app(config)) as client:
        result = wait(client, submit(client))
        assert child_stopped and result["error_code"] == "TIMEOUT"
        no_inputs(config)


def test_normalization_reservation_blocks_upload_without_double_counting_output(tmp_path, monkeypatch):
    install_pipeline(monkeypatch)
    entered = threading.Event()
    release = threading.Event()
    limits = []

    async def normalize(source, output, info, *, timeout, max_bytes):
        limits.append(max_bytes)
        output.write_bytes(b"n" * (512 * 1024))
        entered.set()
        while not release.is_set():
            await asyncio.sleep(0.005)
        return info

    monkeypatch.setattr(media, "normalize_video", normalize)
    config = settings(tmp_path, max_storage_mb=2, max_normalized_mb=1, max_upload_mb=2,
                      workers=1, timeout=5)
    with TestClient(create_app(config)) as client:
        first = submit(client, b"a" * (128 * 1024))
        assert entered.wait(1)
        rejected = client.post("/api/v1/analyze", files={"file": ("large.avi", b"b" * (1024 * 1024))}, headers=HEADERS)
        assert rejected.status_code == 503
        # 512 KiB already written is part of the 1 MiB reservation, not added twice.
        second = submit(client, b"c" * (512 * 1024), "small.webm")
        release.set()
        assert wait(client, first)["status"] == "done"
        assert wait(client, second)["status"] == "done"
        assert limits[0] == 1024 * 1024
        # The first completed MP4 is now retained, so it consumes archive quota.
        assert 512 * 1024 <= limits[1] < 1024 * 1024
        assert not client.app.state.normalization_reservations
        no_inputs(config)


def test_upload_checks_actual_free_disk_space(tmp_path, monkeypatch):
    install_pipeline(monkeypatch)
    monkeypatch.setattr(main.shutil, "disk_usage", lambda path: SimpleNamespace(free=32))
    config = settings(tmp_path)
    with TestClient(create_app(config)) as client:
        response = client.post("/api/v1/analyze", files={"file": ("clip.mp4", b"x" * 64)}, headers=HEADERS)
        assert response.status_code == 503
        no_inputs(config)


def test_disk_write_error_during_upload_is_safe_and_cleans_source(tmp_path, monkeypatch):
    original_open = Path.open
    def fail_upload(path, *args, **kwargs):
        if path.suffix == ".upload":
            raise OSError("private disk details")
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", fail_upload)
    config = settings(tmp_path)
    with TestClient(create_app(config)) as client:
        response = client.post("/api/v1/analyze", files={"file": ("clip.mov", b"source")}, headers=HEADERS)
        assert response.status_code == 503
        assert "private disk details" not in response.text
        assert "хранилища" in response.json()["detail"]
        no_inputs(config)


def test_conversion_reservation_is_reduced_to_available_disk(tmp_path, monkeypatch):
    install_pipeline(monkeypatch)
    monkeypatch.setattr(main.shutil, "disk_usage", lambda path: SimpleNamespace(free=256 * 1024))
    limits = []
    async def normalize(source, output, info, *, timeout, max_bytes):
        limits.append(max_bytes)
        output.write_bytes(b"normalized")
        return info
    monkeypatch.setattr(media, "normalize_video", normalize)
    config = settings(tmp_path, max_normalized_mb=1)
    with TestClient(create_app(config)) as client:
        assert wait(client, submit(client))["status"] == "done"
        assert len(limits) == 1 and 0 < limits[0] < 256 * 1024
        no_inputs(config)


def test_disk_full_before_conversion_fails_without_starting_converter(tmp_path, monkeypatch):
    install_pipeline(monkeypatch)
    async def inspect(path, **kwargs):
        monkeypatch.setattr(main.shutil, "disk_usage", lambda path: SimpleNamespace(free=0))
        return SimpleNamespace(duration_sec=2.0, start_time=0.0)
    async def normalize(*args, **kwargs):
        pytest.fail("A converter was started with no disk reservation")
    monkeypatch.setattr(media, "inspect_video", inspect)
    monkeypatch.setattr(media, "normalize_video", normalize)
    config = settings(tmp_path)
    with TestClient(create_app(config)) as client:
        result = wait(client, submit(client))
        assert result["error_code"] == "STORAGE_FULL"
        assert result["verdict"] is None
        no_inputs(config)


def test_conversion_failure_has_no_verdict_and_removes_both_inputs(tmp_path, monkeypatch):
    install_pipeline(monkeypatch)
    async def broken(source, output, info, **kwargs):
        output.write_bytes(b"partial")
        raise media.PipelineError("NORMALIZATION_FAILED", "Не удалось преобразовать видео.")
    monkeypatch.setattr(media, "normalize_video", broken)
    config = settings(tmp_path)
    with TestClient(create_app(config)) as client:
        result = wait(client, submit(client))
        assert result["error_code"] == "NORMALIZATION_FAILED"
        assert result["verdict"] is None and result["violations"] == []
        assert not client.app.state.normalization_reservations
        no_inputs(config)


def test_shutdown_and_restart_remove_normalized_orphans_preserve_job(tmp_path, monkeypatch):
    install_pipeline(monkeypatch)
    entered = threading.Event()
    cancelled = []
    async def waiting(source, output, info, **kwargs):
        output.write_bytes(b"partial")
        entered.set()
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.append(True)
    monkeypatch.setattr(media, "normalize_video", waiting)
    config = settings(tmp_path)
    with TestClient(create_app(config)) as client:
        job_id = submit(client)
        assert entered.wait(1)
    assert cancelled
    no_inputs(config)
    (config.storage / "orphan.upload").write_bytes(b"raw")
    (config.storage / "orphan.normalized.mp4").write_bytes(b"partial")
    with TestClient(create_app(config)) as restarted:
        result = restarted.get(f"/api/v1/jobs/{job_id}", headers=HEADERS).json()
        assert result["error_code"] == "SERVER_RESTARTED"
        assert result["verdict"] is None
        no_inputs(config)


def test_periodic_cleanup_covers_normalized_orphan(tmp_path):
    config = settings(tmp_path, retention_hours=0.00001, cleanup_interval=0.02)
    with TestClient(create_app(config)):
        orphan = config.storage / "orphan.normalized.mp4"
        orphan.write_bytes(b"stale")
        time.sleep(0.15)
        assert not orphan.exists()


@pytest.mark.parametrize("name", ["normalization_workers", "max_normalized_mb"])
def test_normalization_settings_must_be_positive(tmp_path, name):
    with pytest.raises(RuntimeError, match="positive"):
        with TestClient(create_app(settings(tmp_path, **{name: 0}))):
            pass
