import base64
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from fastapi.testclient import TestClient
import jsonschema
from backend.pipeline.perception import PerceptionConfig
from backend.schemas import Event
from service.app import create_app
from service.evidence import compact_jpeg, observations
from scripts.download_models import verify_files
from backend.pipeline.video import VideoReader
from video_fixtures import normalized_mp4


def jpeg(size=(32, 24)):
    out = BytesIO()
    Image.new("RGB", size, "gray").save(out, "JPEG")
    return out.getvalue()


class FakeRuntime:
    starts = 0

    def __init__(self, config):
        self.config = config
        self.ready = False
        self.process = self
        self.model_loads = dict(detector_loads=1, vision_encoder_loads=1)

    def is_alive(self):
        return self.ready

    def start(self):
        self.ready = True
        FakeRuntime.starts += 1

    def close(self):
        self.ready = False

    def analyze(self, path):
        content = Path(path).read_bytes()
        error = {b"bad": "ValueError", b"timeout": "TimeoutError"}.get(content)
        events = (
            [
                Event(
                    type="violation",
                    rule_id="two_clients_three_seconds",
                    timecode_sec=1,
                    description="Two tracks near a table",
                    confidence=0.7,
                    frames=[jpeg()],
                    frame_timecodes_sec=[1],
                )
            ]
            if content == b"event"
            else []
        )
        return dict(
            perception_complete=error is None,
            analysis_complete=False,
            error_type=error,
            events=events,
            status="partial",
            enabled_rule_ids=[],
            elapsed_sec=0.01,
        )


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "contracts/ml1-response.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.app = create_app(runtime_factory=FakeRuntime, config=PerceptionConfig())

    def test_models_start_once_and_no_rules_is_success(self):
        before = FakeRuntime.starts
        with TestClient(self.app) as client:
            for _ in range(2):
                response = client.post(
                    "/analyze", files={"file": ("a.mov", b"valid", "video/quicktime")}
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), dict(schema_version="1.0", events=[]))
                self.assertNotIn("x-analysis-status", response.headers)
                self.assertNotIn("x-analysis-complete", response.headers)
                self.assertEqual(response.headers["x-rules-enabled"], "none")
                jsonschema.validate(response.json(), self.schema)
            self.assertEqual(FakeRuntime.starts, before + 1)
            self.assertEqual(
                client.get("/health").json()["model_loads"]["detector_loads"], 1
            )
            self.assertEqual(
                client.get("/health").json()["analysis_status"], "no_rules"
            )

    def test_errors_are_not_converted_to_empty_success(self):
        with TestClient(self.app) as client:
            for data, code in [(b"bad", 422), (b"timeout", 504), (b"", 400)]:
                response = client.post("/analyze", files={"file": ("a.mov", data)})
                self.assertEqual(response.status_code, code)
                self.assertNotIn("events", response.json())
                self.assertNotIn("failed", json.dumps(response.json()))
                if code == 504:
                    self.assertEqual(response.headers["x-analysis-status"], "partial")
                    self.assertEqual(response.headers["x-analysis-complete"], "false")
                else:
                    self.assertNotIn("x-analysis-status", response.headers)
                    self.assertNotIn("x-analysis-complete", response.headers)
            self.assertEqual(
                client.post("/analyze", files={"file": ("a.txt", b"x")}).status_code,
                415,
            )

    def test_event_matches_actual_schema_and_decodes_as_jpeg(self):
        with TestClient(self.app) as client:
            response = client.post("/analyze", files={"file": ("a.mov", b"event")})
            jsonschema.validate(response.json(), self.schema)
            event = response.json()["events"][0]
            self.assertTrue(event["id"].startswith("two_clients_three_seconds:"))
            image = Image.open(
                BytesIO(base64.b64decode(event["evidence_frames"][0]["image_base64"]))
            )
            image.load()
            self.assertEqual(image.format, "JPEG")

    def test_normalized_mp4_upload_is_decoded_with_original_pts(self):
        class DecodingRuntime(FakeRuntime):
            def analyze(self, path):
                self.input_suffix = Path(path).suffix
                with VideoReader(path) as reader:
                    self.pts = [
                        sample.actual_timestamp_sec for sample in reader.iter_samples()
                    ]
                return dict(
                    perception_complete=True,
                    analysis_complete=False,
                    error_type=None,
                    events=[],
                    status="partial",
                    enabled_rule_ids=[],
                    elapsed_sec=0.01,
                )

        app = create_app(runtime_factory=DecodingRuntime, config=PerceptionConfig())
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "video.mp4"
            normalized_mp4(video, (2000, 2100, 2200, 2900, 3000, 3600))
            with TestClient(app) as client, video.open("rb") as stream:
                response = client.post(
                    "/analyze", files={"file": ("video.mp4", stream, "video/mp4")}
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.json(), {"schema_version": "1.0", "events": []}
                )
                self.assertEqual(response.headers["x-rules-enabled"], "none")
                self.assertNotIn("x-analysis-status", response.headers)
                self.assertNotIn("x-analysis-complete", response.headers)
                self.assertEqual(app.state.runtime.input_suffix, ".mp4")
                self.assertEqual(app.state.runtime.pts, [2, 2.9, 3, 3.6])

    def test_large_source_evidence_is_downsized(self):
        result = compact_jpeg(jpeg((4000, 3000)), max_chars=5000)
        self.assertLessEqual(len(result), 5000)
        with Image.open(BytesIO(base64.b64decode(result))) as image:
            image.load()
            self.assertLessEqual(image.width * image.height, 8_000_000)
            self.assertLessEqual(max(image.size), 8192)

    def test_setup_rejects_corrupt_assets_and_path_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "asset").write_bytes(b"wrong")
            with self.assertRaisesRegex(ValueError, "corrupt"):
                verify_files(root, {"asset": dict(size=5, sha256="bad")})
            with self.assertRaisesRegex(ValueError, "escapes"):
                verify_files(root, {"../other": dict(size=0, sha256="bad")})
