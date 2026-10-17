import asyncio
import base64
import json
from pathlib import Path
from collections.abc import Callable

import httpx

from .config import Settings
from .models import AnalysisResult, EvidenceFrame, Observations, Rule, Violation


async def command(*args: str, timeout: float = 20) -> bytes:
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise ValueError("Не удалось прочитать видео. Загрузите корректный файл MOV или MP4.")
    return stdout


async def probe(path: Path) -> float:
    raw = await command("ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-f", "mov", "-show_format", "-show_streams", "-of", "json", str(path))
    info = json.loads(raw)
    if not any(stream.get("codec_type") == "video" for stream in info.get("streams", [])):
        raise ValueError("В файле нет видеодорожки. Выберите другую запись.")
    duration = float(info.get("format", {}).get("duration", 0))
    if not 0 < duration <= 600:
        raise ValueError("Нужна запись длительностью от 1 кадра до 10 минут.")
    return duration


async def frame_at(path: Path, timestamp: float) -> EvidenceFrame:
    jpeg = await command(
        "ffmpeg", "-v", "error", "-ss", str(timestamp), "-protocol_whitelist", "file,pipe", "-f", "mov", "-i", str(path),
        "-map", "0:v:0", "-frames:v", "1", "-an", "-vf", "scale='min(960,iw)':-2",
        "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
    )
    return EvidenceFrame(timestamp_sec=timestamp, image_base64=base64.b64encode(jpeg).decode())


async def analyze(
    path: Path, duration: float, settings: Settings, scenario: str,
    on_stage: Callable[[str], None],
) -> AnalysisResult:
    on_stage("analyzing")
    if settings.mode == "demo":
        await asyncio.sleep(0.6)
        on_stage("matching")
        await asyncio.sleep(0.6)
        if scenario == "no_violation":
            return AnalysisResult(verdict="no_violation")
        timestamp = round(min(12.4, duration / 2), 3)
        frame = await frame_at(path, timestamp)
        return AnalysisResult(verdict="violation", violations=[Violation(
            type="Демонстрационное событие",
            timecode_sec=timestamp,
            description="Тестовая карточка для проверки интерфейса. Кадр взят из загруженного видео; "
                        "событие сгенерировано заглушкой и не является выводом о действиях на записи.",
            evidence_frames=[frame],
        )])

    rules = [Rule.model_validate(item) for item in json.loads(settings.rules_path.read_text())["rules"]]
    if not rules:
        raise ValueError("Каталог правил пуст. Добавьте проверенные правила перед запуском ML.")
    async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
        with path.open("rb") as video:
            first = await client.post(f"{settings.ml1_url.rstrip('/')}/analyze", files={"file": ("video.mov", video, "video/quicktime")})
        first.raise_for_status()
        observations = Observations.model_validate(first.json())
        if any(event.end_sec > duration or any(frame.timestamp_sec > duration for frame in event.evidence_frames) for event in observations.events):
            raise ValueError("ML1 вернул таймкод за пределами видео.")
        on_stage("matching")
        second = await client.post(f"{settings.ml2_url.rstrip('/')}/match", json={
            **observations.model_dump(), "duration_sec": duration,
            "rules": [rule.model_dump() for rule in rules],
        })
        second.raise_for_status()
        result = AnalysisResult.model_validate(second.json())
    catalog = {rule.id: rule for rule in rules}
    for violation in result.violations:
        if violation.rule_id not in catalog:
            raise ValueError("ML2 вернул событие без проверенного правила из каталога.")
        if violation.timecode_sec > duration or any(frame.timestamp_sec > duration for frame in violation.evidence_frames):
            raise ValueError("ML2 вернул таймкод за пределами видео.")
        violation.rule = catalog[violation.rule_id]
    return result
