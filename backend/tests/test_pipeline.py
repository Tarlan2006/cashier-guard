import asyncio
import base64
import json

import httpx
import pytest

from app.config import Settings
from app.pipeline import analyze

FRAME = {"timestamp_sec": 2.0, "image_base64": base64.b64encode(b"\xff\xd8\xff\xe0fixture\xff\xd9").decode()}
RULE = {"id": "test-rule", "title": "Fixture only", "visual_signs": ["fixture"], "document": "Test document", "section": "test", "url": "https://example.test/rule"}


@pytest.mark.parametrize("rule_id,timestamp,expected_error", [
    ("test-rule", 2, None), ("invented-rule", 2, "правила"), ("test-rule", 99, "таймкод"),
])
def test_live_adapter_validates_and_uses_trusted_catalog(tmp_path, monkeypatch, rule_id, timestamp, expected_error):
    video = tmp_path / "test.upload"
    video.write_bytes(b"fixture")
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"rules": [RULE]}))
    seen = []

    def respond(request):
        seen.append(request.url.path)
        if request.url.path == "/analyze":
            assert b'name="file"' in request.read()
            return httpx.Response(200, json={"schema_version": "1.0", "events": [{
                "id": "event-1", "start_sec": 1, "end_sec": 3,
                "description": "Test observation", "evidence_frames": [FRAME],
            }]})
        payload = json.loads(request.read())
        assert payload["rules"] == [RULE]
        assert payload["events"][0]["id"] == "event-1"
        return httpx.Response(200, json={"verdict": "violation", "violations": [{
            "type": "Fixture event", "timecode_sec": timestamp, "description": "Fixture explanation",
            "evidence_frames": [FRAME], "rule_id": rule_id,
        }]})

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    stages = []
    settings = Settings(api_key="test", mode="live", rules_path=rules)
    if expected_error:
        with pytest.raises(ValueError, match=expected_error):
            asyncio.run(analyze(video, 10, settings, "no_violation", stages.append))
    else:
        result = asyncio.run(analyze(video, 10, settings, "no_violation", stages.append))
        assert result.verdict == "violation"  # Demo scenario cannot override live inference.
        assert result.violations[0].rule.model_dump() == RULE
        assert seen == ["/analyze", "/match"]
        assert stages == ["analyzing", "matching"]


def test_live_does_not_run_with_empty_catalog(tmp_path):
    rules = tmp_path / "rules.json"
    rules.write_text('{"rules": []}')
    with pytest.raises(ValueError, match="Каталог правил пуст"):
        asyncio.run(analyze(tmp_path / "video", 10, Settings(api_key="test", mode="live", rules_path=rules), "violation", lambda _: None))
