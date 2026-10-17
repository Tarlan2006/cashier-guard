import asyncio
import json
import time

from app.config import Settings
from app.middleware import UploadBudgetMiddleware


def run_rejected(messages, *, delay=0, upload_timeout=0.04):
    async def execute():
        sent, read = [], []
        async def forbidden_app(*args):
            raise AssertionError("Unauthorized bytes must never reach the multipart parser or pipeline")
        async def receive():
            # Proxy must have received the real status before any body is discarded.
            assert sent[0]["status"] == 401
            await asyncio.sleep(delay)
            message = messages[len(read)]
            read.append(message)
            return message
        async def send(message):
            sent.append(message)
        config = Settings(api_key="test-key", max_upload_mb=1, upload_timeout=upload_timeout)
        middleware = UploadBudgetMiddleware(forbidden_app, config)
        started = time.monotonic()
        await middleware({"type": "http", "path": "/api/v1/analyze", "method": "POST", "headers": [(b"x-api-key", b"wrong")]}, receive, send)
        assert sent[0]["status"] == 401
        assert json.loads(sent[-1]["body"])["error_code"] == "UNAUTHORIZED"
        return read, time.monotonic() - started
    return asyncio.run(execute())


def test_auth_discard_streams_no_parser_and_preserves_status_first():
    messages = [{"type": "http.request", "body": b"not multipart", "more_body": True}, {"type": "http.request", "body": b"rest", "more_body": False}]
    read, _ = run_rejected(messages)
    assert read == messages


def test_auth_discard_stops_at_raw_size_limit():
    read, _ = run_rejected([{"type": "http.request", "body": b"x" * (1024 * 1024 + 65536), "more_body": True}])
    assert len(read) == 1


def test_auth_discard_has_short_deadline():
    read, elapsed = run_rejected([], delay=0.2)
    assert read == []
    assert 0.03 <= elapsed < 0.15


def test_auth_discard_handles_disconnect():
    read, _ = run_rejected([{"type": "http.disconnect"}])
    assert read == [{"type": "http.disconnect"}]
