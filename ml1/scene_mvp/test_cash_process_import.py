import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from import_cash_process import main


class ProcessImportTests(unittest.TestCase):
    def test_geometry_only_import_preserves_original_and_updates_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);trial=root/'local/cash-process-test';source=trial/'X-13';source.mkdir(parents=True);(root/'outputs').mkdir()
            video=source/'source.bin';video.write_bytes(b'synthetic video fixture, no bank data')
            digest=hashlib.sha256(video.read_bytes()).hexdigest();frame=source/'frame.jpg';frame.write_bytes(b'synthetic frame hash fixture')
            (source/'session.local.json').write_text(json.dumps({'source_video':str(video),'source_video_sha256':digest}))
            definition={'case_id':'X-13','source_session':str(source),'source_video_sha256':digest,'duration_sec':20,
                'sample_times_sec':[0,1,2],'frame_sha256':{'frame.jpg':hashlib.sha256(frame.read_bytes()).hexdigest()}}
            pp=trial/'protocol.local.json';pp.write_text(json.dumps({'review_session':trial.name,'cases':[definition]}))
            case={**{k:definition[k] for k in ['case_id','source_session','source_video_sha256']},
                'confirmed':True,'human_cash_type_confirmed':True,'cash_anchor_sec':1,'same_cash_batch':'unclear',
                'zones':{k:[.1,.1,.3,.3] for k in ['machine_zone','safe_zone','cash_seed']}}
            review={'schema_version':'cash-process-review/1','review_session':trial.name,'protocol_sha256':hashlib.sha256(pp.read_bytes()).hexdigest(),
                'confirmed':True,'automatic_legal_verdict':False,'cases':[case]}
            download=root/'download.json';raw=json.dumps(review).encode();download.write_bytes(raw)
            with patch('import_cash_process.ROOT',root),patch('build_unified_review.main') as update,patch.object(sys,'argv',['import_cash_process','--trial',str(trial),'--review',str(download)]):main()
            update.assert_called_once();self.assertEqual((trial/'human-review.original.local.json').read_bytes(),raw)
            summary=json.loads((root/'outputs/forte_cash_process_sequences.json').read_text())
            self.assertEqual(summary['cases'][0]['result']['visible_sequence_state'],'incomplete_evidence')
            self.assertEqual(summary['cases'][0]['result']['storage_state'],'not_annotated')
            self.assertIsNone(summary['cases'][0]['result']['legal_violation_label'])


if __name__=='__main__':unittest.main()
