import asyncio
import base64
import json
import math
from pathlib import Path
from time import monotonic
from collections.abc import Callable

import httpx
from pydantic import ValidationError

from .config import Settings
from .models import AnalysisResult, EvidenceFrame, Observations, Rule, RuleCatalog, Violation

DEMO_SCENARIOS = (
    "violation", "no_violation", "multiple_events", "three_frames", "long_text",
    "demo_rule", "slow", "ml_error", "invalid_ml_response",
)
MAX_ML_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_CATALOG_BYTES = 4 * 1024 * 1024
ML_REQUEST_TIMEOUT_SECONDS = 120
DEMO_RULES_PATH = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "demo-rules.json"


class PipelineError(ValueError):
    """Safe, stable error contract; never expose ML response bodies or local paths."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def load_rules(path: Path) -> list[Rule]:
    try:
        if path.stat().st_size > MAX_CATALOG_BYTES:
            raise ValueError("Catalog is too large")
        catalog = RuleCatalog.model_validate_json(path.read_text())
        if any(rule.is_demo or rule.id.startswith("demo:") for rule in catalog.rules):
            raise ValueError("Demo rules are not production rules")
    except (OSError, ValueError) as error:
        raise PipelineError("RULES_INVALID", "Каталог правил недоступен или содержит некорректные источники. Проверьте каталог.") from error
    if not catalog.rules:
        raise PipelineError("RULES_EMPTY", "Каталог правил пуст. Добавьте проверенные правила перед запуском ML.")
    return catalog.rules


async def command(*args: str, timeout: float = 20) -> bytes:
    try:
        process = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    except FileNotFoundError as error:
        raise PipelineError("FFMPEG_UNAVAILABLE", "FFmpeg недоступен. Обратитесь к администратору сервиса.") from error
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise PipelineError("VIDEO_INVALID", "Не удалось прочитать видео. Загрузите корректный файл MOV или MP4.")
    return stdout


async def probe(path: Path) -> float:
    raw = await command("ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-f", "mov", "-show_format", "-show_streams", "-of", "json", str(path))
    try:
        info = json.loads(raw)
        if not any(stream.get("codec_type") == "video" for stream in info.get("streams", [])):
            raise PipelineError("VIDEO_INVALID", "В файле нет видеодорожки. Выберите другую запись.")
        duration = float(info.get("format", {}).get("duration", 0))
    except (TypeError, ValueError, KeyError) as error:
        if isinstance(error, PipelineError):
            raise
        raise PipelineError("VIDEO_INVALID", "Не удалось определить длительность видео.") from error
    if not math.isfinite(duration) or not 0 < duration <= 600:
        raise PipelineError("VIDEO_DURATION_INVALID", "Нужна запись длительностью от 1 кадра до 10 минут.")
    return duration


async def frame_at(path: Path, timestamp: float) -> EvidenceFrame:
    jpeg = await command(
        "ffmpeg", "-v", "error", "-ss", str(timestamp), "-protocol_whitelist", "file,pipe", "-f", "mov", "-i", str(path),
        "-map", "0:v:0", "-frames:v", "1", "-an", "-vf", "scale='min(960,iw)':-2",
        "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
    )
    try:
        return EvidenceFrame(timestamp_sec=timestamp, image_base64=base64.b64encode(jpeg).decode())
    except ValidationError as error:
        raise PipelineError("FRAME_INVALID", "Не удалось получить корректный JPEG-кадр из видео.") from error


async def _request_json(client: httpx.AsyncClient, url: str, stage: str, **kwargs) -> object:
    try:
        # Bound both inactivity and total request time; backend bounds the whole job.
        async with asyncio.timeout(ML_REQUEST_TIMEOUT_SECONDS):
            async with client.stream("POST", url, **kwargs) as response:
                response.raise_for_status()
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > MAX_ML_RESPONSE_BYTES:
                    raise PipelineError(f"{stage.upper()}_INVALID_RESPONSE", f"{stage.upper()} вернул слишком большой ответ.")
                data = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65_536):
                    if len(data) + len(chunk) > MAX_ML_RESPONSE_BYTES:
                        raise PipelineError(f"{stage.upper()}_INVALID_RESPONSE", f"{stage.upper()} вернул слишком большой ответ.")
                    data.extend(chunk)
                return json.loads(data)
    except PipelineError:
        raise
    except (httpx.TimeoutException, TimeoutError) as error:
        raise PipelineError(f"{stage.upper()}_TIMEOUT", f"{stage.upper()} не ответил вовремя. Попробуйте повторить проверку.") from error
    except httpx.HTTPStatusError as error:
        raise PipelineError(f"{stage.upper()}_HTTP_ERROR", f"{stage.upper()} завершил запрос с ошибкой. Анализ не выполнен.") from error
    except httpx.RequestError as error:
        raise PipelineError(f"{stage.upper()}_UNAVAILABLE", f"{stage.upper()} недоступен. Попробуйте повторить проверку позже.") from error
    except (ValueError, RecursionError) as error:
        raise PipelineError(f"{stage.upper()}_INVALID_RESPONSE", f"{stage.upper()} вернул пустой или некорректный JSON.") from error


def _validate_observations(payload: object, duration: float) -> Observations:
    try:
        observations = Observations.model_validate(payload)
    except ValidationError as error:
        raise PipelineError("ML1_INVALID_RESPONSE", "ML1 вернул ответ, не соответствующий контракту версии 1.0.") from error
    if any(event.start_sec >= duration or event.end_sec > duration or
           any(frame.timestamp_sec >= duration for frame in event.evidence_frames)
           for event in observations.events):
        raise PipelineError("ML1_INVALID_TIMECODE", "ML1 вернул таймкод за пределами видео.")
    return observations


def _validate_result(payload: object, duration: float, rules: list[Rule]) -> AnalysisResult:
    try:
        result = AnalysisResult.model_validate(payload)
    except ValidationError as error:
        raise PipelineError("ML2_INVALID_RESPONSE", "ML2 вернул ответ, не соответствующий контракту.") from error
    catalog = {rule.id: rule for rule in rules}
    for violation in result.violations:
        if violation.rule_id not in catalog:
            raise PipelineError("ML2_UNKNOWN_RULE", "ML2 вернул событие без проверенного правила из каталога.")
        if violation.timecode_sec >= duration or any(frame.timestamp_sec >= duration for frame in violation.evidence_frames):
            raise PipelineError("ML2_INVALID_TIMECODE", "ML2 вернул таймкод за пределами видео.")
        trusted_rule = catalog[violation.rule_id]
        if violation.rule is not None and violation.rule != trusted_rule:
            raise PipelineError("ML2_RULE_MISMATCH", "ML2 вернул источник правила, не совпадающий с каталогом.")
        violation.rule = trusted_rule
    return result


async def _demo(path: Path, duration: float, scenario: str, on_stage: Callable[[str], None]) -> AnalysisResult:
    if scenario not in DEMO_SCENARIOS:
        raise PipelineError("DEMO_SCENARIO_INVALID", "Неизвестный тестовый сценарий.")
    await asyncio.sleep(12 if scenario == "slow" else 0.6)
    if scenario == "ml_error":
        raise PipelineError("ML1_UNAVAILABLE", "Тестовый сценарий: ML1 недоступен. Это демонстрационная ошибка.")
    if scenario == "invalid_ml_response":
        _validate_observations({}, duration)
    on_stage("matching")
    await asyncio.sleep(0.6)
    if scenario == "no_violation":
        return AnalysisResult(verdict="no_violation")
    fractions = (0.25, 0.5, 0.75) if scenario == "multiple_events" else (0.5,)
    violations = []
    for index, fraction in enumerate(fractions):
        timestamp = duration * fraction
        frame_times = (duration * 0.4, timestamp, duration * 0.6) if scenario == "three_frames" else (timestamp,)
        frames = [await frame_at(path, time) for time in frame_times]
        title = "Демонстрационное событие" if len(fractions) == 1 else f"Демонстрационное событие {index + 1}"
        description = ("Тестовая карточка для проверки интерфейса. Кадр взят из загруженного видео; "
                       "событие сгенерировано заглушкой и не является выводом о действиях на записи.")
        if scenario == "long_text":
            title = "Демонстрационное событие с длинным названием для проверки переноса текста и доступности карточек на узком экране"
            description += (" Этот искусственный пример проверяет читаемость длинных объяснений, "
                            "переносы строк, раскрытие деталей и сохранение доступа к доказательствам. "
                            "Он не описывает реальное нарушение и не содержит нормативного заключения.") * 6
        rule = None
        if scenario == "demo_rule":
            catalog = RuleCatalog.model_validate_json(DEMO_RULES_PATH.read_text())
            rule = catalog.rules[0]
        violations.append(Violation(type=title, timecode_sec=timestamp, description=description,
                                    evidence_frames=frames, rule_id=rule.id if rule else None, rule=rule))
    return AnalysisResult(verdict="violation", violations=violations)


async def analyze(
    path: Path, duration: float, settings: Settings, scenario: str,
    on_stage: Callable[[str], None], *, on_timing: Callable[[str, float], None] | None = None,
) -> AnalysisResult:
    started = monotonic()
    active_stage = "analyzing"

    def stage(name: str):
        nonlocal started, active_stage
        if on_timing and name != active_stage:
            on_timing(active_stage, round(monotonic() - started, 6))
        started, active_stage = monotonic(), name
        on_stage(name)

    stage("analyzing")
    try:
        if not math.isfinite(duration) or duration <= 0:
            raise PipelineError("VIDEO_DURATION_INVALID", "Не удалось определить длительность видео.")
        if settings.mode == "demo":
            return await _demo(path, duration, scenario, stage)
        rules = load_rules(settings.rules_path)
        async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=5, read=90, write=30, pool=5), trust_env=False, follow_redirects=False) as client:
            with path.open("rb") as video:
                first = await _request_json(client, f"{settings.ml1_url.rstrip('/')}/analyze", "ml1",
                                            files={"file": ("video.mov", video, "video/quicktime")})
            observations = _validate_observations(first, duration)
            stage("matching")
            second = await _request_json(client, f"{settings.ml2_url.rstrip('/')}/match", "ml2", json={
                **observations.model_dump(), "duration_sec": duration,
                "rules": [rule.model_dump() for rule in rules],
            })
            return _validate_result(second, duration, rules)
    finally:
        if on_timing:
            on_timing(active_stage, round(monotonic() - started, 6))
