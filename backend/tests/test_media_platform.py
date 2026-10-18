"""Output quota fallback and the unchanged Unix subprocess contract."""
import asyncio
from types import SimpleNamespace
import sys

import pytest

from app import media


def polling_platform(monkeypatch):
    monkeypatch.setattr(media, "os", SimpleNamespace(name="nt"))
    # The fallback must never read a signal constant absent on Windows.
    monkeypatch.setattr(media, "signal", SimpleNamespace())


def test_polling_stops_running_writer_reaps_and_removes_partial(tmp_path, monkeypatch):
    polling_platform(monkeypatch)
    output = tmp_path / "oversized.bin"
    children = []
    original = asyncio.create_subprocess_exec

    async def tracked(*args, **kwargs):
        process = await original(*args, **kwargs)
        children.append((args, process))
        return process

    monkeypatch.setattr(media.asyncio, "create_subprocess_exec", tracked)
    program = "import sys,time; f=open(sys.argv[1],'wb'); f.write(b'x'*8192); f.flush(); time.sleep(30)"
    with pytest.raises(media.PipelineError) as error:
        asyncio.run(media.command(sys.executable, "-c", program, str(output),
                                  output_path=output, max_bytes=4096, timeout=3))
    assert error.value.code == "VIDEO_STORAGE_LIMIT"
    assert not output.exists()
    assert children[0][0] == (sys.executable, "-c", program, str(output))
    assert children[0][1].returncode is not None


def test_polling_checks_fast_writer_even_after_successful_exit(tmp_path, monkeypatch):
    polling_platform(monkeypatch)
    output = tmp_path / "fast.bin"
    with pytest.raises(media.PipelineError) as error:
        asyncio.run(media.command(sys.executable, "-c",
            "import sys; open(sys.argv[1],'wb').write(b'x'*100000)", str(output),
            output_path=output, max_bytes=4096, timeout=3))
    assert error.value.code == "VIDEO_STORAGE_LIMIT"
    assert not output.exists()


def test_polling_accepts_output_below_quota(tmp_path, monkeypatch):
    polling_platform(monkeypatch)
    output = tmp_path / "small.bin"
    result = asyncio.run(media.command(sys.executable, "-c",
        "import sys; open(sys.argv[1],'wb').write(b'x'*1024); sys.stdout.write('ok')", str(output),
        output_path=output, max_bytes=4096, timeout=3))
    assert result == b"ok"
    assert output.stat().st_size == 1024


class FinishedProcess:
    def __init__(self, returncode):
        self.returncode = returncode
        self.stdout = self.stderr = self

    async def read(self, size):
        return b""

    async def wait(self):
        return self.returncode

    async def communicate(self):
        return b"", b""


def test_unix_keeps_exact_exec_wrapper_sigxfsz_and_partial_file(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(media, "signal", SimpleNamespace(SIGXFSZ=25))
    find_spec = media.importlib.util.find_spec
    monkeypatch.setattr(media.importlib.util, "find_spec", lambda name: object() if name == "resource" else find_spec(name))
    monkeypatch.setattr(media.shutil, "which", lambda _: "ffmpeg")
    calls = []

    async def spawn(*args, **kwargs):
        calls.append(args)
        return FinishedProcess(-25)

    monkeypatch.setattr(media.asyncio, "create_subprocess_exec", spawn)
    output = tmp_path / "unix.bin"
    output.write_bytes(b"bounded")
    with pytest.raises(media.PipelineError) as error:
        asyncio.run(media.command("ffmpeg", "-y", str(output), output_path=output, max_bytes=4096))
    assert calls == [(sys.executable, "-c",
        "import os,resource,sys; n=int(sys.argv[1]); resource.setrlimit(resource.RLIMIT_FSIZE,(n,n)); os.execvp(sys.argv[2],sys.argv[2:])",
        "4096", "ffmpeg", "-y", str(output))]
    assert error.value.code == "VIDEO_STORAGE_LIMIT"
    assert output.read_bytes() == b"bounded"


def test_missing_resource_uses_direct_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(media, "signal", SimpleNamespace(SIGXFSZ=25))
    find_spec = media.importlib.util.find_spec
    monkeypatch.setattr(media.importlib.util, "find_spec", lambda name: None if name == "resource" else find_spec(name))
    monkeypatch.setattr(media.shutil, "which", lambda _: "ffmpeg")
    calls = []

    async def spawn(*args, **kwargs):
        calls.append(args)
        return FinishedProcess(0)

    monkeypatch.setattr(media.asyncio, "create_subprocess_exec", spawn)
    output = tmp_path / "fallback.bin"
    assert asyncio.run(media.command("ffmpeg", str(output), output_path=output, max_bytes=4096)) == b""
    assert calls == [("ffmpeg", str(output))]
