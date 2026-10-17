import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app import media
from app.media import PipelineError, command, inspect_video, normalize_video


pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="Real FFmpeg/FFprobe required")


def ffmpeg(*args):
    return subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *map(str, args)], capture_output=True, check=True, timeout=30)


def synthetic(path: Path, *, audio=False, size="96x64", codec=None, extra=()):
    codecs = {".mov": "mpeg4", ".mp4": "libx264", ".avi": "mpeg4", ".mkv": "ffv1", ".webm": "libvpx-vp9"}
    args = ["-f", "lavfi", "-i", f"testsrc=size={size}:rate=10"]
    if audio:
        args += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000"]
    args += ["-t", "1.3", "-c:v", codec or codecs[path.suffix], "-threads", "2"]
    if audio:
        args += ["-c:a", "libopus" if path.suffix == ".webm" else "pcm_s16le" if path.suffix == ".avi" else "aac"]
    args += list(extra)
    ffmpeg(*args, path)
    return path


def timestamps(path):
    data = json.loads(subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames",
        "-show_entries", "frame=best_effort_timestamp_time", "-of", "json", str(path),
    ], check=True, capture_output=True, timeout=10).stdout)
    return [float(frame["best_effort_timestamp_time"]) for frame in data["frames"]]


def normalize(source, output, **kwargs):
    async def run():
        info = await inspect_video(source)
        return info, await normalize_video(source, output, info, timeout=20, max_bytes=2 * 1024 * 1024, **kwargs)
    return asyncio.run(run())


@pytest.mark.parametrize("extension", ["mov", "mp4", "avi", "mkv", "webm"])
def test_all_five_containers_are_real_normalized_mp4_without_audio(tmp_path, extension):
    source = synthetic(tmp_path / f"source.{extension}", audio=True)
    output = tmp_path / "video.mp4"
    before, after = normalize(source, output)
    assert before.has_audio
    assert after.codec == "h264"
    assert after.pixel_format == "yuv420p"
    assert after.demuxer == "mov" and "mp4" in after.format_name
    assert not after.has_audio
    assert (after.width, after.height) == (96, 64)
    assert after.duration == pytest.approx(before.duration, abs=0.025)
    assert after.duration == pytest.approx(1.3, abs=0.002)
    assert after.start_time == after.video_start_time == 0
    assert timestamps(output) == pytest.approx(timestamps(source), abs=0.001)
    assert source.exists()  # Lifecycle owns original cleanup.


@pytest.mark.parametrize("payload", [b"not a video", b"\x00\x00\x00\x18ftypisomtruncated", b"#EXTM3U\nhttp://127.0.0.1:1/private.ts", b"ffconcat version 1.0\nfile '/etc/passwd'\n"])
def test_corrupt_and_disguised_playlists_rejected(tmp_path, payload):
    source = tmp_path / "disguised.mp4"
    source.write_bytes(payload)
    with pytest.raises(PipelineError, match="повреждён|прочитать"):
        asyncio.run(inspect_video(source))


def test_content_identification_does_not_depend_on_extension(tmp_path):
    source = synthetic(tmp_path / "source.avi")
    renamed = tmp_path / "renamed.mov"
    source.rename(renamed)
    info = asyncio.run(inspect_video(renamed))
    assert info.demuxer == "avi"


def test_audio_only_container_rejected(tmp_path):
    path = tmp_path / "audio.mp4"
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=440", "-t", "0.3", "-c:a", "aac", path)
    with pytest.raises(PipelineError) as error:
        asyncio.run(inspect_video(path))
    assert error.value.code == "VIDEO_NO_VIDEO_TRACK"


def test_unknown_video_codec_rejected(tmp_path):
    source = synthetic(tmp_path / "unknown.avi")
    data = source.read_bytes()
    assert b"FMP4" in data
    source.write_bytes(data.replace(b"FMP4", b"ZZZZ"))
    with pytest.raises(PipelineError) as error:
        asyncio.run(inspect_video(source))
    assert error.value.code in {"VIDEO_CODEC_UNSUPPORTED", "VIDEO_INVALID"}


def test_duration_limit_checked_against_actual_container(tmp_path):
    source = tmp_path / "too-long.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=size=16x16:rate=1", "-t", "601", "-c:v", "libx264", "-threads", "1", source)
    with pytest.raises(PipelineError) as error:
        asyncio.run(inspect_video(source))
    assert error.value.code == "VIDEO_DURATION_INVALID"


def test_nonzero_container_origin_becomes_zero_without_changing_relative_times(tmp_path):
    source = synthetic(tmp_path / "offset.mp4", extra=["-output_ts_offset", "5"])
    output = tmp_path / "video.mp4"
    before, after = normalize(source, output)
    assert before.start_time == 5
    assert after.start_time == 0
    assert timestamps(output) == pytest.approx([time - 5 for time in timestamps(source)], abs=0.001)


@pytest.mark.parametrize("format_duration", ["1.3", "6.3"])
def test_duration_reporting_across_ffprobe_versions_does_not_add_absolute_origin(format_duration):
    assert media._duration({"start_time": "5", "duration": format_duration}, [
        {"codec_type": "video", "start_time": "5", "duration": "1.3"},
    ]) == pytest.approx(1.3)


def test_delayed_video_preserves_empty_leading_edit_and_original_timeline(tmp_path):
    video = synthetic(tmp_path / "source.mp4")
    delayed = tmp_path / "delayed.mp4"
    ffmpeg("-itsoffset", "0.5", "-i", video, "-f", "lavfi", "-i", "sine=frequency=440:duration=1.8", "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", delayed)
    info = asyncio.run(inspect_video(delayed))
    assert info.video_start_time - info.start_time > 0.4
    output = tmp_path / "video.mp4"
    result = asyncio.run(normalize_video(delayed, output, info, timeout=10, max_bytes=1_000_000))
    assert result.video_start_time == pytest.approx(0.5)
    assert result.duration_sec == pytest.approx(info.duration, abs=0.002)
    assert timestamps(output) == pytest.approx(timestamps(delayed), abs=0.001)


def test_vfr_preserves_every_presentation_timestamp_and_frame_count(tmp_path):
    source = synthetic(tmp_path / "vfr.mp4", extra=["-vf", "select='not(eq(mod(n,3),1))'", "-fps_mode", "vfr"])
    output = tmp_path / "video.mp4"
    normalize(source, output)
    before, after = timestamps(source), timestamps(output)
    assert len(set(round(b - a, 3) for a, b in zip(before, before[1:]))) > 1
    assert after == pytest.approx(before, abs=0.001)


def test_odd_resolution_is_padded_by_one_pixel_never_scaled_or_cropped(tmp_path):
    source = synthetic(tmp_path / "odd.mkv", size="95x63")
    output = tmp_path / "video.mp4"
    before, after = normalize(source, output)
    assert (before.width, before.height) == (95, 63)
    assert (after.width, after.height) == (96, 64)


def test_rotation_is_applied_to_pixels_not_lost_metadata(tmp_path):
    from PIL import Image, ImageChops, ImageStat
    from io import BytesIO
    source = synthetic(tmp_path / "source.mp4", extra=["-pix_fmt", "yuv420p"])
    rotated = tmp_path / "rotated.mov"
    ffmpeg("-i", source, "-c", "copy", "-metadata:s:v:0", "rotate=90", rotated)
    if not asyncio.run(inspect_video(rotated)).rotation:
        # FFmpeg 9 replaced metadata rotation with an explicit input option.
        ffmpeg("-display_rotation", "90", "-i", source, "-c", "copy", rotated)
    output = tmp_path / "video.mp4"
    before, after = normalize(rotated, output)
    assert abs(before.rotation) == 90
    assert (after.width, after.height) == (64, 96)
    assert after.rotation == 0
    def decoded(path):
        data = ffmpeg("-i", path, "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "pipe:1").stdout
        return Image.open(BytesIO(data)).convert("RGB")
    expected, actual = decoded(rotated), decoded(output)
    assert expected.size == actual.size
    assert max(ImageStat.Stat(ImageChops.difference(expected, actual)).mean) < 8


def test_non_square_pixel_aspect_ratio_is_preserved(tmp_path):
    source = synthetic(tmp_path / "anamorphic.mp4", extra=["-vf", "setsar=4/3"])
    before, after = normalize(source, tmp_path / "video.mp4")
    assert before.sample_aspect_ratio == after.sample_aspect_ratio == "4:3"


def test_output_quota_is_hard_and_partial_file_removed(tmp_path):
    source = synthetic(tmp_path / "source.mp4")
    info = asyncio.run(inspect_video(source))
    output = tmp_path / "video.mp4"
    with pytest.raises(PipelineError) as error:
        asyncio.run(normalize_video(source, output, info, timeout=10, max_bytes=1024))
    assert error.value.code == "VIDEO_STORAGE_LIMIT"
    assert not output.exists()


def test_runner_fsize_limit_cannot_be_exceeded_even_without_ffmpeg_fs(tmp_path):
    output = tmp_path / "bounded.bin"
    with pytest.raises(PipelineError) as error:
        asyncio.run(command(sys.executable, "-c", "import sys; open(sys.argv[1],'wb').write(b'x'*100000)", str(output), output_path=output, max_bytes=4096))
    assert error.value.code == "VIDEO_STORAGE_LIMIT"
    assert output.stat().st_size <= 4096


@pytest.mark.parametrize("cancel", [False, True])
def test_timeout_or_cancel_reaps_real_ffmpeg_and_removes_output(tmp_path, monkeypatch, cancel):
    source = synthetic(tmp_path / "source.mp4")
    info = asyncio.run(inspect_video(source))
    output = tmp_path / "video.mp4"
    children = []
    original = asyncio.create_subprocess_exec
    async def tracked(*args, **kwargs):
        process = await original(*args, **kwargs)
        children.append(process)
        return process
    monkeypatch.setattr(media.asyncio, "create_subprocess_exec", tracked)
    async def run():
        task = asyncio.create_task(normalize_video(source, output, info, timeout=10 if cancel else 0.01, max_bytes=1_000_000))
        if cancel:
            while not children:
                await asyncio.sleep(0)
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
            await task
    asyncio.run(run())
    assert children and all(child.returncode is not None for child in children)
    assert not output.exists()


def test_command_bounds_stdout_without_deadlock():
    with pytest.raises(PipelineError):
        asyncio.run(command(sys.executable, "-c", "import sys; sys.stdout.write('x'*1000000)", max_stdout=128, timeout=2))


def test_missing_ffmpeg_with_output_wrapper_is_server_dependency_error(tmp_path, monkeypatch):
    monkeypatch.setattr(media.shutil, "which", lambda _: None)
    async def unexpected_process(*args, **kwargs):
        pytest.fail("Missing executable must be detected before spawning its wrapper")
    monkeypatch.setattr(media.asyncio, "create_subprocess_exec", unexpected_process)
    with pytest.raises(PipelineError) as error:
        asyncio.run(command("ffmpeg", output_path=tmp_path / "video.mp4", max_bytes=1024))
    assert error.value.code == "FFMPEG_UNAVAILABLE"
    assert "администратору" in str(error.value)


def test_missing_libx264_encoder_is_server_dependency_error(tmp_path):
    with pytest.raises(PipelineError) as error:
        asyncio.run(command(sys.executable, "-c", "import sys; sys.stderr.write(\"Unknown encoder 'libx264'\\n\"); sys.exit(1)",
                            output_path=tmp_path / "video.mp4", max_bytes=1024, error_code="VIDEO_CONVERSION_FAILED"))
    assert error.value.code == "FFMPEG_UNAVAILABLE"
    assert "администратору" in str(error.value)


def test_input_options_disable_network_and_external_mov_references():
    for demuxer in ("mov", "avi", "matroska"):
        options = media.input_options(demuxer)
        assert options[options.index("-protocol_whitelist") + 1] == "file"
        assert options[options.index("-f") + 1] == demuxer
        if demuxer == "mov":
            assert options[options.index("-enable_drefs") + 1] == "0"
            assert options[options.index("-use_absolute_path") + 1] == "0"


@pytest.mark.parametrize("extension", ["mov", "mp4", "mkv"])
def test_aac_tail_at_30fps_does_not_reject_or_extend_video(tmp_path, extension):
    video = tmp_path / "video-only.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=96x64:rate=30", "-t", "1.3",
           "-c:v", "libx264", "-threads", "1", video)
    source = tmp_path / f"audio-tail.{extension}"
    if extension == "mkv":
        ffmpeg("-i", video, "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
               "-t", "1.3", "-c:v", "copy", "-c:a", "aac", source)
    else:
        audio = tmp_path / "audio.aac"
        ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "1.3", "-c:a", "aac", audio)
        ffmpeg("-i", video, "-i", audio, "-c", "copy", source)
    output = tmp_path / "normalized.mp4"
    before, after = normalize(source, output)
    assert 0.02 < before.duration - before.video_duration < 0.03
    assert before.video_duration == pytest.approx(1.3, abs=0.001)
    assert after.duration_sec == pytest.approx(1.3, abs=0.001)
    assert not after.has_audio
    assert len(timestamps(source)) == len(timestamps(output)) == 39
    assert timestamps(output) == pytest.approx(timestamps(source), abs=0.001)


@pytest.mark.parametrize("origin,leading", [(5, 0), (0, 0.5), (5, 0.5)])
def test_matroska_duration_tag_is_absolute_end_not_span(tmp_path, origin, leading):
    video = tmp_path / "video-only.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=96x64:rate=30", "-t", "1.3",
           "-c:v", "libx264", "-threads", "1", video)
    source = tmp_path / "timed.mkv"
    ffmpeg("-itsoffset", str(leading), "-i", video,
           "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={1.3 + leading}",
           "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-output_ts_offset", str(origin), source)
    output = tmp_path / "normalized.mp4"
    before, after = normalize(source, output)
    assert before.start_time == pytest.approx(origin, abs=0.001)
    assert before.video_start_time == pytest.approx(origin + leading, abs=0.001)
    assert before.video_duration == pytest.approx(1.3, abs=0.001)
    assert before.duration == pytest.approx(leading + 1.321, abs=0.002)
    assert after.video_start_time == pytest.approx(leading, abs=0.001)
    assert after.duration_sec == pytest.approx(leading + 1.3, abs=0.001)
    assert timestamps(output) == pytest.approx([timestamp - origin for timestamp in timestamps(source)], abs=0.001)


def test_missing_matroska_track_duration_uses_actual_packet_timestamps(tmp_path):
    source = tmp_path / "no-duration-tags.mkv"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=96x64:rate=30",
           "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "1.3",
           "-c:v", "libx264", "-threads", "1", "-c:a", "aac", "-write_crc32", "0", source)
    data = source.read_bytes()
    assert b"DURATION" in data
    # Same-length, valid tag rename; CRC writing was disabled for this fixture.
    source.write_bytes(data.replace(b"DURATION", b"IGNORED!"))
    before, after = normalize(source, tmp_path / "normalized.mp4")
    assert before.duration == pytest.approx(1.321, abs=0.001)
    assert before.video_duration == pytest.approx(1.3, abs=0.001)
    assert after.duration_sec == pytest.approx(1.3, abs=0.001)


def test_packet_fallback_rejects_unknown_final_duration_instead_of_guessing_fps(tmp_path, monkeypatch):
    async def incomplete_packets(*args, **kwargs):
        return b"pts_time=0.000000|duration_time=0.033333\npts_time=0.033333|duration_time=N/A\n"
    monkeypatch.setattr(media, "command", incomplete_packets)
    with pytest.raises(PipelineError) as error:
        asyncio.run(media._packet_video_end(tmp_path / "fixture.mkv", "matroska", 0, 0, timeout=1))
    assert error.value.code == "VIDEO_TIMELINE_UNSUPPORTED"


def test_container_duration_limit_includes_long_audio_tail(tmp_path):
    source = tmp_path / "long-audio.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=size=16x16:rate=1:duration=1",
           "-f", "lavfi", "-i", "anullsrc=sample_rate=8000:channel_layout=mono:duration=601",
           "-c:v", "libx264", "-threads", "1", "-c:a", "aac", "-b:a", "8k", source)
    with pytest.raises(PipelineError) as error:
        asyncio.run(inspect_video(source))
    assert error.value.code == "VIDEO_DURATION_INVALID"
