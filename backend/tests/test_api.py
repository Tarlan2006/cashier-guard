import base64
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from app.models import AnalysisResult, EvidenceFrame
from app import media, pipeline

KEY = "test-private-key"
HEADERS = {"X-API-Key": KEY}


@pytest.fixture
def client(tmp_path, monkeypatch):
    async def fake_probe(path, **kwargs):
        if path.read_bytes() == b"broken":
            raise ValueError("Повреждённое видео")
        return SimpleNamespace(duration_sec=20.0, start_time=0.0)

    async def normalize(source, output, info, **kwargs):
        output.write_bytes(b"normalized mp4")
        return info

    async def fake_analyze(path, duration, settings, scenario, on_stage):
        on_stage("analyzing")
        return AnalysisResult(verdict="no_violation", violations=[])

    monkeypatch.setattr(media, "inspect_video", fake_probe)
    monkeypatch.setattr(media, "normalize_video", normalize)
    monkeypatch.setattr(pipeline, "analyze", fake_analyze)
    config = Settings(api_key=KEY, storage=tmp_path / "uploads", max_upload_mb=1)
    with TestClient(create_app(config)) as test_client:
        yield test_client, config


def wait_for_job(client, job_id):
    for _ in range(100):
        response = client.get(f"/api/v1/jobs/{job_id}", headers=HEADERS)
        if response.json()["status"] != "processing":
            return response.json()
        time.sleep(0.01)
    pytest.fail("Job did not finish")


def test_requires_key_for_upload_and_polling(client):
    api, _ = client
    for headers in [{}, {"X-API-Key": "wrong"}]:
        assert api.post("/api/v1/analyze", files={"file": ("video.mov", b"x")}, headers=headers).status_code == 401
        assert api.get("/api/v1/jobs/unknown", headers=headers).status_code == 401


def test_upload_process_poll_and_delete_original(client):
    api, config = client
    response = api.post("/api/v1/analyze", files={"file": ("../../video.mov", b"video")}, headers=HEADERS)
    assert response.status_code == 202
    result = wait_for_job(api, response.json()["job_id"])
    assert result["status"] == "done"
    assert result["verdict"] == "no_violation"
    assert result["violations"] == []
    assert result["filename"] == "video.mov"
    assert not list(config.storage.glob("*.upload"))
    assert not list(config.storage.glob("*.normalized.mp4"))


@pytest.mark.parametrize("extension", ["mov", "MP4", "avi", "mkv", "WEBM"])
def test_supported_containers_reach_normalized_pipeline(client, monkeypatch, extension):
    api, config = client
    paths = []
    async def analyze(path, duration, settings, scenario, on_stage):
        assert path.name.endswith(".normalized.mp4")
        assert path.read_bytes() == b"normalized mp4"
        paths.append(path)
        return AnalysisResult(verdict="no_violation", violations=[])
    monkeypatch.setattr(pipeline, "analyze", analyze)
    response = api.post("/api/v1/analyze", files={"file": (f"clip.{extension}", b"video")}, headers=HEADERS)
    assert response.status_code == 202
    result = wait_for_job(api, response.json()["job_id"])
    assert result["status"] == "done" and paths
    assert not list(config.storage.glob("*.upload"))
    assert not list(config.storage.glob("*.normalized.mp4"))


@pytest.mark.parametrize("filename,content,status", [("clip.txt", b"x", 415), ("clip.mov", b"", 400), ("clip.mov", b"x" * (1024 * 1024 + 1), 413)], ids=["unsupported", "empty", "oversized"])
def test_invalid_uploads_leave_no_files(client, filename, content, status):
    api, config = client
    response = api.post("/api/v1/analyze", files={"file": (filename, content)}, headers=HEADERS)
    assert response.status_code == status
    assert not list(config.storage.glob("*.upload"))


def test_corrupt_video_has_failed_status_and_no_verdict(client):
    api, _ = client
    response = api.post("/api/v1/analyze", files={"file": ("broken.mov", b"broken")}, headers=HEADERS)
    result = wait_for_job(api, response.json()["job_id"])
    assert result["status"] == "failed"
    assert result["verdict"] is None
    assert result["error"]


def test_missing_job_and_health(client):
    api, _ = client
    assert api.get("/api/v1/jobs/unknown", headers=HEADERS).status_code == 404
    assert api.get("/api/v1/health").json()["mode"] == "demo"


def test_bad_scenario_is_rejected(client):
    api, _ = client
    assert api.post("/api/v1/analyze", files={"file": ("clip.mov", b"x")}, data={"demo_scenario": "unknown"}, headers=HEADERS).status_code == 422


def test_timeout_fails_job_and_cleans_upload(client, monkeypatch):
    api, config = client
    async def timeout(*args, **kwargs):
        raise TimeoutError
    monkeypatch.setattr(pipeline, "analyze", timeout)
    response = api.post("/api/v1/analyze", files={"file": ("clip.mov", b"x")}, headers=HEADERS)
    result = wait_for_job(api, response.json()["job_id"])
    assert result["status"] == "failed"
    assert "время" in result["error"]
    assert not list(config.storage.glob("*.upload"))


def test_contract_rejects_false_no_violation_and_non_jpeg():
    with pytest.raises(ValidationError):
        AnalysisResult(verdict="violation", violations=[])
    with pytest.raises(ValidationError):
        EvidenceFrame(timestamp_sec=0, image_base64=base64.b64encode(b"not an image").decode())


def test_default_or_missing_key_is_not_allowed(tmp_path):
    for key in ["", "replace-with-your-own-key"]:
        with pytest.raises(RuntimeError, match="API_KEY"):
            with TestClient(create_app(Settings(api_key=key, storage=tmp_path))):
                pass
