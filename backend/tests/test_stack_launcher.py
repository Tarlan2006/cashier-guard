"""Launcher safety: fail closed and clean up only its own process groups."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

spec = importlib.util.spec_from_file_location("start_stack", Path(__file__).resolve().parents[2] / "scripts/start_stack.py")
stack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stack)


@pytest.fixture
def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return str(probe.getsockname()[1])


def test_missing_matching_does_not_start_backend_or_models(monkeypatch, free_port):
    monkeypatch.setattr(stack, "health", lambda url: {} if ":8001/" in url else None)
    monkeypatch.setattr(stack.shutil, "which", lambda *_, **__: "/usr/bin/ffmpeg")
    monkeypatch.setattr(stack.subprocess, "Popen", lambda *_, **__: pytest.fail("Must fail before launching any process"))
    with pytest.raises(ValueError, match="ML2 недоступен"):
        stack.launch({"API_KEY": "private-test-key", "PORT": free_port}, build=False)


@pytest.mark.parametrize("value", ["http://user:secret@localhost:8001", "http://localhost:8001?key=secret", "https://example.com"])
def test_remote_or_secret_bearing_model_urls_are_rejected_without_echo(value):
    with pytest.raises(ValueError) as error:
        stack.local_url(value)
    assert value not in str(error.value) and "secret" not in str(error.value)


@pytest.mark.skipif(os.name != "posix", reason="Native launcher is POSIX only")
def test_rejecting_matching_stub_stops_owned_process_but_preserves_external(tmp_path, monkeypatch, free_port):
    (tmp_path / "frontend/dist").mkdir(parents=True)
    (tmp_path / "frontend/dist/index.html").write_text("fixture")
    monkeypatch.setattr(stack, "ROOT", tmp_path)
    monkeypatch.setattr(stack, "health", lambda url: {"stub": True} if ":8002/" in url else {"status": "ok"})
    monkeypatch.setattr(stack.shutil, "which", lambda *_, **__: "/usr/bin/ffmpeg")
    original = subprocess.Popen
    owned = []

    def spawn(*args, **kwargs):
        child = original(*args, **kwargs)
        owned.append(child)
        return child

    external = original([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    monkeypatch.setattr(stack.subprocess, "Popen", spawn)
    try:
        with pytest.raises(RuntimeError, match="stub=true"):
            stack.launch({"API_KEY": "private-test-key", "PORT": free_port, "ML1_COMMAND_JSON": json.dumps([sys.executable, "-c", "import time; time.sleep(60)"]),
                          "ML1_WORKDIR": str(tmp_path)}, build=False, timeout=2)
        assert len(owned) == 1 and owned[0].poll() is not None
        assert external.poll() is None
    finally:
        external.terminate()
        external.wait(timeout=5)
