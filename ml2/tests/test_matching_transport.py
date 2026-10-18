"""Transport validation is independent of trained models and scene inference."""
import base64
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import socket
import tempfile
import unittest

from fastapi.testclient import TestClient
from PIL import Image

from scripts.check_events import ContractError, validate_payload, validate_rules
from scripts.matching_stub import app
from scripts.run_chain import open_videos, require_free_ports, main as run_chain


def rule():
    return dict(id='unit:rule', title='Synthetic contract fixture',
        visual_signs=['Synthetic test condition'], document='Not a normative source',
        section='Unit test only', url='https://example.invalid/fixture', is_demo=False)


def frame(format='JPEG'):
    stream = BytesIO()
    Image.new('RGB',(24,16),'gray').save(stream,format)
    return dict(timestamp_sec=1.,image_base64=base64.b64encode(stream.getvalue()).decode('ascii'))


def observation():
    return dict(id='unit:rule:000:1.000',start_sec=1.,end_sec=2.,
                description='Synthetic transport observation',evidence_frames=[frame()])


def request(events=None):
    return dict(schema_version='1.0', events=[] if events is None else events,
                duration_sec=10.,rules=[rule()])


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_empty_is_explicit_stub_no_violation(self):
        response = self.client.post('/match',json=request())
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json(),dict(verdict='no_violation',violations=[]))
        self.assertEqual(response.headers['x-matching-stub'],'true')
        self.assertTrue(self.client.get('/health').json()['stub'])

    def test_known_rule_with_colon_copies_evidence_without_mutating_input(self):
        data=request([observation()]);before=deepcopy(data)
        response=self.client.post('/match',json=data)
        self.assertEqual(response.status_code,200)
        result=response.json();event=result['violations'][0]
        self.assertEqual(result['verdict'],'violation')
        self.assertEqual(event['rule_id'],'unit:rule')
        self.assertEqual(event['timecode_sec'],1.)
        self.assertEqual(event['evidence_frames'],data['events'][0]['evidence_frames'])
        self.assertEqual(event['assessment'],'needs_review')
        self.assertEqual(data,before)
        validate_payload(result,kind='result',duration=10,rules=[rule()])

    def test_missing_events_empty_catalog_and_bad_version_are_errors(self):
        missing=request();del missing['events']
        for payload in ({},missing,dict(request(),rules=[]),dict(request(),schema_version='2.0')):
            with self.subTest(keys=list(payload)):
                response=self.client.post('/match',json=payload)
                self.assertEqual(response.status_code,422)
                self.assertNotIn('verdict',response.json())

    def test_unknown_rule_and_invalid_evidence_are_errors(self):
        unknown=observation();unknown['id']='unknown:000:1.000'
        png=observation();png['evidence_frames']=[frame('PNG')]
        for event in (unknown,png):
            self.assertEqual(self.client.post('/match',json=request([event])).status_code,422)

    def test_duplicate_ids_and_invalid_intervals_rejected(self):
        event=observation();event['end_sec']=0.
        for events in ([observation(),observation()],[event]):
            self.assertEqual(self.client.post('/match',json=request(events)).status_code,422)


class EvidenceValidationTests(unittest.TestCase):
    def payload(self):
        return dict(schema_version='1.0',events=[observation()])

    def test_nonfinite_and_out_of_bounds_timestamps(self):
        for timestamp in (float('nan'),float('inf'),10**500,True,-1,10):
            data=self.payload();data['events'][0]['evidence_frames'][0]['timestamp_sec']=timestamp
            with self.subTest(timestamp=timestamp),self.assertRaises(ContractError):
                validate_payload(data,kind='ml1',duration=10)

    def test_end_may_equal_duration_but_frame_may_not(self):
        data=self.payload();data['events'][0]['end_sec']=10
        self.assertTrue(validate_payload(data,kind='ml1',duration=10)['valid'])

    def test_truncated_jpeg_invalid_base64_and_oversized_image(self):
        data=self.payload()
        valid=base64.b64decode(data['events'][0]['evidence_frames'][0]['image_base64'])
        large=BytesIO();Image.new('RGB',(3000,3000),'gray').save(large,'JPEG')
        values=['not base64',base64.b64encode(valid[:100]).decode(),base64.b64encode(large.getvalue()).decode()]
        for value in values:
            data['events'][0]['evidence_frames'][0]['image_base64']=value
            with self.subTest(length=len(value)),self.assertRaises(ContractError):
                validate_payload(data,kind='ml1')

    def test_invalid_response_does_not_echo_image(self):
        data=self.payload();value='DO-NOT-PRINT-THIS-IMAGE'
        data['events'][0]['evidence_frames'][0]['image_base64']=value
        with self.assertRaises(ContractError) as error:
            validate_payload(data)
        self.assertNotIn(value,str(error.exception))

    def test_inconsistent_result_unknown_rule_and_forged_source(self):
        with self.assertRaises(ContractError):
            validate_payload(dict(verdict='violation',violations=[]))
        result=TestClient(app).post('/match',json=request([observation()])).json()
        result['violations'][0]['rule_id']='unknown'
        with self.assertRaises(ContractError):validate_payload(result,rules=[rule()])
        result['violations'][0]['rule_id']='unit:rule'
        result['violations'][0]['rule']=dict(rule(),document='Changed source')
        with self.assertRaises(ContractError):validate_payload(result,rules=[rule()])

    def test_rules_default_fields_are_normalized_and_demo_rules_rejected(self):
        data=rule();del data['is_demo']
        self.assertFalse(validate_rules([data])['unit:rule']['is_demo'])
        with self.assertRaises(ContractError):validate_rules([dict(rule(),is_demo=True)])

    def test_failed_job_cannot_be_accepted_as_empty_result(self):
        job=dict(job_id='test',filename='video.mp4',created_at='2026-10-18T00:00:00Z',mode='live',
            status='done',stage='done',verdict='no_violation',violations=[],duration_sec=10)
        self.assertTrue(validate_payload(job,kind='job',expect_empty=True)['valid'])
        job.update(status='failed',stage='failed',verdict=None,error_code='ML1_TIMEOUT')
        with self.assertRaisesRegex(ContractError,'ML1_TIMEOUT'):validate_payload(job,kind='job')


class ChainTests(unittest.TestCase):
    def test_open_video_numbers_accept_both_alphabets_and_reject_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'data/open';(root/'videos').mkdir(parents=True)
            (root/'videos/X-2.mov').write_bytes(b'unit')
            (root/'videos/\u0425-14.mov').write_bytes(b'unit')
            self.assertEqual([n for n,_ in open_videos(root,[2,14])],[2,14])
            with self.assertRaises(ValueError):open_videos(root,[99])
            closed=root.parent/'closed';closed.mkdir()
            with self.assertRaises(ValueError):open_videos(closed,[2])

    def test_occupied_port_is_not_reused(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));listener.listen()
            with self.assertRaises(RuntimeError):require_free_ports([listener.getsockname()[1]])

    def test_existing_report_is_not_overwritten(self):
        root=Path(__file__).resolve().parents[1]/'cache'
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as directory:
            path=Path(directory);report=path/'report.json';report.write_text('KEEP')
            code=run_chain(['--open-root',str(path),'--rules-path',str(path/'missing.json'),
                            '--output-dir',str(path)])
            self.assertEqual(code,1)
            self.assertEqual(report.read_text(),'KEEP')


if __name__ == '__main__':unittest.main()
