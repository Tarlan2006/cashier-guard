import base64
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import unittest

from fastapi.testclient import TestClient
from PIL import Image

from matching.app import ASSESSMENT_REASON, app
from scripts.check_events import validate_result

REPO = Path(__file__).resolve().parents[2]


def request_fixture():
    rules = json.loads((REPO / "data/rules.json").read_text(encoding="utf-8"))["rules"]
    image = BytesIO()
    Image.new("RGB", (16, 16), "gray").save(image, format="JPEG")
    event = dict(id=f"{rules[0]['id']}:0:2.000", start_sec=2, end_sec=3,
                 description="Synthetic observation; no real scene inferred",
                 evidence_frames=[dict(timestamp_sec=2,
                    image_base64=base64.b64encode(image.getvalue()).decode("ascii"))])
    return dict(schema_version="1.0", duration_sec=10, events=[event], rules=rules)


class MatchingServiceTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_declares_no_semantics_without_stub_markers(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "semantic_matching": False})
        self.assertNotIn("stub", response.json())
        self.assertNotIn("transport_fixture", response.json())

    def test_empty_events_return_explicit_no_violation(self):
        payload = request_fixture()
        payload["events"] = []
        response = self.client.post("/match", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"verdict": "no_violation", "violations": []})

    def test_known_rule_is_needs_review_and_preserves_observation(self):
        payload = request_fixture()
        response = self.client.post("/match", json=payload)
        self.assertEqual(response.status_code, 200)
        result = validate_result(response.json(), payload["duration_sec"], payload["rules"])
        self.assertEqual(result["verdict"], "violation")
        event = result["violations"][0]
        self.assertEqual(event["rule_id"], payload["rules"][0]["id"])
        self.assertEqual(event["type"], payload["rules"][0]["title"])
        self.assertEqual(event["assessment"], "needs_review")
        self.assertEqual(event["assessment_reason"], ASSESSMENT_REASON)
        self.assertEqual(event["description"], payload["events"][0]["description"])
        self.assertEqual(event["evidence_frames"], payload["events"][0]["evidence_frames"])
        self.assertNotIn("x-matching-stub", response.headers)

    def test_unknown_rule_is_error_instead_of_empty_success(self):
        payload = request_fixture()
        payload["events"][0]["id"] = "UNKNOWN:0:2.000"
        self.assertEqual(self.client.post("/match", json=payload).status_code, 422)

    def test_invalid_schema_is_rejected_even_when_no_events(self):
        for invalid in ({}, {"schema_version": "1.0", "events": []},
                        {**request_fixture(), "duration_sec": 0},
                        {**request_fixture(), "rules": []},
                        {**request_fixture(), "events": "not-a-list"}):
            with self.subTest(payload_fields=list(invalid)):
                self.assertEqual(self.client.post("/match", json=invalid).status_code, 422)

    def test_invalid_id_timestamp_interval_and_evidence_are_rejected(self):
        original = request_fixture()
        for identifier in ("KZ-CASH-001", "KZ-CASH-001:-1:2", "KZ-CASH-001:0:nan",
                           "KZ-CASH-001:0:4.000", "KZ-CASH-001:0:10"):
            payload = deepcopy(original)
            payload["events"][0]["id"] = identifier
            with self.subTest(identifier=identifier):
                self.assertEqual(self.client.post("/match", json=payload).status_code, 422)
        for change in (dict(end_sec=1), dict(evidence_frames=[dict(timestamp_sec=2, image_base64="AAAA")])):
            payload = deepcopy(original)
            payload["events"][0].update(change)
            self.assertEqual(self.client.post("/match", json=payload).status_code, 422)

    def test_rounding_of_ml1_timestamp_and_supplied_catalog_are_supported(self):
        payload = request_fixture()
        payload["events"][0].update(id="custom-rule:001:2.123", start_sec=2.1234)
        payload["rules"][0]["id"] = "custom-rule"
        response = self.client.post("/match", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["violations"][0]["rule_id"], "custom-rule")
