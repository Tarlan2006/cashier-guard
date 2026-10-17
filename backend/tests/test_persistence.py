import asyncio
import json
import time
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main, media, pipeline
from app.config import Settings
from app.main import create_app
from app.models import AnalysisResult, JobResponse

KEY = "test-private-key"
HEADERS = {"X-API-Key": KEY}


def config_for(tmp_path, **kwargs):
    return Settings(api_key=KEY, mode="demo", storage=tmp_path / "storage", **kwargs)


def fake_pipeline(monkeypatch, delay=0):
    async def probe(path, **kwargs):
        return SimpleNamespace(duration_sec=12.5, start_time=0.0)

    async def normalize(source, output, info, **kwargs):
        output.write_bytes(b"normalized mp4")
        return info

    async def analyze(path, duration, settings, scenario, on_stage):
        on_stage("analyzing")
        await asyncio.sleep(delay)
        on_stage("matching")
        return AnalysisResult(verdict="no_violation", violations=[])

    monkeypatch.setattr(media, "inspect_video", probe)
    monkeypatch.setattr(media, "normalize_video", normalize)
    monkeypatch.setattr(pipeline, "analyze", analyze)


def submit(client):
    response = client.post("/api/v1/analyze", files={"file": ("clip.mov", b"fake video")}, headers=HEADERS)
    assert response.status_code == 202, response.text
    return response.json()["job_id"]


def wait(client, job_id):
    for _ in range(200):
        response = client.get(f"/api/v1/jobs/{job_id}", headers=HEADERS)
        assert response.status_code == 200
        job = response.json()
        if job["status"] != "processing":
            return job
        time.sleep(0.01)
    pytest.fail("Job remained processing")


def test_done_result_survives_new_app(tmp_path, monkeypatch):
    fake_pipeline(monkeypatch)
    config = config_for(tmp_path)
    with TestClient(create_app(config)) as first:
        job_id = submit(first)
        original = wait(first, job_id)
    with TestClient(create_app(config)) as restarted:
        restored = restarted.get(f"/api/v1/jobs/{job_id}", headers=HEADERS).json()
        assert restored == original
        assert restored["status"] == "done"
        assert restored["size_bytes"] == len(b"fake video")
        assert {"upload", "queue", "preparing", "analyzing", "matching", "total"} <= restored["timings_sec"].keys()


@pytest.mark.parametrize("offset", [5.0, -0.5])
def test_source_playback_offset_survives_reload_and_allows_legacy_results(tmp_path, monkeypatch, offset):
    fake_pipeline(monkeypatch)
    async def probe(path, **kwargs):
        return SimpleNamespace(duration_sec=12.5, start_time=offset)
    monkeypatch.setattr(media, "inspect_video", probe)
    config = config_for(tmp_path)
    with TestClient(create_app(config)) as first:
        job_id = submit(first)
        original = wait(first, job_id)
        assert original["status"] == "done"
        assert original["source_time_offset_sec"] == offset
    with TestClient(create_app(config)) as restarted:
        restored = restarted.get(f"/api/v1/jobs/{job_id}", headers=HEADERS).json()
        assert restored == original
    legacy = {key: value for key, value in original.items() if key != "source_time_offset_sec"}
    assert JobResponse.model_validate(legacy).source_time_offset_sec is None
    for invalid in [float("nan"), float("inf"), float("-inf")]:
        with pytest.raises(ValueError):
            JobResponse.model_validate({**original, "source_time_offset_sec": invalid})


def test_restart_marks_unfinished_explicit_failure(tmp_path, monkeypatch):
    fake_pipeline(monkeypatch, delay=60)
    config = config_for(tmp_path)
    with TestClient(create_app(config)) as first:
        job_id = submit(first)
        assert first.get(f"/api/v1/jobs/{job_id}", headers=HEADERS).json()["status"] == "processing"
    with TestClient(create_app(config)) as restarted:
        restored = restarted.get(f"/api/v1/jobs/{job_id}", headers=HEADERS).json()
        assert restored["status"] == "failed"
        assert restored["error_code"] == "SERVER_RESTARTED"
        assert restored["verdict"] is None
        assert restored["violations"] == []
        assert not list(config.storage.glob("*.upload"))


def test_ttl_periodically_deletes_results_and_stale_uploads(tmp_path, monkeypatch):
    fake_pipeline(monkeypatch)
    config = config_for(tmp_path, retention_hours=0.00004, cleanup_interval=0.03)
    with TestClient(create_app(config)) as client:
        job_id = submit(client)
        wait(client, job_id)
        orphan = config.storage / "orphan.upload"
        orphan.write_bytes(b"stale")
        time.sleep(0.3)
        assert client.get(f"/api/v1/jobs/{job_id}", headers=HEADERS).status_code == 404
        assert not orphan.exists()
        # Query via the portal because the SQLite connection belongs to its event-loop thread.
        async def row_count():
            return client.app.state.store.count()
        assert client.portal.call(row_count) == 0


def test_total_deadline_includes_queue_and_worker_survives(tmp_path, monkeypatch):
    fake_pipeline(monkeypatch, delay=60)
    config = config_for(tmp_path, workers=1, timeout=0.16)
    with TestClient(create_app(config)) as client:
        first, second = submit(client), submit(client)
        for job_id in (first, second):
            job = wait(client, job_id)
            assert job["status"] == "failed"
            assert job["error_code"] == "TIMEOUT"
            assert job["verdict"] is None
            assert job["timings_sec"]["total"] < 0.3
            assert datetime.fromisoformat(job["deadline_at"]) > datetime.fromisoformat(job["created_at"])
        fake_pipeline(monkeypatch)
        assert wait(client, submit(client))["status"] == "done"
        assert not list(config.storage.glob("*.upload"))


def test_capacity_rejects_without_deleting_retained_result(tmp_path, monkeypatch):
    fake_pipeline(monkeypatch)
    with TestClient(create_app(config_for(tmp_path, max_jobs=1))) as client:
        job_id = submit(client)
        wait(client, job_id)
        assert client.post("/api/v1/analyze", files={"file": ("other.mov", b"video")}, headers=HEADERS).status_code == 503
        assert client.get(f"/api/v1/jobs/{job_id}", headers=HEADERS).status_code == 200


def test_storage_quota_rejects_upload_and_cleans_file(tmp_path, monkeypatch):
    fake_pipeline(monkeypatch)
    config = config_for(tmp_path, max_storage_mb=1, max_upload_mb=2)
    with TestClient(create_app(config)) as client:
        response = client.post("/api/v1/analyze", files={"file": ("clip.mov", b"x" * (1024 * 1024))}, headers=HEADERS)
        assert response.status_code == 503
        assert not list(config.storage.glob("*.upload"))


@pytest.mark.parametrize("exception,expected", [(ValueError, "INVALID_ML_RESPONSE"), (RuntimeError, "PROCESSING_FAILED")])
def test_ml_errors_have_no_verdict_or_sensitive_error_details(tmp_path, monkeypatch, caplog, exception, expected):
    fake_pipeline(monkeypatch)
    async def broken(*args, **kwargs):
        args[-1]("analyzing")
        raise exception("private-frame-or-key")
    monkeypatch.setattr(pipeline, "analyze", broken)
    with TestClient(create_app(config_for(tmp_path))) as client:
        result = wait(client, submit(client))
        assert result["status"] == "failed"
        assert result["error_code"] == expected
        assert result["verdict"] is None and result["violations"] == []
        assert "private-frame-or-key" not in json.dumps(result)
        assert "private-frame-or-key" not in caplog.text


async def asgi_request(app, messages, delays=None, headers=None):
    sent = []
    index = 0
    async def receive():
        nonlocal index
        if delays:
            await asyncio.sleep(delays[index])
        message = messages[index]
        index += 1
        return message
    async def send(message):
        sent.append(message)
    scope = {"type": "http", "asgi": {"version": "3.0"}, "method": "POST", "path": "/api/v1/analyze",
             "raw_path": b"/api/v1/analyze", "query_string": b"", "http_version": "1.1", "scheme": "http",
             "server": ("test", 80), "client": ("test", 123), "headers": headers or [(b"x-api-key", KEY.encode()), (b"content-type", b"multipart/form-data; boundary=test")]}
    await app(scope, receive, send)
    return sent[0]["status"], json.loads(b"".join(item.get("body", b"") for item in sent))


def test_body_receive_and_multipart_time_are_in_total_budget(tmp_path, monkeypatch):
    fake_pipeline(monkeypatch, delay=0.15)
    config = config_for(tmp_path, timeout=0.17, upload_timeout=0.5)
    body = b'--test\r\nContent-Disposition: form-data; name="file"; filename="clip.mov"\r\nContent-Type: video/quicktime\r\n\r\nvideo\r\n--test--\r\n'
    with TestClient(create_app(config)) as client:
        status, response = client.portal.call(asgi_request, client.app, [{"type": "http.request", "body": body, "more_body": False}], [0.09])
        assert status == 202
        job = wait(client, response["job_id"])
        assert job["error_code"] == "TIMEOUT"
        assert job["timings_sec"]["upload"] >= 0.09
        assert job["timings_sec"]["total"] < 0.26


def test_slow_chunked_multipart_rejected_before_job(tmp_path, monkeypatch):
    fake_pipeline(monkeypatch)
    config = config_for(tmp_path, upload_timeout=0.03)
    with TestClient(create_app(config)) as client:
        status, response = client.portal.call(asgi_request, client.app, [{"type": "http.request", "body": b"", "more_body": False}], [0.1])
        assert status == 408
        assert response["error_code"] == "TIMEOUT"
        assert not list(config.storage.glob("*.upload"))


def test_time_spent_in_multipart_parser_counts_toward_upload_limit(tmp_path, monkeypatch):
    from starlette.formparsers import MultiPartParser
    fake_pipeline(monkeypatch)
    original = MultiPartParser.parse
    async def slow_parse(parser):
        form = await original(parser)
        await asyncio.sleep(0.04)
        return form
    monkeypatch.setattr(MultiPartParser, "parse", slow_parse)
    config = config_for(tmp_path, upload_timeout=0.02)
    with TestClient(create_app(config)) as client:
        response = client.post("/api/v1/analyze", files={"file": ("clip.mov", b"video")}, headers=HEADERS)
        assert response.status_code == 408
        assert not list(config.storage.glob("*.upload"))


def test_concurrent_uploads_are_bounded_before_parsing(tmp_path, monkeypatch):
    fake_pipeline(monkeypatch)
    body = b'--test\r\nContent-Disposition: form-data; name="file"; filename="clip.mov"\r\n\r\nvideo\r\n--test--\r\n'
    config = config_for(tmp_path, max_concurrent_uploads=1)
    with TestClient(create_app(config)) as client:
        async def two_uploads():
            first = asyncio.create_task(asgi_request(client.app, [{"type": "http.request", "body": body, "more_body": False}], [0.05]))
            await asyncio.sleep(0.01)
            second = await asgi_request(client.app, [])
            return await first, second
        first, second = client.portal.call(two_uploads)
        assert first[0] == 202
        assert second[0] == 503
        assert second[1]["error_code"] == "UPLOAD_BUSY"


def test_partial_multipart_timeout_closes_spooled_file(tmp_path, monkeypatch):
    from starlette import formparsers
    original = formparsers.SpooledTemporaryFile
    spools = []
    def tracked_spool(*args, **kwargs):
        spool = original(*args, **kwargs)
        spools.append(spool)
        return spool
    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", tracked_spool)
    config = config_for(tmp_path, max_upload_mb=2, upload_timeout=0.04)
    head = b'--test\r\nContent-Disposition: form-data; name="file"; filename="clip.mov"\r\n\r\n'
    with TestClient(create_app(config)) as client:
        status, _ = client.portal.call(asgi_request, client.app, [
            {"type": "http.request", "body": head + b"x" * (1024 * 1024 + 1), "more_body": True},
            {"type": "http.request", "body": b"\r\n--test--\r\n", "more_body": False},
        ], [0, 0.1])
        assert status == 408
        assert spools and all(spool.closed for spool in spools)


def test_partial_multipart_disk_refusal_closes_spool_and_releases_reservation(tmp_path, monkeypatch):
    from starlette import formparsers
    original = formparsers.SpooledTemporaryFile
    spools = []
    checks = 0
    def tracked_spool(*args, **kwargs):
        spool = original(*args, **kwargs)
        spools.append(spool)
        return spool
    def disk_usage(path):
        nonlocal checks
        checks += 1
        # First chunk has space on both storage and temp filesystems; next does not.
        return SimpleNamespace(free=8 * 1024 * 1024 if checks <= 2 else 0)
    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", tracked_spool)
    monkeypatch.setattr(main.shutil, "disk_usage", disk_usage)
    config = config_for(tmp_path, max_upload_mb=2)
    head = b'--test\r\nContent-Disposition: form-data; name="file"; filename="clip.mov"\r\n\r\n'
    with TestClient(create_app(config)) as client:
        status, result = client.portal.call(asgi_request, client.app, [
            {"type": "http.request", "body": head + b"x" * (1024 * 1024 + 1), "more_body": True},
            {"type": "http.request", "body": b"\r\n--test--\r\n", "more_body": False},
        ])
        assert status == 503 and result["error_code"] == "STORAGE_FULL"
        assert spools and all(spool.closed for spool in spools)
        assert not client.app.state.upload_reservations
        assert not list(config.storage.glob("*.upload"))


def test_simultaneous_parsers_share_physical_disk_reservations(tmp_path, monkeypatch):
    fake_pipeline(monkeypatch)
    monkeypatch.setattr(main.shutil, "disk_usage", lambda path: SimpleNamespace(free=512 * 1024))
    head = b'--test\r\nContent-Disposition: form-data; name="file"; filename="clip.mov"\r\n\r\n'
    tail = b"\r\n--test--\r\n"
    config = config_for(tmp_path, max_upload_mb=1, max_concurrent_uploads=2)
    with TestClient(create_app(config)) as client:
        async def concurrent_bodies():
            first = asyncio.create_task(asgi_request(client.app, [
                {"type": "http.request", "body": head + b"a" * (150 * 1024), "more_body": True},
                {"type": "http.request", "body": tail, "more_body": False},
            ], [0, 0.08]))
            await asyncio.sleep(0.02)
            second = await asgi_request(client.app, [
                {"type": "http.request", "body": head + b"b" * (250 * 1024) + tail, "more_body": False},
            ])
            return await first, second
        first, second = client.portal.call(concurrent_bodies)
        assert first[0] == 202
        assert second[0] == 503 and second[1]["error_code"] == "STORAGE_FULL"
        assert wait(client, first[1]["job_id"])["status"] == "done"
        assert not client.app.state.upload_reservations


def test_chunked_oversized_body_and_unauthorized_never_accept(tmp_path, monkeypatch):
    fake_pipeline(monkeypatch)
    with TestClient(create_app(config_for(tmp_path, max_upload_mb=1))) as client:
        status, response = client.portal.call(asgi_request, client.app, [{"type": "http.request", "body": b"x" * (1024 * 1024 + 65537), "more_body": False}])
        assert status == 413
        assert response["error_code"] == "UPLOAD_TOO_LARGE"
        status, response = client.portal.call(asgi_request, client.app, [{"type": "http.request", "body": b"not multipart", "more_body": False}], None, [(b"x-api-key", b"wrong")])
        assert status == 401  # Authentication discards raw bytes without invoking the parser.


def test_health_is_alive_when_live_processing_not_ready(tmp_path, monkeypatch):
    config = Settings(api_key=KEY, mode="live", storage=tmp_path, rules_path=tmp_path / "missing.json", ml1_url="http://127.0.0.1:1", ml2_url="http://127.0.0.1:1")
    with TestClient(create_app(config)) as client:
        assert client.get("/api/v1/health").json()["status"] == "ok"
        response = client.get("/api/v1/ready")
        assert response.status_code == 200
        ready = response.json()
        assert ready["ready"] is False
        assert not ready["checks"]["rules"]["ready"]
        assert not ready["checks"]["ml1"]["ready"]
        assert not ready["checks"]["ml2"]["ready"]


class TerminalCommitFault:
    """Inject commit faults while exercising the real transaction and rollback."""
    def __init__(self, connection, *, permanent=False):
        self.connection = connection
        self.permanent = permanent
        self.enabled = True
        self.fail_commit = False
        self.failures = 0
        self.rollbacks = 0

    def execute(self, statement, parameters=()):
        result = self.connection.execute(statement, parameters)
        if statement.startswith("INSERT INTO jobs") and parameters[1] != "processing":
            self.fail_commit = self.enabled and (self.permanent or self.failures == 0)
        return result

    def commit(self):
        if self.fail_commit:
            import sqlite3
            self.fail_commit = False
            self.failures += 1
            raise sqlite3.OperationalError("private disk detail: cannot commit")
        return self.connection.commit()

    def rollback(self):
        self.rollbacks += 1
        self.fail_commit = False
        return self.connection.rollback()

    def close(self):
        return self.connection.close()


def install_terminal_commit_fault(client, *, permanent=False):
    async def install():
        store = client.app.state.store
        fault = TerminalCommitFault(store.connection, permanent=permanent)
        store.connection = fault
        return fault
    return client.portal.call(install)


def test_terminal_commit_failure_becomes_durable_failure_and_cleans_source(tmp_path, monkeypatch, caplog):
    fake_pipeline(monkeypatch)
    config = config_for(tmp_path)
    with TestClient(create_app(config)) as client:
        fault = install_terminal_commit_fault(client)
        job_id = submit(client)
        result = wait(client, job_id)
        assert result["status"] == "failed"
        assert result["error_code"] == "STORAGE_WRITE_FAILED"
        assert result["verdict"] is None and result["violations"] == []
        assert fault.failures == 1 and fault.rollbacks == 1
        assert not client.app.state.active and not client.app.state.unsaved_failures
        assert not list(config.storage.glob("*.upload"))
        assert "private disk detail" not in caplog.text
        assert wait(client, submit(client))["status"] == "done"
    with TestClient(create_app(config)) as restarted:
        restored = restarted.get(f"/api/v1/jobs/{job_id}", headers=HEADERS).json()
        assert restored["error_code"] == "STORAGE_WRITE_FAILED"
        assert restored["verdict"] is None


def test_permanent_terminal_commit_failure_cancels_work_and_recovers_on_cleanup(tmp_path, monkeypatch):
    fake_pipeline(monkeypatch)
    cancelled = []
    async def waiting_model(path, duration, settings, scenario, on_stage):
        on_stage("analyzing")
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.append(True)
    monkeypatch.setattr(pipeline, "analyze", waiting_model)
    config = config_for(tmp_path, timeout=0.07, workers=1, cleanup_interval=60)
    with TestClient(create_app(config)) as client:
        fault = install_terminal_commit_fault(client, permanent=True)
        job_id = submit(client)
        result = wait(client, job_id)
        assert result["status"] == "failed" and result["error_code"] == "STORAGE_WRITE_FAILED"
        assert result["verdict"] is None and result["violations"] == []
        assert fault.failures == 2 and fault.rollbacks == 2
        assert cancelled and not client.app.state.active
        assert job_id in client.app.state.unsaved_failures
        assert not list(config.storage.glob("*.upload"))
        async def stored_status():
            return client.app.state.store.get(job_id).status
        assert client.portal.call(stored_status) == "processing"
        assert client.get(f"/api/v1/jobs/{job_id}", headers=HEADERS).json()["status"] == "failed"
        assert client.post("/api/v1/analyze", files={"file": ("again.mov", b"video")}, headers=HEADERS).status_code == 503
        fault.enabled = False
        async def cleanup():
            client.app.state.cleanup()
        client.portal.call(cleanup)
        assert client.portal.call(stored_status) == "failed"
        assert not client.app.state.unsaved_failures
        fake_pipeline(monkeypatch)
        assert wait(client, submit(client))["status"] == "done"


def test_unsaved_terminal_failure_expires_without_resurrecting_processing(tmp_path, monkeypatch):
    fake_pipeline(monkeypatch)
    config = config_for(tmp_path, retention_hours=0.00002, cleanup_interval=60)
    with TestClient(create_app(config)) as client:
        fault = install_terminal_commit_fault(client, permanent=True)
        job_id = submit(client)
        assert wait(client, job_id)["error_code"] == "STORAGE_WRITE_FAILED"
        time.sleep(0.1)
        assert client.get(f"/api/v1/jobs/{job_id}", headers=HEADERS).status_code == 404
        fault.enabled = False
        async def cleanup_and_count():
            client.app.state.cleanup()
            return client.app.state.store.count()
        assert client.portal.call(cleanup_and_count) == 0
        assert not client.app.state.unsaved_failures
