import asyncio
import base64
import json
from io import BytesIO

import httpx
import pytest
from PIL import Image

from app.config import Settings
from app import pipeline
from app.pipeline import PipelineError, analyze, load_rules
from app.models import EvidenceFrame, Observations, Rule
from pydantic import ValidationError


def image_bytes(format="JPEG"):
    output = BytesIO()
    Image.new("RGB", (32, 24), color=(50, 120, 160)).save(output, format=format)
    return output.getvalue()


FRAME = {"timestamp_sec": 2.0, "image_base64": base64.b64encode(image_bytes()).decode()}
RULE = {"id": "test-rule", "title": "Fixture only", "visual_signs": ["fixture"], "document": "Test document", "section": "test", "url": "https://example.test/rule", "is_demo": False}
OBSERVATION = {"id": "event-1", "start_sec": 1, "end_sec": 3, "description": "Test observation", "evidence_frames": [FRAME]}
ML1 = {"schema_version": "1.0", "events": [OBSERVATION]}
VIOLATION = {"type": "Fixture event", "timecode_sec": 2, "description": "Fixture explanation", "evidence_frames": [FRAME], "rule_id": "test-rule"}
ML2 = {"verdict": "violation", "violations": [VIOLATION]}


def live_settings(tmp_path):
    video = tmp_path / "test.upload"
    video.write_bytes(b"fixture")
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"rules": [RULE]}))
    return video, Settings(api_key="test", mode="live", rules_path=rules)


def install_transport(monkeypatch, respond):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))


@pytest.mark.parametrize("rule_id,timestamp,error_code", [
    ("test-rule", 2.12345, None), ("invented-rule", 2, "ML2_UNKNOWN_RULE"),
    ("test-rule", 10, "ML2_INVALID_TIMECODE"), ("test-rule", 99, "ML2_INVALID_TIMECODE"),
])
def test_live_adapter_validates_and_uses_trusted_catalog(tmp_path, monkeypatch, rule_id, timestamp, error_code):
    video, settings = live_settings(tmp_path)
    seen = []

    def respond(request):
        seen.append(request.url.path)
        if request.url.path == "/analyze":
            assert b'name="file"' in request.read()
            return httpx.Response(200, json=ML1)
        payload = json.loads(request.read())
        assert payload["rules"] == [RULE]
        assert payload["events"][0]["id"] == "event-1"
        assert "file" not in payload and "video" not in payload
        return httpx.Response(200, json={"verdict": "violation", "violations": [{**VIOLATION, "rule_id": rule_id, "timecode_sec": timestamp}]})

    install_transport(monkeypatch, respond)
    stages, timings = [], {}
    if error_code:
        with pytest.raises(PipelineError) as error:
            asyncio.run(analyze(video, 10, settings, "no_violation", stages.append))
        assert error.value.code == error_code
    else:
        result = asyncio.run(analyze(video, 10, settings, "no_violation", stages.append, on_timing=timings.__setitem__))
        assert result.verdict == "violation"  # Demo selection cannot change live inference.
        assert result.violations[0].rule.model_dump() == RULE
        assert result.violations[0].timecode_sec == timestamp
        assert seen == ["/analyze", "/match"]
        assert stages == ["analyzing", "matching"]
        assert set(timings) == {"analyzing", "matching"}
        assert all(value >= 0 for value in timings.values())


@pytest.mark.parametrize("payload", [{}, {"events": []}, {"schema_version": "1.0"}, {"schema_version": "2.0", "events": []}, None, []])
def test_ml1_requires_explicit_version_and_events(payload):
    with pytest.raises(ValidationError):
        Observations.model_validate(payload)


def test_explicit_empty_ml1_is_valid_and_still_goes_to_ml2(tmp_path, monkeypatch):
    video, settings = live_settings(tmp_path)
    seen = []
    def respond(request):
        seen.append(request.url.path)
        return httpx.Response(200, json={"schema_version": "1.0", "events": []} if request.url.path == "/analyze" else {"verdict": "no_violation", "violations": []})
    install_transport(monkeypatch, respond)
    result = asyncio.run(analyze(video, 10, settings, "violation", lambda _: None))
    assert result.verdict == "no_violation"
    assert seen == ["/analyze", "/match"]


@pytest.mark.parametrize("bad_response,expected_code", [
    (httpx.Response(200, content=b""), "ML1_INVALID_RESPONSE"),
    (httpx.Response(200, content=b"   "), "ML1_INVALID_RESPONSE"),
    (httpx.Response(200, json={}), "ML1_INVALID_RESPONSE"),
    (httpx.Response(200, json={"events": []}), "ML1_INVALID_RESPONSE"),
    (httpx.Response(503, text="secret internal stack trace"), "ML1_HTTP_ERROR"),
    (httpx.Response(200, headers={"Content-Length": "999999999"}, json=ML1), "ML1_INVALID_RESPONSE"),
])
def test_invalid_ml1_never_becomes_clean_verdict(tmp_path, monkeypatch, bad_response, expected_code):
    video, settings = live_settings(tmp_path)
    seen = []
    def respond(request):
        seen.append(request.url.path)
        return bad_response
    install_transport(monkeypatch, respond)
    with pytest.raises(PipelineError) as error:
        asyncio.run(analyze(video, 10, settings, "no_violation", lambda _: None))
    assert error.value.code == expected_code
    assert "secret internal" not in error.value.message
    assert seen == ["/analyze"]


@pytest.mark.parametrize("exception,code", [(httpx.ConnectError("secret host"), "ML1_UNAVAILABLE"), (httpx.ReadTimeout("secret host"), "ML1_TIMEOUT")])
def test_network_errors_are_failures(tmp_path, monkeypatch, exception, code):
    video, settings = live_settings(tmp_path)
    def respond(_):
        raise exception
    install_transport(monkeypatch, respond)
    with pytest.raises(PipelineError) as error:
        asyncio.run(analyze(video, 10, settings, "no_violation", lambda _: None))
    assert error.value.code == code
    assert "secret host" not in str(error.value)


@pytest.mark.parametrize("raw", [b"\xff\xd8\xff\xe0fixture\xff\xd9", image_bytes("PNG"), image_bytes()[:-20], b"garbage"])
def test_rejects_fake_png_and_truncated_jpeg(raw):
    with pytest.raises(ValidationError):
        EvidenceFrame(timestamp_sec=0, image_base64=base64.b64encode(raw).decode())


def test_jpeg_is_actually_decoded_and_pixel_limit_enforced(monkeypatch):
    assert EvidenceFrame(**FRAME)
    monkeypatch.setattr("app.models.MAX_EVIDENCE_PIXELS", 100)
    with pytest.raises(ValidationError):
        EvidenceFrame(**FRAME)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1])
def test_nonfinite_and_negative_timestamps_rejected(value):
    with pytest.raises(ValidationError):
        EvidenceFrame(**{**FRAME, "timestamp_sec": value})
    with pytest.raises(ValidationError):
        Observations.model_validate({"schema_version": "1.0", "events": [{**OBSERVATION, "start_sec": value}]})


@pytest.mark.parametrize("changes", [{"start_sec": 10, "end_sec": 10}, {"end_sec": 10.01}, {"evidence_frames": [{**FRAME, "timestamp_sec": 10}]}])
def test_ml1_times_must_be_inside_video(changes):
    with pytest.raises(PipelineError, match="таймкод"):
        pipeline._validate_observations({"schema_version": "1.0", "events": [{**OBSERVATION, **changes}]}, 10)


@pytest.mark.parametrize("url", ["", "javascript:alert(1)", "file:///tmp/rule", "/relative", "https://", "https://user:password@example.test", "https://example.test/path with spaces"])
def test_rule_url_validation(url):
    with pytest.raises(ValidationError):
        Rule.model_validate({**RULE, "url": url})


@pytest.mark.parametrize("rules,code", [([], "RULES_EMPTY"), ([RULE, RULE], "RULES_INVALID"), ([{**RULE, "title": "  "}], "RULES_INVALID"), ([{**RULE, "is_demo": True}], "RULES_INVALID")])
def test_catalog_rejects_empty_duplicate_blank_or_demo_rules(tmp_path, rules, code):
    path = tmp_path / "rules.json"
    path.write_text(json.dumps({"rules": rules}))
    with pytest.raises(PipelineError) as error:
        load_rules(path)
    assert error.value.code == code


def test_ml2_source_must_match_trusted_catalog():
    rules = [Rule.model_validate(RULE)]
    with pytest.raises(PipelineError) as error:
        pipeline._validate_result({"verdict": "violation", "violations": [{**VIOLATION, "rule": {**RULE, "url": "https://example.test/invented"}}]}, 10, rules)
    assert error.value.code == "ML2_RULE_MISMATCH"
    with pytest.raises(PipelineError) as error:
        pipeline._validate_result({"verdict": "violation", "violations": [{**VIOLATION, "evidence_frames": [{**FRAME, "timestamp_sec": 10}]}]}, 10, rules)
    assert error.value.code == "ML2_INVALID_TIMECODE"


@pytest.mark.parametrize("scenario,count,frames", [("no_violation", 0, 0), ("violation", 1, 1), ("multiple_events", 3, 1), ("three_frames", 1, 3), ("long_text", 1, 1), ("demo_rule", 1, 1), ("slow", 1, 1)])
def test_demo_scenarios_use_uploaded_frames(tmp_path, monkeypatch, scenario, count, frames):
    captured, delays = [], []
    async def sleep(seconds):
        delays.append(seconds)
    async def fake_frame(path, timestamp):
        captured.append((path, timestamp))
        return EvidenceFrame(**{**FRAME, "timestamp_sec": timestamp})
    monkeypatch.setattr(pipeline.asyncio, "sleep", sleep)
    monkeypatch.setattr(pipeline, "frame_at", fake_frame)
    path = tmp_path / "synthetic.mov"
    result = asyncio.run(analyze(path, 12.345, Settings(api_key="test", mode="demo"), scenario, lambda _: None))
    assert len(result.violations) == count
    for violation in result.violations:
        assert len(violation.evidence_frames) == frames
        assert 0 <= violation.timecode_sec < 12.345
        assert "заглушкой" in violation.description
    assert all(item[0] == path for item in captured)
    if scenario == "slow":
        assert delays[0] == 12
    if scenario == "demo_rule":
        assert result.violations[0].rule.is_demo is True
        assert result.violations[0].rule.id.startswith("demo:")
        assert ".invalid/" in result.violations[0].rule.url
    if scenario == "long_text":
        assert len(result.violations[0].description) > 1_000


@pytest.mark.parametrize("scenario,code", [("ml_error", "ML1_UNAVAILABLE"), ("invalid_ml_response", "ML1_INVALID_RESPONSE")])
def test_demo_errors_fail_instead_of_returning_verdict(tmp_path, monkeypatch, scenario, code):
    async def sleep(_):
        pass
    monkeypatch.setattr(pipeline.asyncio, "sleep", sleep)
    with pytest.raises(PipelineError) as error:
        asyncio.run(analyze(tmp_path / "synthetic.mov", 10, Settings(api_key="test", mode="demo"), scenario, lambda _: None))
    assert error.value.code == code


def test_streamed_ml_response_size_is_bounded(tmp_path, monkeypatch):
    video, settings = live_settings(tmp_path)
    monkeypatch.setattr(pipeline, "MAX_ML_RESPONSE_BYTES", 100)
    install_transport(monkeypatch, lambda _: httpx.Response(200, content=b" " * 101, headers={"Content-Length": "1"}))
    with pytest.raises(PipelineError) as error:
        asyncio.run(analyze(video, 10, settings, "violation", lambda _: None))
    assert error.value.code == "ML1_INVALID_RESPONSE"


def test_total_ml_request_timeout_stops_slow_peer(tmp_path, monkeypatch):
    video, settings = live_settings(tmp_path)
    monkeypatch.setattr(pipeline, "ML_REQUEST_TIMEOUT_SECONDS", 0.01)
    async def respond(_):
        await asyncio.sleep(1)
        return httpx.Response(200, json=ML1)
    install_transport(monkeypatch, respond)
    with pytest.raises(PipelineError) as error:
        asyncio.run(analyze(video, 10, settings, "no_violation", lambda _: None))
    assert error.value.code == "ML1_TIMEOUT"


def test_synthetic_video_produces_three_decodable_evidence_frames(tmp_path, monkeypatch):
    import shutil
    import subprocess
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and FFprobe are needed for the real video integration check")
    path = tmp_path / "synthetic.mov"
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=96x64:rate=10",
        "-t", "1.3", "-c:v", "mpeg4", "-pix_fmt", "yuv420p", str(path),
    ], check=True, capture_output=True, timeout=10)
    async def sleep(_):
        pass
    monkeypatch.setattr(pipeline.asyncio, "sleep", sleep)
    async def run():
        duration = await pipeline.probe(path)
        result = await analyze(path, duration, Settings(api_key="test", mode="demo"), "three_frames", lambda _: None)
        return duration, result
    duration, result = asyncio.run(run())
    assert duration == pytest.approx(1.3)
    assert len(result.violations[0].evidence_frames) == 3
    for frame in result.violations[0].evidence_frames:
        assert 0 <= frame.timestamp_sec < duration
        with Image.open(BytesIO(base64.b64decode(frame.image_base64))) as image:
            image.load()
            assert image.format == "JPEG" and image.size == (96, 64)
