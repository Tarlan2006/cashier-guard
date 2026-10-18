"""Launcher routing, patch isolation and missing-runtime behavior, no models."""
from contextlib import redirect_stdout
from hashlib import sha256
from io import StringIO
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.launch_chain import ROOT, docker_command, main, prepare_native_backend, require_runtime


class LaunchTests(unittest.TestCase):
    def test_native_linux_and_windows_backend_are_distinguished(self):
        self.assertEqual(require_runtime('auto',platform='posix'),'native')
        with self.assertRaisesRegex(RuntimeError,'requires Linux'):
            require_runtime('native',platform='nt')

    def test_missing_docker_does_not_attempt_installation_or_startup(self):
        with patch('scripts.launch_chain.shutil.which',return_value=None), \
             patch('scripts.launch_chain.subprocess.run') as run:
            with self.assertRaisesRegex(RuntimeError,'unavailable'):
                require_runtime('auto',platform='nt')
            run.assert_not_called()

    def test_docker_requires_running_linux_engine(self):
        with patch('scripts.launch_chain.shutil.which',return_value='docker'), \
             patch('scripts.launch_chain.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='windows')):
            with self.assertRaisesRegex(RuntimeError,'Linux Docker engine'):
                require_runtime('docker')

    def test_native_patch_changes_only_cache_copy(self):
        original=ROOT.parent/'backend/app/pipeline.py';before=sha256(original.read_bytes()).hexdigest()
        cache=ROOT/'cache';cache.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=cache) as directory:
            backend=prepare_native_backend(Path(directory))
            text=(backend/'app/pipeline.py').read_text(encoding='utf-8')
            self.assertIn('ML2_REQUEST_TIMEOUT_SECONDS = 100',text)
            self.assertIn('ML2_READ_TIMEOUT_SECONDS = 90',text)
            self.assertIn('ML_REQUEST_TIMEOUT_SECONDS = 190',text)
            self.assertIn('ML1_READ_TIMEOUT_SECONDS = 180',text)
        self.assertEqual(before,sha256(original.read_bytes()).hexdigest())

    def test_docker_uses_env_names_no_secrets_and_no_runtime_pull(self):
        args=docker_command('local-image','owned-unit',Path('rules.json'),Path('storage'))
        self.assertIn('never',args)
        self.assertIn('127.0.0.1:8000:8000',args)
        self.assertIn('API_KEY',args)
        self.assertFalse(any('API_KEY=' in value for value in args))
        self.assertTrue(any('target=/app/catalog.json,readonly' in value for value in args))

    def test_preflight_failure_never_starts_host_services(self):
        with patch('scripts.launch_chain.require_runtime',side_effect=RuntimeError('Linux unavailable')), \
             patch('scripts.launch_chain.local_processes') as start, redirect_stdout(StringIO()):
            result=main(['--models','unused','--rules-path','unused'])
        self.assertEqual(result,1)
        start.assert_not_called()


if __name__=='__main__':unittest.main()
