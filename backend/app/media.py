"""Local, bounded video inspection and normalization; no model implementation."""

import asyncio
import importlib.util
import json
import math
import os
import signal
import shutil
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from time import monotonic


class PipelineError(ValueError):
    """Safe error contract; raw FFmpeg output and local paths stay private."""

    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


@dataclass(frozen=True)
class VideoInfo:
    duration: float
    width: int
    height: int
    codec: str
    pixel_format: str
    format_name: str
    start_time: float
    video_start_time: float
    stream_index: int
    frame_count: int | None
    rotation: float
    sample_aspect_ratio: str
    has_audio: bool
    frame_rate: float
    demuxer: str
    time_base: str
    timeline_origin: float | None = None
    video_duration: float | None = None

    @property
    def duration_sec(self) -> float:
        # A normalized file may have an empty leading edit. Its first frame PTS
        # is kept, while duration_sec remains measured from the original zero.
        return self.duration if self.timeline_origin is None else self.start_time + self.duration - self.timeline_origin


def _container(path: Path) -> str:
    try:
        with path.open("rb") as file:
            header = file.read(16)
    except OSError as error:
        raise PipelineError("VIDEO_INVALID", "Не удалось прочитать загруженное видео.") from error
    if header[:4] == b"RIFF" and header[8:12] == b"AVI ":
        return "avi"
    if header[:4] == b"\x1aE\xdf\xa3":
        return "matroska"
    if header[4:8] in (b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip", b"pnot"):
        return "mov"
    raise PipelineError("VIDEO_INVALID", "Файл повреждён или его содержимое не является видео MOV, MP4, AVI, MKV или WEBM.")


def input_options(demuxer: str) -> list[str]:
    # Force a content-identified demuxer: a renamed HLS/concat playlist cannot
    # cause nested requests. MOV aliases/references are explicitly disabled.
    options = ["-protocol_whitelist", "file", "-format_whitelist", "mov,avi,matroska,webm", "-f", demuxer]
    if demuxer == "mov":
        options += ["-enable_drefs", "0", "-use_absolute_path", "0"]
    return options


async def command(
    *args: str, timeout: float = 20, max_stdout: int = 256 * 1024,
    output_path: Path | None = None, max_bytes: int | None = None,
    error_code: str = "VIDEO_INVALID",
) -> bytes:
    """Drain pipes with bounded memory; kill and reap on every failure/cancel.

    RLIMIT_FSIZE is applied in an exec wrapper (not preexec_fn in a threaded
    server). FFmpeg -fs alone may overshoot; the OS limit is the hard bound.
    Windows instead polls the output size, then kills/reaps and removes an
    over-quota file. Polling can overshoot between checks; it is not an OS cap.
    """
    if shutil.which(args[0]) is None:
        raise PipelineError("FFMPEG_UNAVAILABLE", "FFmpeg недоступен. Обратитесь к администратору сервиса.")
    poll_output = (os.name == "nt" or not hasattr(signal, "SIGXFSZ")
                   or importlib.util.find_spec("resource") is None)
    quota_exceeded = False
    invocation = list(args)
    if output_path is not None:
        if max_bytes is None or max_bytes < 1:
            raise PipelineError("VIDEO_STORAGE_LIMIT", "Недостаточно места для подготовки видео.")
        if not poll_output:
            invocation = [sys.executable, "-c",
                          "import os,resource,sys; n=int(sys.argv[1]); resource.setrlimit(resource.RLIMIT_FSIZE,(n,n)); os.execvp(sys.argv[2],sys.argv[2:])",
                          str(max_bytes), *invocation]
    try:
        process = await asyncio.create_subprocess_exec(
            *invocation, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as error:
        raise PipelineError("FFMPEG_UNAVAILABLE", "FFmpeg недоступен. Обратитесь к администратору сервиса.") from error

    async def read_stdout():
        data = bytearray()
        while chunk := await process.stdout.read(64 * 1024):
            if len(data) + len(chunk) > max_stdout:
                raise PipelineError(error_code, "Видео содержит слишком большой объём служебных данных.")
            data.extend(chunk)
        return bytes(data)

    async def read_stderr():
        tail = b""
        while chunk := await process.stderr.read(16 * 1024):
            tail = (tail + chunk)[-8192:]
        return tail

    tasks = [asyncio.create_task(read_stdout()), asyncio.create_task(read_stderr()), asyncio.create_task(process.wait())]
    async def watch_output():
        nonlocal quota_exceeded
        while True:
            try:
                size = output_path.stat().st_size
            except FileNotFoundError:
                size = 0
            if size >= max_bytes:
                quota_exceeded = True
                raise PipelineError("VIDEO_STORAGE_LIMIT", "Подготовленное видео превышает доступный лимит диска. Выберите файл меньшего размера или разрешения.")
            # Check the file before checking exit: fast writers may finish
            # between polls, and their final output must still be rejected.
            if process.returncode is not None:
                return
            await asyncio.sleep(0.01)

    monitor = asyncio.create_task(watch_output()) if poll_output and output_path is not None else None
    if monitor is not None:
        tasks.append(monitor)
    try:
        if monitor is None:
            stdout, stderr, returncode = await asyncio.wait_for(asyncio.gather(*tasks), timeout=max(0, timeout))
        else:
            stdout, stderr, returncode, _ = await asyncio.wait_for(asyncio.gather(*tasks), timeout=max(0, timeout))
        at_limit = output_path is not None and output_path.exists() and output_path.stat().st_size >= max_bytes
        if at_limit or (not poll_output and returncode == -signal.SIGXFSZ) or b"no space left on device" in stderr.lower():
            quota_exceeded = poll_output and output_path is not None
            raise PipelineError("VIDEO_STORAGE_LIMIT", "Подготовленное видео превышает доступный лимит диска. Выберите файл меньшего размера или разрешения.")
        if returncode or stderr:
            lower = stderr.lower()
            if b"libx264" in lower and (b"unknown encoder" in lower or b"encoder not found" in lower):
                raise PipelineError("FFMPEG_UNAVAILABLE", "На сервере недоступен кодировщик H.264 (libx264). Обратитесь к администратору сервиса.")
            if b"unknown decoder" in lower or b"decoder not found" in lower or b"decoding requested, but no decoder" in lower or b"unsupported codec" in lower:
                raise PipelineError("VIDEO_CODEC_UNSUPPORTED", "Кодек видео не поддерживается сервером. Экспортируйте запись с другим видеокодеком.")
            message = ("Не удалось преобразовать видео. Файл повреждён или его кодек не поддерживается."
                       if error_code == "VIDEO_CONVERSION_FAILED" else "Не удалось прочитать видео. Файл повреждён или его кодек не поддерживается.")
            raise PipelineError(error_code, message)
        return stdout
    finally:
        async def reap():
            if process.returncode is None:
                process.kill()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            # The child is stopped, so remaining pipe data is bounded by pipe
            # buffers. Draining avoids a paused pipe holding wait() open.
            await process.communicate()
            await process.wait()

        cleanup = asyncio.create_task(reap())
        cancelled = False
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                cancelled = True
        await cleanup
        if quota_exceeded:
            output_path.unlink(missing_ok=True)
        if cancelled:
            raise asyncio.CancelledError


def _number(value, default=0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _rate(value: str | None) -> float:
    try:
        numerator, denominator = (value or "0/1").split("/")
        return _number(numerator) / _number(denominator)
    except (ValueError, ZeroDivisionError):
        return 0.0


def _stream_end(stream: dict, origin: float, demuxer: str) -> float | None:
    start = _number(stream.get("start_time"), origin)
    duration = _number(stream.get("duration"))
    if duration > 0:
        return start + duration
    # Matroska's DURATION tag is a presentation END timestamp, not a span.
    # A clip starting at 5s and lasting 1.3s carries DURATION=00:00:06.300.
    if demuxer == "matroska":
        try:
            hours, minutes, seconds = stream.get("tags", {}).get("DURATION", "").split(":")
            if not hours.isdigit() or not minutes.isdigit() or not 0 <= int(minutes) < 60:
                return None
            second = float(seconds)
            if not math.isfinite(second) or not 0 <= second < 60:
                return None
            end = int(hours) * 3600 + int(minutes) * 60 + second
            return end if end > start else None
        except (TypeError, ValueError):
            return None
    return None


def _duration(container: dict, streams: list[dict], demuxer: str = "") -> float:
    # MOV duration reporting around empty edits differs between FFmpeg releases.
    # When every A/V stream has a duration, its presentation end is unambiguous.
    timed = [stream for stream in streams if stream.get("codec_type") in {"video", "audio"}
             and not stream.get("disposition", {}).get("attached_pic")]
    start = _number(container.get("start_time"))
    ends = [_stream_end(stream, start, demuxer) for stream in timed]
    if ends and all(end is not None for end in ends):
        return max(ends) - start
    return _number(container.get("duration"))


async def _packet_video_end(path: Path, demuxer: str, stream_index: int, video_start: float, *, timeout: float) -> float:
    """Fallback for containers without stream durations; no FPS-based guesses."""
    raw = await command(
        "ffprobe", "-v", "error", *input_options(demuxer),
        "-select_streams", str(stream_index), "-show_packets",
        "-show_entries", "packet=pts_time,duration_time:packet_side_data=",
        "-of", "compact=p=0:nk=0", str(path.resolve()), timeout=timeout,
        max_stdout=4 * 1024 * 1024,
    )
    first, last, final_duration = math.inf, -math.inf, 0.0
    for line in raw.decode("utf-8").splitlines():
        fields = dict(field.split("=", 1) for field in line.split("|") if "=" in field)
        pts = _number(fields.get("pts_time"), math.nan)
        if not math.isfinite(pts):
            raise PipelineError("VIDEO_TIMELINE_UNSUPPORTED", "Не удалось подтвердить таймкоды видеодорожки. Экспортируйте запись заново.")
        first = min(first, pts)
        if pts > last:
            last, final_duration = pts, _number(fields.get("duration_time"))
    if not math.isfinite(last) or final_duration <= 0 or abs(first - video_start) > 0.002:
        raise PipelineError("VIDEO_TIMELINE_UNSUPPORTED", "Не удалось подтвердить длительность видеодорожки. Экспортируйте запись заново.")
    return last + final_duration


async def inspect_video(path: Path, *, timeout: float = 20) -> VideoInfo:
    started = monotonic()
    demuxer = _container(path)
    raw = await command(
        "ffprobe", "-v", "error", *input_options(demuxer),
        "-show_entries", "format=format_name,start_time,duration:stream=index,codec_type,codec_name,pix_fmt,width,height,start_time,duration,nb_frames,sample_aspect_ratio,avg_frame_rate,time_base:stream_tags=DURATION:stream_disposition=attached_pic:stream_side_data=rotation",
        "-of", "json", str(path.resolve()), timeout=timeout,
    )
    try:
        payload = json.loads(raw)
        streams = payload["streams"]
        video = next((stream for stream in streams if stream.get("codec_type") == "video" and not stream.get("disposition", {}).get("attached_pic")), None)
        if video is None:
            raise PipelineError("VIDEO_NO_VIDEO_TRACK", "В файле нет видеодорожки. Выберите запись с изображением.")
        codec = video.get("codec_name", "")
        if not codec or codec == "unknown":
            raise PipelineError("VIDEO_CODEC_UNSUPPORTED", "Кодек видео не поддерживается сервером. Экспортируйте запись с другим видеокодеком.")
        container = payload["format"]
        duration = _duration(container, streams, demuxer)
        if not 0 < duration <= 600:
            raise PipelineError("VIDEO_DURATION_INVALID", "Нужна запись длительностью от 1 кадра до 10 минут.")
        width, height = int(video["width"]), int(video["height"])
        if width <= 0 or height <= 0:
            raise PipelineError("VIDEO_INVALID", "Не удалось определить размер изображения в видео.")
        rotation = next((_number(side["rotation"]) for side in video.get("side_data_list", []) if "rotation" in side), 0.0)
        origin = _number(container.get("start_time"))
        video_start = _number(video.get("start_time"), origin)
        video_end = _stream_end(video, origin, demuxer)
        if video_end is None:
            video_end = await _packet_video_end(path, demuxer, int(video["index"]), video_start,
                                                timeout=max(0, timeout - (monotonic() - started)))
        if not 0 < video_end - origin <= 600 or video_end <= video_start:
            raise PipelineError("VIDEO_DURATION_INVALID", "Нужна запись длительностью от 1 кадра до 10 минут.")
        return VideoInfo(
            duration=duration, width=width, height=height, codec=codec, pixel_format=video.get("pix_fmt", ""),
            format_name=container["format_name"], start_time=_number(container.get("start_time")),
            video_start_time=_number(video.get("start_time"), _number(container.get("start_time"))),
            stream_index=int(video["index"]), frame_count=int(video["nb_frames"]) if str(video.get("nb_frames", "")).isdigit() else None,
            rotation=rotation, sample_aspect_ratio=video.get("sample_aspect_ratio", "1:1"),
            has_audio=any(stream.get("codec_type") == "audio" for stream in streams),
            frame_rate=_rate(video.get("avg_frame_rate")), demuxer=demuxer,
            time_base=video.get("time_base", "1/1000000"),
            video_duration=video_end - video_start,
        )
    except (ValueError, TypeError, KeyError) as error:
        if isinstance(error, PipelineError):
            raise
        raise PipelineError("VIDEO_INVALID", "Не удалось определить параметры видео.") from error


async def normalize_video(source: Path, output: Path, info: VideoInfo, *, timeout: float, max_bytes: int) -> VideoInfo:
    """Preserve presentation timestamps, autorotate pixels and retain resolution.

    Empty leading edits are retained as positive frame timestamps, not filled
    with invented frames or shifted to zero. Absolute container origin is zeroed.
    """
    if source.resolve() == output.resolve():
        raise ValueError("Source and normalized output must be different files")
    if output.exists():
        raise ValueError("Normalized output must not overwrite an existing file")
    leading_offset = info.video_start_time - info.start_time
    if leading_offset < -0.002:
        raise PipelineError("VIDEO_TIMELINE_UNSUPPORTED", "У видеодорожки некорректное начало временной шкалы. Экспортируйте запись заново для сохранения точных таймкодов.")
    if abs(info.rotation / 90 - round(info.rotation / 90)) > 0.001:
        raise PipelineError("VIDEO_ORIENTATION_UNSUPPORTED", "У записи нестандартный угол поворота. Экспортируйте видео с применённой ориентацией изображения.")
    if info.video_duration is None:
        raise PipelineError("VIDEO_TIMELINE_UNSUPPORTED", "Не удалось подтвердить длительность видеодорожки. Экспортируйте запись заново.")
    try:
        async with asyncio.timeout(timeout):
            await command(
                "ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-xerror", "-n",
                "-copyts", "-start_at_zero", "-threads", "2", "-filter_threads", "1",
                "-err_detect", "explode", *input_options(info.demuxer), "-i", str(source.resolve()),
                "-map", f"0:{info.stream_index}", "-map_metadata", "-1", "-map_chapters", "-1",
                "-an", "-sn", "-dn", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                "-threads", "2", "-fps_mode", "passthrough", "-enc_time_base", info.time_base.replace("/", ":"),
                "-metadata:s:v:0", "rotate=0", "-movflags", "+faststart", "-fs", str(max_bytes),
                "-f", "mp4", str(output.resolve()), timeout=timeout,
                output_path=output, max_bytes=max_bytes, error_code="VIDEO_CONVERSION_FAILED",
            )
            normalized = await inspect_video(output, timeout=timeout)
            expected_width, expected_height = info.width, info.height
            if round(info.rotation / 90) % 2:
                expected_width, expected_height = expected_height, expected_width
            expected_width += expected_width % 2
            expected_height += expected_height % 2
            # One timestamp tick/container rounding is permitted; an entire
            # missing frame is not. Frame count is also checked where available.
            tolerance = max(0.002, min(0.05, 0.25 / info.frame_rate)) if info.frame_rate else 0.05
            if (normalized.codec != "h264" or normalized.pixel_format != "yuv420p" or normalized.has_audio
                or normalized.demuxer != "mov" or abs(normalized.start_time - leading_offset) > 0.002
                or abs(normalized.video_start_time - leading_offset) > 0.002 or abs(normalized.rotation) > 0.001
                or (normalized.width, normalized.height) != (expected_width, expected_height)
                or normalized.video_duration is None
                or abs(normalized.start_time + normalized.video_duration - (leading_offset + info.video_duration)) > tolerance
                or (info.frame_count is not None and normalized.frame_count != info.frame_count)):
                raise PipelineError("VIDEO_CONVERSION_FAILED", "Не удалось подготовить видео без изменения длительности, таймкодов или изображения. Попробуйте экспортировать исходную запись заново.")
            return replace(normalized, timeline_origin=0.0)
    except BaseException:
        output.unlink(missing_ok=True)
        raise
