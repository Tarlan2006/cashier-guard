"""API contracts, source JPEGs and an actual hung-process deadline."""

import base64
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from backend.pipeline.analyze import analyze_facts, analyze_report, analyze_video
from backend.pipeline.analysis_worker import supervise
from backend.pipeline.perception import PerceptionConfig
from backend.schemas import Event

RULE = "two_clients_three_seconds"
JPEG = b"\xff\xd8fixture\xff\xd9"


def candidate():
    return dict(
        rule_id=RULE,
        timecode_sec=0.5,
        first_seen=0.5,
        confirmed_at=3.5,
        description="Два клиентских трека одновременно у стола.",
        confidence=0.9,
    )


def hung_worker(path, config, queue, started):
    queue.put(
        (
            "event",
            Event(
                type="violation",
                rule_id=RULE,
                timecode_sec=0.5,
                description="Synthetic deadline fixture",
                confidence=0.9,
                frames=[JPEG],
                frame_timecodes_sec=[0.5],
            ),
        )
    )
    time.sleep(30)


class AnalyzeContractTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.video = Path(self.directory.name) / "local.mov"
        self.video.touch()
        self.config = PerceptionConfig(validated_rule_ids=[RULE])

    def timeline(self):
        return {
            "video": {"name": self.video.name},
            "semantic_engine": {"events": [candidate()]},
        }

    def test_enabled_rule_has_original_onset_and_json_jpegs(self):
        with patch(
            "backend.pipeline.analysis_worker.extract_jpegs",
            return_value=[(0.0, JPEG), (0.5, JPEG), (1.5, JPEG)],
        ) as decode:
            event = analyze_facts(self.video, self.timeline(), config=self.config)[0]
        self.assertEqual(event.type, "violation")
        self.assertEqual(event.timecode_sec, 0.5)
        self.assertEqual(event.first_seen, 0.5)
        self.assertEqual(event.confirmed_at, 3.5)
        decode.assert_called_once_with(self.video, [0.0, 0.5, 1.5])
        payload = json.loads(json.dumps(event.to_dict()))
        self.assertEqual(base64.b64decode(payload["frames"][0]), JPEG)

    def test_disabled_unknown_and_presence_rules_emit_nothing(self):
        for rule in (RULE, "stub_person_presence", "made_up_rule"):
            facts = self.timeline()
            facts["semantic_engine"]["events"][0]["rule_id"] = rule
            with self.subTest(rule=rule), patch(
                "backend.pipeline.analysis_worker.extract_jpegs"
            ) as decode:
                self.assertEqual(
                    analyze_facts(
                        self.video,
                        facts,
                        config=PerceptionConfig(validated_rule_ids=[]),
                    ),
                    [],
                )
                decode.assert_not_called()
        self.assertEqual(
            analyze_facts(
                self.video, {"frames": [{"persons": [{"id": 1}]}]}, config=self.config
            ),
            [],
        )

    def test_configured_rule_must_exist_in_catalog(self):
        with self.assertRaisesRegex(ValueError, "absent from catalog"):
            analyze_facts(
                self.video,
                self.timeline(),
                config=PerceptionConfig(validated_rule_ids=["typo"]),
            )

    def test_missing_evidence_does_not_publish_an_event(self):
        with patch("backend.pipeline.analysis_worker.extract_jpegs", return_value=[]):
            with self.assertRaisesRegex(ValueError, "1-3 source JPEGs"):
                analyze_facts(self.video, self.timeline(), config=self.config)

    def test_facts_must_belong_to_source_video(self):
        facts = self.timeline()
        facts["video"]["name"] = "other.mov"
        with self.assertRaisesRegex(ValueError, "does not match input"):
            analyze_facts(self.video, facts, config=self.config)

    def test_missing_input_is_partial_without_failed(self):
        config = PerceptionConfig(
            adaptive_after_sec=1.0, stop_after_sec=3.0, api_timeout_sec=4.0
        )
        report = analyze_report(self.video.parent / "absent.mov", config=config)
        self.assertEqual(report["status"], "partial")
        self.assertIsNone(report["verdict"])
        self.assertFalse(report["analysis_complete"])
        self.assertTrue(report["warnings"])

    def test_list_api_preserves_event_contract(self):
        event = Event(
            type="violation",
            rule_id=RULE,
            timecode_sec=1.0,
            description="Fixture",
            confidence=0.9,
        )
        with patch(
            "backend.pipeline.analyze.supervise", return_value={"events": [event]}
        ):
            self.assertEqual(analyze_video(self.video, config=self.config), [event])

    def test_report_serializes_event_bytes(self):
        event = Event(
            type="violation",
            rule_id=RULE,
            timecode_sec=1.0,
            description="Fixture",
            confidence=0.9,
            frames=[JPEG],
            frame_timecodes_sec=[1.0],
        )
        with patch(
            "backend.pipeline.analyze.supervise",
            return_value={"events": [event], "verdict": "нарушение"},
        ):
            report = analyze_report(self.video, config=self.config)
        self.assertEqual(report["enabled_rule_ids"], [RULE])
        self.assertEqual(
            json.loads(json.dumps(report))["events"][0]["frames_encoding"],
            "base64/jpeg",
        )

    def test_hard_timeout_keeps_progress_event(self):
        config = PerceptionConfig(
            adaptive_after_sec=1.0, stop_after_sec=3.0, api_timeout_sec=4.0
        )
        report = supervise(self.video, config, worker=hung_worker)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["verdict"], "нарушение")
        self.assertEqual(len(report["events"]), 1)
        self.assertLess(report["elapsed_sec"], 4.25)

    def test_three_jpegs_decode_from_original_video(self):
        video = self.video.with_suffix(".avi")
        writer = cv2.VideoWriter(
            str(video), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (64, 48)
        )
        if not writer.isOpened():
            self.skipTest("MJPG codec unavailable")
        try:
            for i in range(20):
                frame = np.zeros((48, 64, 3), np.uint8)
                frame[:, :, (2 if i < 5 else 1 if i < 15 else 0)] = 255
                writer.write(frame)
        finally:
            writer.release()
        facts = self.timeline()
        facts["video"]["name"] = video.name
        event = analyze_facts(video, facts, config=self.config)[0]
        self.assertEqual(len(event.frames), 3)
        decoded = [
            cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            for jpeg in event.frames
        ]
        self.assertTrue(all(image is not None for image in decoded))
        self.assertEqual(
            [int(image.mean(axis=(0, 1)).argmax()) for image in decoded], [2, 1, 0]
        )


if __name__ == "__main__":
    unittest.main()
