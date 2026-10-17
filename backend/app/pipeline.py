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
from .media import PipelineError, command, input_options, inspect_video
from .models import AnalysisResult, EvidenceFrame, Observations, Rule, RuleCatalog, Violation

DEMO_SCENARIOS = (
    "violation", "no_violation", "multiple_events", "three_frames", "long_text",
    "demo_rule", "slow", "ml_error", "invalid_ml_response",
    "strong_evidence", "needs_review", "mixed_assessments",
)
MAX_ML_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_CATALOG_BYTES = 4 * 1024 * 1024
ML_REQUEST_TIMEOUT_SECONDS = 120
DEMO_RULES_PATH = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "demo-rules.json"


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


async def probe(path: Path) -> float:
    return (await inspect_video(path)).duration


async def frame_at(path: Path, timestamp: float) -> EvidenceFrame:
    jpeg = await command(
        "ffmpeg", "-nostdin", "-v", "error", "-seek_timestamp", "1", "-ss", str(timestamp), *input_options("mov"), "-i", str(path.resolve()),
        "-map", "0:v:0", "-frames:v", "1", "-an", "-vf", "scale='min(960,iw)':-2",
        "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
        max_stdout=4 * 1024 * 1024,
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
                if (response.headers.get("x-analysis-status", "").lower() in {"partial", "incomplete"}
                    or response.headers.get("x-analysis-complete", "").lower() in {"false", "0", "no"}):
                    raise PipelineError(f"{stage.upper()}_INCOMPLETE", f"{stage.upper()} сообщил о неполном анализе. Результат не определён.")
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
        if not isinstance(payload, dict) or "violations" not in payload:
            raise ValueError("ML2 must explicitly return violations, including an empty list")
        result = AnalysisResult.model_validate(payload)
    except ValueError as error:
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
        return AnalysisResult(verdict="no_violation", violations=[])
    video_start = (await inspect_video(path)).video_start_time
    fractions = ((0.2, 0.4, 0.6, 0.8) if scenario == "mixed_assessments" else
                 (0.25, 0.5, 0.75) if scenario == "multiple_events" else (0.5,))
    violations = []
    for index, fraction in enumerate(fractions):
        timestamp = video_start + (duration - video_start) * fraction
        frame_times = (video_start + (duration - video_start) * 0.4, timestamp, video_start + (duration - video_start) * 0.6) if scenario == "three_frames" else (timestamp,)
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
        assessment = "strong_evidence" if scenario == "strong_evidence" or (scenario == "mixed_assessments" and index % 2 == 0) else "needs_review"
        reason = ("ВЫМЫШЛЕННАЯ demo-оценка: заглушка показывает убедительные визуальные признаки и тестовое правило. "
                  "Это пример оформления, а не оценка действий на записи; решение принимает человек.") if assessment == "strong_evidence" else (
                  "ВЫМЫШЛЕННАЯ demo-оценка: заглушка показывает неоднозначное событие, требующее уточнения человеком. "
                  "Это пример оформления, а не вывод модели о записи.")
        if scenario == "demo_rule" or assessment == "strong_evidence":
            catalog = RuleCatalog.model_validate_json(DEMO_RULES_PATH.read_text())
            rule = catalog.rules[0]
        violations.append(Violation(type=title, timecode_sec=timestamp, description=description,
                                    evidence_frames=frames, rule_id=rule.id if rule else None, rule=rule,
                                    assessment=assessment, assessment_reason=reason))
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
                                            files={"file": ("video.mp4", video, "video/mp4")})
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
