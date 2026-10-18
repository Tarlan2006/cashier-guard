from pathlib import Path
import tempfile
import unittest

import httpx

from scripts.robustness_check import ROOT, external_output, local_url, observe


class RobustnessSafetyTests(unittest.TestCase):
    def test_external_destinations_and_redirect_credentials_are_rejected(self):
        for url in ("https://example.com", "http://192.168.1.1:8001",
                    "http://127.0.0.1.example.com", "http://user:pass@127.0.0.1:8001",
                    "http://127.0.0.1:8001/?token=x", "http://127.0.0.1:8001/path"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                local_url(url)
        self.assertEqual(local_url("http://127.0.0.1:8001/"), "http://127.0.0.1:8001")
        self.assertEqual(local_url("http://[::1]:8001"), "http://[::1]:8001")

    def test_media_output_cannot_enter_checkout(self):
        for directory in (ROOT.parent, ROOT / "cache", ROOT.parent / "data"):
            with self.subTest(directory=directory), self.assertRaises(ValueError):
                external_output(directory)
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(external_output(Path(directory)), Path(directory).resolve())

    def test_empty_events_do_not_invent_role_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unit.mp4"
            path.write_bytes(b"synthetic-upload")
            transport = httpx.MockTransport(lambda request: httpx.Response(200,
                json={"schema_version": "1.0", "events": []},
                headers={"X-Rules-Enabled": "none", "X-Perception-Complete": "true"}))
            with httpx.Client(transport=transport) as client:
                result = observe(client, "http://127.0.0.1:8001", path)
            self.assertEqual(result["events"], 0)
            self.assertFalse(result["diagnostics_available"])
            self.assertIsNone(result["cashier"])
            self.assertIsNone(result["counter_machine"])

    def test_timeout_response_remains_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unit.mp4"
            path.write_bytes(b"synthetic-upload")
            transport = httpx.MockTransport(lambda request: httpx.Response(504,
                json={"detail": "timeout"}, headers={"X-Analysis-Status": "partial"}))
            with httpx.Client(transport=transport) as client:
                result = observe(client, "http://127.0.0.1:8001", path)
            self.assertEqual(result["status"], 504)
            self.assertEqual(result["analysis_status"], "partial")
            self.assertIsNone(result["events"])
