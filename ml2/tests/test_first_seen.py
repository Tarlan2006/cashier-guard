"""Visible onset is preserved when confirmation comes later."""

import unittest
from backend.pipeline.perception.timestamps import annotate_first_seen


class FirstSeenTests(unittest.TestCase):
    def test_person_onset_does_not_shift_to_confirmation(self):
        facts = {
            "frames": [
                dict(
                    timestamp_sec=i * 0.5,
                    persons=[dict(id=1, confirmed=i >= 4, event_eligible=i >= 4)],
                    objects=[],
                )
                for i in range(8)
            ]
        }
        annotate_first_seen(facts)
        event = facts["events"][0]
        self.assertEqual(event["timecode_sec"], 0.0)
        self.assertEqual(event["confirmed_at"], 2.0)
        self.assertEqual(facts["frames"][-1]["persons"][0]["first_seen"], 0.0)

    def test_new_object_uses_its_first_source_frame(self):
        facts = {
            "frames": [
                dict(
                    timestamp_sec=i * 0.5,
                    persons=[],
                    objects=(
                        []
                        if i < 4
                        else [{"class": "handbag", "bbox": [0.2, 0.2, 0.3, 0.3]}]
                    ),
                )
                for i in range(8)
            ]
        }
        annotate_first_seen(facts)
        event = facts["events"][0]
        self.assertEqual(event["first_seen"], 2.0)
        self.assertEqual(event["confirmed_at"], 2.5)

    def test_uncertain_or_reflected_person_is_retained_without_confirmed_event(self):
        for flag in ["uncertain", "is_reflection"]:
            facts = {
                "frames": [
                    dict(
                        timestamp_sec=i * 0.5,
                        persons=[dict(id=1, event_eligible=True, **{flag: True})],
                        objects=[],
                    )
                    for i in range(8)
                ]
            }
            annotate_first_seen(facts)
            self.assertEqual(facts["events"], [])
            self.assertEqual(facts["frames"][0]["persons"][0]["first_seen"], 0.0)


if __name__ == "__main__":
    unittest.main()
