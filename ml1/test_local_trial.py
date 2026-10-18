"""Tests use invented metadata only; never load the dataset or a model."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

from run_local_trial import parse_observations


class TrialValidationTests(unittest.TestCase):
    def setUp(self):
        self.frames = [
            {'index': 0, 'timestamp_sec': 0.033, 'file': 'frame-00.jpg'},
            {'index': 1, 'timestamp_sec': 2.367, 'file': 'frame-01.jpg'},
        ]
        self.payload = {'observations': [{
            'start_frame': 0, 'end_frame': 1, 'description': 'Synthetic object moves.',
            'evidence_frame_indices': [0, 1],
        }], 'uncertainties': []}

    def test_timestamps_come_from_decoded_frames(self):
        result = parse_observations(json.dumps(self.payload), self.frames)
        event = result['events'][0]
        self.assertEqual((event['start_sec'], event['end_sec']), (0.033, 2.367))
        self.assertEqual(event['review_status'], 'needs_review')

    def test_out_of_range_evidence_is_rejected(self):
        self.payload['observations'][0]['evidence_frame_indices'] = [2]
        with self.assertRaises(ValueError):
            parse_observations(json.dumps(self.payload), self.frames)

    def test_evidence_outside_event_interval_is_rejected(self):
        self.payload['observations'][0]['start_frame'] = 1
        with self.assertRaises(ValueError):
            parse_observations(json.dumps(self.payload), self.frames)

    def test_missing_observations_is_not_treated_as_no_events(self):
        with self.assertRaises(ValueError):
            parse_observations('{}', self.frames)

    def test_extra_prose_is_not_silently_accepted(self):
        with self.assertRaises(ValueError):
            parse_observations('Model explanation: ' + json.dumps(self.payload), self.frames)

    def test_network_connections_are_blocked(self):
        code = '''from run_local_trial import offline_only
import socket
offline_only()
try:
    socket.create_connection(('127.0.0.1', 9), timeout=0.1)
except OSError as error:
    assert 'Network connections are disabled' in str(error)
else:
    raise AssertionError('Network guard missing')
'''
        subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parent, check=True)


if __name__ == '__main__':
    unittest.main()
