"""Evidence levels are ML2 data, never client-side confidence thresholds."""
import asyncio
import base64
import json
import time
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace

import pytest
import httpx
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from app import media, pipeline
from app.config import Settings
from app.main import create_app
from app.models import AnalysisResult, EvidenceFrame, JobResponse, Rule, Violation
from app.pipeline import PipelineError
from app.store import JobStore


def jpeg():
    data = BytesIO()
    Image.new("RGB", (32, 24), "green").save(data, format="JPEG")
    return base64.b64encode(data.getvalue()).decode()


FRAME = {"timestamp_sec": 2.0, "image_base64": jpeg()}
RULE = {"id": "test:checked", "title": "Fixture only", "visual_signs": ["Fixture"],
        "document": "Test document", "section": "Fixture section", "url": "https://example.test/rule", "is_demo": False}
EVENT = {"type": "Fixture event", "timecode_sec": 2.0, "description": "Fixture description",
         "evidence_frames": [FRAME], "rule_id": RULE["id"]}
HEADERS = {"X-API-Key": "test-key"}


def job_payload(**changes):
    now = datetime.now(timezone.utc).isoformat()
    return {"job_id": "saved-job", "status": "done", "stage": "done", "mode": "live",
            "filename": "saved.mov", "created_at": now,
            "expires_at": datetime.fromtimestamp(time.time() + 3600, timezone.utc).isoformat(),
            "duration_sec": 10.0, "verdict": "violation", "violations": [{**EVENT, "rule": RULE}], **changes}


@pytest.mark.parametrize("assessment", [None, "needs_review", "strong_evidence"])
def test_assessment_round_trip_and_legacy_null(assessment):
    fields = {} if assessment is None else {"assessment": assessment, "assessment_reason": "Chosen by test ML2"}
    event = Violation.model_validate({**EVENT, **fields})
    assert event.assessment == assessment
    assert event.assessment_reason == fields.get("assessment_reason")
    restored = Violation.model_validate_json(event.model_dump_json())
    assert restored == event


@pytest.mark.parametrize("changes", [
    {"assessment": "confirmed"}, {"assessment": 90}, {"assessment": {}},
    {"assessment": "strong_evidence"}, {"assessment": "strong_evidence", "assessment_reason": None},
    {"assessment": "strong_evidence", "assessment_reason": "   "},
    {"assessment": "needs_review", "assessment_reason": ""},
])
def test_invalid_assessment_is_contract_error(changes):
    with pytest.raises(ValidationError):
        Violation.model_validate({**EVENT, **changes})
    with pytest.raises(PipelineError) as error:
        pipeline._validate_result({"verdict": "violation", "violations": [{**EVENT, **changes}]}, 10, [Rule(**RULE)])
    assert error.value.code == "ML2_INVALID_RESPONSE"


def test_strong_evidence_live_requires_checked_rule_and_decoded_frames():
    event = {**EVENT, "assessment": "strong_evidence", "assessment_reason": "Test rationale"}
    result = pipeline._validate_result({"verdict": "violation", "violations": [event]}, 10, [Rule(**RULE)])
    assert result.violations[0].rule == Rule(**RULE)
    for changes, code in [
        ({"rule_id": None}, "ML2_UNKNOWN_RULE"),
        ({"rule_id": "made-up"}, "ML2_UNKNOWN_RULE"),
        ({"rule": {**RULE, "url": "https://example.test/untrusted"}}, "ML2_RULE_MISMATCH"),
        ({"evidence_frames": []}, "ML2_INVALID_RESPONSE"),
        ({"evidence_frames": [{**FRAME, "image_base64": base64.b64encode(b"not a jpeg").decode()}]}, "ML2_INVALID_RESPONSE"),
        ({"evidence_frames": [{**FRAME, "timestamp_sec": 10}]}, "ML2_INVALID_TIMECODE"),
    ]:
        with pytest.raises(PipelineError) as error:
            pipeline._validate_result({"verdict": "violation", "violations": [{**event, **changes}]}, 10, [Rule(**RULE)])
        assert error.value.code == code


@pytest.mark.parametrize("payload", [
    {"verdict": "no_violation"}, {"verdict": "no_violation", "violations": [EVENT]},
    {"verdict": "violation", "violations": []}, {"verdict": "needs_review", "violations": [EVENT]},
    {"verdict": "no_violation", "violations": None}, {}, None,
])
def test_corrupt_ml2_result_never_becomes_green(payload):
    with pytest.raises(PipelineError) as error:
        pipeline._validate_result(payload, 10, [Rule(**RULE)])
    assert error.value.code == "ML2_INVALID_RESPONSE"


@pytest.mark.parametrize("scenario,levels", [
    ("no_violation", []), ("strong_evidence", ["strong_evidence"]),
    ("needs_review", ["needs_review"]),
    ("mixed_assessments", ["strong_evidence", "needs_review", "strong_evidence", "needs_review"]),
])
def test_demo_levels_are_explicit_and_fictional(tmp_path, monkeypatch, scenario, levels):
    async def sleep(_):
        pass
    async def frame(path, timestamp):
        return EvidenceFrame(**{**FRAME, "timestamp_sec": timestamp})
    async def inspect(path):
        return SimpleNamespace(video_start_time=0)
    monkeypatch.setattr(pipeline.asyncio, "sleep", sleep)
    monkeypatch.setattr(pipeline, "frame_at", frame)
    monkeypatch.setattr(pipeline, "inspect_video", inspect)
    result = asyncio.run(pipeline.analyze(tmp_path / "normalized.mp4", 10,
                        Settings(api_key="test", mode="demo"), scenario, lambda _: None))
    assert result.verdict == ("violation" if levels else "no_violation")
    assert [event.assessment for event in result.violations] == levels
    for event in result.violations:
        assert "ВЫМЫШЛЕННАЯ demo-оценка" in event.assessment_reason
        if event.assessment == "strong_evidence":
            assert event.rule.is_demo and event.rule.id.startswith("demo:")
            assert "не нормативный" in event.rule.document


@pytest.mark.parametrize("changes", [
    {"verdict": "no_violation"}, {"status": "processing", "stage": "matching"},
    {"status": "failed", "stage": "failed", "error_code": "TIMEOUT"},
    {"stage": "matching"}, {"error_code": "TIMEOUT"},
    {"violations": [{**EVENT, "assessment": "strong_evidence", "assessment_reason": "Test reason"}]},
    {"violations": [{**EVENT, "timecode_sec": 10}]},
])
def test_saved_job_inconsistent_state_is_invalid(changes):
    with pytest.raises(ValidationError):
        JobResponse.model_validate(job_payload(**changes))


def test_missing_completed_events_is_not_empty_success():
    payload = job_payload(verdict="no_violation")
    del payload["violations"]
    with pytest.raises(ValidationError):
        JobResponse.model_validate(payload)


@pytest.mark.parametrize("assessment", [None, "needs_review", "strong_evidence"])
def test_saved_assessments_and_legacy_survive_api_restart(tmp_path, assessment):
    settings = Settings(api_key="test-key", mode="demo", storage=tmp_path / "storage")
    settings.storage.mkdir()
    payload = job_payload()
    if assessment is not None:
        payload["violations"][0].update(assessment=assessment, assessment_reason="Test ML2 rationale")
    store = JobStore(settings.storage / "jobs.sqlite3")
    # Write legacy JSON literally, without filling the new fields first.
    store.connection.execute("INSERT INTO jobs VALUES (?, ?, ?, ?)", (
        payload["job_id"], "done", time.time() + 3600, json.dumps(payload)))
    store.connection.commit()
    store.close()
    for _ in range(2):
        with TestClient(create_app(settings)) as client:
            response = client.get("/api/v1/jobs/saved-job", headers=HEADERS)
            assert response.status_code == 200
            restored = response.json()
            assert restored["status"] == "done" and restored["verdict"] == "violation"
            assert restored["violations"][0]["assessment"] == assessment
            assert restored["violations"][0]["assessment_reason"] == ("Test ML2 rationale" if assessment else None)
            assert json.loads(json.dumps(restored))["violations"] == restored["violations"]


@pytest.mark.parametrize("kind", ["unknown", "contradiction", "truncated", "missing_events", "bad_mode", "processing"])
def test_corrupt_saved_results_return_neutral_failure_and_restart(tmp_path, kind):
    settings = Settings(api_key="test-key", mode="demo", storage=tmp_path / "storage")
    settings.storage.mkdir()
    payload = job_payload()
    status = "done"
    if kind == "unknown":
        payload["violations"][0]["assessment"] = "confident"
    elif kind == "contradiction":
        payload["verdict"] = "no_violation"
    elif kind == "missing_events":
        payload["verdict"] = "no_violation"
        del payload["violations"]
    elif kind == "bad_mode":
        payload["mode"] = []
    elif kind == "processing":
        status = payload["status"] = "processing"
        payload["stage"] = "matching"
    raw = "{" if kind == "truncated" else json.dumps(payload)
    store = JobStore(settings.storage / "jobs.sqlite3")
    store.connection.execute("INSERT INTO jobs VALUES (?, ?, ?, ?)", ("saved-job", status, time.time() + 3600, raw))
    store.connection.commit()
    store.close()
    for _ in range(2):
        with TestClient(create_app(settings)) as client:
            response = client.get("/api/v1/jobs/saved-job", headers=HEADERS)
            assert response.status_code == 200
            failed = response.json()
            assert failed["status"] == "failed" and failed["stage"] == "failed"
            assert failed["error_code"] == "RESULT_INVALID"
            assert failed["verdict"] is None and failed["violations"] == []
            assert "Проверка не завершена" in failed["error"]


@pytest.mark.parametrize("case", ["strong_evidence", "unknown", "missing_events", "timeout"])
def test_ml2_assessment_through_api_and_cleanup(tmp_path, monkeypatch, case):
    rules_path = tmp_path / "test-rules.json"
    rules_path.write_text(json.dumps({"rules": [RULE]}))
    settings = Settings(api_key="test-key", mode="live", storage=tmp_path / "storage", rules_path=rules_path,
                        timeout=0.1 if case == "timeout" else 10)

    async def inspect(path, **kwargs):
        return SimpleNamespace(duration_sec=10, start_time=0)
    async def normalize(source, output, info, **kwargs):
        output.write_bytes(b"normalized fixture")
        return info
    async def respond(request):
        if request.url.path == "/analyze":
            assert b'filename="video.mp4"' in request.read()
            return httpx.Response(200, json={"schema_version": "1.0", "events": [{
                "id": "event-1", "start_sec": 1, "end_sec": 3,
                "description": "Fixture observation", "evidence_frames": [FRAME],
            }]})
        if case == "timeout":
            await asyncio.sleep(2)
        payload = {"verdict": "no_violation"} if case == "missing_events" else {
            "verdict": "violation", "violations": [{**EVENT, "assessment": "unknown" if case == "unknown" else "strong_evidence",
                                                       "assessment_reason": "Test ML2 explanation"}]}
        return httpx.Response(200, json=payload)
    original = httpx.AsyncClient
    monkeypatch.setattr(media, "inspect_video", inspect)
    monkeypatch.setattr(media, "normalize_video", normalize)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/v1/analyze", headers=HEADERS, files={"file": ("fixture.mp4", b"test source")})
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        for _ in range(200):
            result = client.get(f"/api/v1/jobs/{job_id}", headers=HEADERS).json()
            if result["status"] != "processing":
                break
            time.sleep(0.01)
        if case == "strong_evidence":
            assert result["status"] == "done" and result["verdict"] == "violation"
            assert result["violations"][0]["assessment"] == "strong_evidence"
            assert result["violations"][0]["assessment_reason"] == "Test ML2 explanation"
            assert result["violations"][0]["rule"] == RULE
        else:
            assert result["status"] == "failed"
            assert result["verdict"] is None and result["violations"] == []
            assert result["error_code"] == ("TIMEOUT" if case == "timeout" else "ML2_INVALID_RESPONSE")
        assert not list(settings.storage.glob("*.upload"))
        assert not list(settings.storage.glob("*.normalized.mp4"))
    with TestClient(create_app(settings)) as client:
        assert client.get(f"/api/v1/jobs/{job_id}", headers=HEADERS).json() == result
