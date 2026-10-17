"""Optional depth setup validates all assets before copying, without network."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts.download_models import install_depth_small


class DepthSetupTests(unittest.TestCase):
    def test_verified_bundle_copy_and_corruption_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';target=root/'target';name='depth-anything-v2-small/model.safetensors'
            path=source/name;path.parent.mkdir(parents=True);path.write_bytes(b'synthetic-test-weights')
            record=dict(size=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            manifest=root/'manifest.json';manifest.write_text(json.dumps(dict(models=[dict(license='Apache-2.0')],runtime_files={name:record})))
            with patch('scripts.download_models.DEPTH_MANIFEST',manifest):
                install_depth_small(target,source)
                self.assertEqual((target/name).read_bytes(),path.read_bytes())
                install_depth_small(target,verify_only=True)
                path.write_bytes(b'corrupt')
                with self.assertRaisesRegex(ValueError,'corrupt'):install_depth_small(root/'bad-target',source)
                self.assertFalse((root/'bad-target').exists())

    def test_non_apache_model_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);manifest=root/'manifest.json'
            manifest.write_text(json.dumps(dict(models=[dict(license='CC-BY-NC-4.0')],runtime_files={})))
            with patch('scripts.download_models.DEPTH_MANIFEST',manifest):
                with self.assertRaisesRegex(ValueError,'Small'):install_depth_small(root/'models')


if __name__=='__main__':unittest.main()
