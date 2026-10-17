"""Real synthetic uploads through preparation and a local HTTP transport stub.

The stub checks ML1's actual input bytes. It is not a trained model.
"""
import base64
import json
import shutil
import subprocess
import time
from email import policy
from email.parser import BytesParser
from io import BytesIO

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app

KEY = "synthetic-video-flow-test-key"
HEADERS = {"X-API-Key": KEY}
pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="Real FFmpeg/FFprobe are required for video flow checks",
)


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, timeout=30).stdout


def info(path):
    return json.loads(run("ffprobe", "-v", "error", "-protocol_whitelist", "file",
                          "-show_format", "-show_streams", "-of", "json", str(path)))


@pytest.fixture(scope="module")
def videos(tmp_path_factory):
    directory = tmp_path_factory.mktemp("five-synthetic-containers")
    codecs = {
        "mov": ["-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac"],
        "mp4": ["-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac"],
        "avi": ["-c:v", "mpeg4", "-c:a", "pcm_s16le"],
        "mkv": ["-c:v", "ffv1", "-c:a", "pcm_s16le"],
        "webm": ["-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8", "-c:a", "libopus"],
    }
    paths = {}
    for extension, codec in codecs.items():
        path = directory / f"synthetic.{extension}"
        run("ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x96:rate=10",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "1.2",
            *codec, "-pix_fmt", "yuv420p", "-y", str(path))
        paths[extension] = path
    return paths


def wait_for_terminal(client, job_id):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/jobs/{job_id}", headers=HEADERS)
        assert response.status_code == 200
        job = response.json()
        if job["status"] != "processing":
            return job
        time.sleep(0.02)
    pytest.fail("Isolated synthetic upload did not finish")


def assert_no_videos(storage):
    assert not list(storage.glob("*.upload"))
    assert not list(storage.glob("*.normalized.mp4"))


@pytest.mark.parametrize("extension", ["mov", "mp4", "avi", "mkv", "webm"])
def test_actual_upload_reaches_ml1_as_normalized_mp4(videos, tmp_path, monkeypatch, extension):
    source = videos[extension]
    source_info = info(source)
    catalogue = tmp_path / "fixture-rules.json"
    catalogue.write_text(json.dumps({"rules": [{
        "id": "synthetic-test-only", "title": "Synthetic test fixture",
        "visual_signs": ["synthetic"], "document": "Test fixture, not a regulation",
        "section": "test", "url": "https://example.test/synthetic-fixture",
    }]}))
    settings = Settings(api_key=KEY, mode="live", storage=tmp_path / "storage",
                        rules_path=catalogue, max_storage_mb=64, timeout=30)
    seen = []

    def respond(request):
        seen.append(request.url.path)
        if request.url.path == "/analyze":
            body = request.read()
            message = BytesParser(policy=policy.default).parsebytes(
                b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + body,
            )
            parts = list(message.iter_parts())
            assert len(parts) == 1
            part = parts[0]
            assert part.get_param("name", header="content-disposition") == "file"
            assert part.get_filename() == "video.mp4"
            assert part.get_content_type() == "video/mp4"
            received = part.get_payload(decode=True)
            assert received != source.read_bytes()  # Audio was present in every input.
            normalized = list(settings.storage.glob("*.normalized.mp4"))
            assert len(normalized) == 1 and normalized[0].read_bytes() == received
            capture = tmp_path / "stub-received.mp4"
            capture.write_bytes(received)
            output = info(capture)
            assert "mp4" in output["format"]["format_name"].split(",")
            assert len(output["streams"]) == 1
            video = output["streams"][0]
            assert video["codec_type"] == "video"
            assert video["codec_name"] == "h264"
            assert video["pix_fmt"] == "yuv420p"
            assert (video["width"], video["height"]) == (160, 96)
            assert float(output["format"]["duration"]) == pytest.approx(
                float(source_info["format"]["duration"]), abs=0.12,
            )
            return httpx.Response(200, json={"schema_version": "1.0", "events": []})
        assert request.url.path == "/match"
        payload = json.loads(request.read())
        assert payload["schema_version"] == "1.0" and payload["events"] == []
        assert "file" not in payload and "video" not in payload
        return httpx.Response(200, json={"verdict": "no_violation", "violations": []})

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/v1/analyze", files={"file": (source.name, source.read_bytes(), "application/octet-stream")}, headers=HEADERS)
        assert response.status_code == 202
        job = wait_for_terminal(client, response.json()["job_id"])
        assert job["status"] == "done", job
        assert job["verdict"] == "no_violation"
        assert job["filename"] == source.name
        assert seen == ["/analyze", "/match"]
        assert job["timings_sec"]["preparing"] > 0
        assert_no_videos(settings.storage)


def test_mkv_demo_extracts_three_real_jpegs_after_normalization(videos, tmp_path):
    settings = Settings(api_key=KEY, mode="demo", storage=tmp_path / "storage", timeout=30)
    source = videos["mkv"]
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/v1/analyze", files={"file": (source.name, source.read_bytes())},
                               data={"demo_scenario": "three_frames"}, headers=HEADERS)
        job = wait_for_terminal(client, response.json()["job_id"])
        assert job["status"] == "done", job
        frames = job["violations"][0]["evidence_frames"]
        assert len(frames) == 3
        for frame in frames:
            with Image.open(BytesIO(base64.b64decode(frame["image_base64"]))) as image:
                image.load()
                assert image.format == "JPEG"
            assert 0 <= frame["timestamp_sec"] < job["duration_sec"]
        assert_no_videos(settings.storage)


@pytest.mark.parametrize("kind", ["corrupt", "audio-only", "over-duration"])
def test_real_bad_uploads_fail_without_a_verdict_or_leftover_files(tmp_path, kind):
    source = tmp_path / "synthetic.mp4"
    if kind == "corrupt":
        source.write_bytes(b"not an MP4 even though its suffix says so")
    elif kind == "audio-only":
        run("ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440",
            "-t", "0.4", "-vn", "-c:a", "aac", "-y", str(source))
    else:
        run("ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=size=16x16:rate=1",
            "-t", "601", "-an", "-c:v", "libx264", "-preset", "ultrafast", "-y", str(source))
    settings = Settings(api_key=KEY, mode="demo", storage=tmp_path / "storage", timeout=30)
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/v1/analyze", files={"file": (source.name, source.read_bytes())}, headers=HEADERS)
        assert response.status_code == 202
        job = wait_for_terminal(client, response.json()["job_id"])
        assert job["status"] == "failed", job
        assert job["verdict"] is None and job["violations"] == []
        assert job["error"] and job["error_code"]
        assert_no_videos(settings.storage)
