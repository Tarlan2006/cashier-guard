import asyncio
import hmac
import hashlib
import json
import re
import logging
import shutil
import sqlite3
import tempfile
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import media, pipeline
from .config import ROOT, Settings
from .middleware import UploadBudgetMiddleware
from .models import JobResponse, HistoryPage, HumanReview, ReviewUpdate, AnalyticsResponse, ReviewedEvent, TagsUpdate, ReviewQueuePage, ReviewQueueOptions, ReviewLogPage
from .readiness import inspect_readiness
from .store import JobStore
from .reports import build_report

logger = logging.getLogger(__name__)


def iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


@dataclass
class RunningJob:
    job: JobResponse
    path: Path
    scenario: str
    started: float
    queued: float
    deadline: float
    stage_started: float
    work_task: asyncio.Task | None = None
    timer: asyncio.Task | None = None

    @property
    def normalized_path(self) -> Path:
        return self.path.with_suffix(".normalized.mp4")


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    active: dict[str, RunningJob] = {}
    # Bounded by admitted jobs; these failure snapshots never contain result frames.
    unsaved_failures: dict[str, JobResponse] = {}
    pending_deletions: set[Path] = set()
    # Reserve bytes not yet written by FFmpeg so uploads/results cannot consume them.
    normalization_reservations: dict[Path, int] = {}
    upload_reservations: dict[object, int] = {}
    normalization_slots = asyncio.Semaphore(config.normalization_workers)
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=config.queue_size)
    store: JobStore | None = None
    pdf_slots = asyncio.Semaphore(1)

    def storage_bytes() -> int:
        return sum(path.stat().st_size for path in config.storage.rglob("*") if path.is_file() and not path.is_symlink())

    def reserved_bytes() -> int:
        return sum(max(0, limit - (path.stat().st_size if path.exists() else 0))
                   for path, limit in normalization_reservations.items())

    def metadata_headroom() -> int:
        database = config.storage / "jobs.sqlite3"
        # SQLite may need a rollback journal while FFmpeg is still writing.
        # Keep space for that journal plus small status/index page updates.
        return (database.stat().st_size if database.exists() else 0) + 64 * 1024

    def physical_available_bytes() -> int:
        # The parser may spool outside STORAGE_DIR. Charge received bytes before
        # it can write them; double charging already-spooled bytes is conservative.
        free = min(shutil.disk_usage(config.storage).free,
                   shutil.disk_usage(tempfile.gettempdir()).free)
        return max(0, free - reserved_bytes()
                   - sum(upload_reservations.values()) - metadata_headroom())

    def available_bytes() -> int:
        return max(0, min(config.max_storage_mb * 1024 * 1024 - storage_bytes()
                          - reserved_bytes() - metadata_headroom(), physical_available_bytes()))

    def reserve_upload(token: object, size: int) -> bool:
        try:
            available = physical_available_bytes()
        except OSError:
            return False
        if size > available:
            return False
        upload_reservations[token] = upload_reservations.get(token, 0) + size
        return True

    def release_upload(token: object):
        upload_reservations.pop(token, None)

    def rollback_after_write_error():
        try:
            store.connection.rollback()
        except Exception:
            pass

    def try_save_terminal(job: JobResponse, video=None) -> bool:
        try:
            if video is None:
                store.save(job)
            else:
                store.save(job, video=video)
            return True
        except Exception as error:
            rollback_after_write_error()
            logger.error("Terminal state persistence failed id=%s kind=%s", job.job_id, type(error).__name__)
            return False

    def delete_source(path: Path):
        try:
            path.unlink(missing_ok=True)
            pending_deletions.discard(path)
        except OSError as error:
            pending_deletions.add(path)
            logger.error("Source cleanup failed kind=%s", type(error).__name__)

    def delete_inputs(record: RunningJob):
        delete_source(record.path)
        delete_source(record.normalized_path)
        normalization_reservations.pop(record.normalized_path, None)

    def cleanup():
        # Keep a bounded tombstone until the stale processing row can be replaced.
        # Expired tombstones return 404 without resurrecting that stale row.
        for job_id, job in list(unsaved_failures.items()):
            if try_save_terminal(job):
                unsaved_failures.pop(job_id, None)
        try:
            for path in [*store.delete_expired(time.time()), *store.expire_videos(time.time())]:
                delete_source(path)
        except Exception as error:
            rollback_after_write_error()
            logger.error("Result expiry cleanup failed kind=%s", type(error).__name__)
        for path in list(pending_deletions):
            delete_source(path)
        # Active inputs are removed on every terminal state; only stale orphans use TTL.
        cutoff = time.time() - config.retention_hours * 3600
        protected = {path for record in active.values() for path in (record.path, record.normalized_path)}
        for path in [*config.storage.glob("*.upload"), *config.storage.glob("*.normalized.mp4")]:
            if path not in protected and path.stat().st_mtime < cutoff:
                delete_source(path)

    def set_stage(record: RunningJob, stage: str):
        if record.job.status != "processing": return
        now = time.monotonic()
        previous = record.job.stage
        record.job.timings_sec["queue" if previous == "queued" else previous] = round(now - record.stage_started, 3)
        record.job.stage = stage
        record.stage_started = now
        store.save(record.job)

    def finish(record: RunningJob, code: str | None = None, error: str | None = None, result=None):
        if record.job.status != "processing":
            return
        # Persist a separate snapshot before changing the live record's status.
        job = record.job.model_copy(deep=True)
        if result is not None:
            # A new payload can grow both the database and its transaction journal.
            if 3 * len(result.model_dump_json().encode()) > available_bytes():
                code, error = "STORAGE_FULL", "На сервере закончилось место для результата. Повторите позже или обратитесь к администратору."
            else:
                job.verdict, job.violations = result.verdict, [ReviewedEvent(**event.model_dump()) for event in result.violations]
        if code:
            # A failure can never be mistaken for a clean video.
            job.verdict, job.violations = None, []
            job.error_code, job.error = code, error
        now = time.monotonic()
        previous = job.stage
        job.timings_sec["queue" if previous == "queued" else previous] = round(now - record.stage_started, 3)
        job.timings_sec["total"] = round(now - record.started, 3)
        job.status = job.stage = "failed" if code else "done"
        completed = time.time()
        job.completed_at = iso(completed)
        job.expires_at = iso(completed + config.retention_hours * 3600)
        video = None
        archive = config.storage / "videos" / f"{job.job_id}.mp4"
        if job.status == "done":
            try:
                record.normalized_path.replace(archive)
                video = dict(filename=archive.name, size_bytes=archive.stat().st_size,
                             expires_at=completed + config.video_retention_hours * 3600)
            except OSError:
                job.status = job.stage = "failed"
                job.verdict, job.violations = None, []
                job.error_code, job.error = "STORAGE_WRITE_FAILED", "Не удалось сохранить видеоархив. Проверьте хранилище сервера."
        try:
            if not try_save_terminal(job, video):
                job.status = job.stage = "failed"
                job.verdict, job.violations = None, []
                job.error_code = "STORAGE_WRITE_FAILED"
                job.error = "Не удалось сохранить результат на сервере. Повторите проверку после восстановления хранилища."
                if not try_save_terminal(job):
                    unsaved_failures[job.job_id] = job
            record.job = job
        finally:
            if job.status != "done":
                delete_source(archive)
            delete_inputs(record)
            active.pop(job.job_id, None)
            if record.timer and record.timer is not asyncio.current_task():
                record.timer.cancel()

    async def expire(record: RunningJob):
        await asyncio.sleep(max(0, record.deadline - time.monotonic()))
        if record.job.status == "processing":
            if record.work_task:
                record.work_task.cancel()
                # FFmpeg cancellation kills and reaps its child before files are removed.
                await asyncio.gather(record.work_task, return_exceptions=True)
            finish(record, "TIMEOUT", "Истекло общее время проверки, включая загрузку, очередь и преобразование. Попробуйте более короткую запись или повторите позже.")

    async def process(record: RunningJob):
        def remaining_budget() -> float:
            if record.job.status != "processing":
                raise asyncio.CancelledError
            remaining = record.deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            return remaining

        try:
            set_stage(record, "preparing")
            info = await media.inspect_video(record.path, timeout=min(20, remaining_budget()))
            record.job.duration_sec = info.duration_sec
            record.job.source_time_offset_sec = info.start_time
            # Waiting for a conversion slot consumes the same deadline as upload and ML.
            async with normalization_slots:
                remaining_budget()
                capacity = min(config.max_normalized_mb * 1024 * 1024, available_bytes())
                if capacity <= 0:
                    finish(record, "STORAGE_FULL", "На сервере недостаточно места для преобразования видео. Повторите позже.")
                    return
                normalization_reservations[record.normalized_path] = capacity
                try:
                    normalized = await media.normalize_video(
                        record.path, record.normalized_path, info,
                        timeout=remaining_budget(), max_bytes=capacity,
                    )
                finally:
                    normalization_reservations.pop(record.normalized_path, None)
            record.job.duration_sec = normalized.duration_sec
            remaining_budget()
            result = await pipeline.analyze(record.normalized_path, record.job.duration_sec, config, record.scenario, lambda stage: set_stage(record, stage))
            # Also guard synchronous work that returns after its allotted deadline.
            if time.monotonic() >= record.deadline:
                raise TimeoutError
            finish(record, result=result)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            finish(record, "TIMEOUT", "Истекло общее время проверки, включая загрузку и очередь. Попробуйте более короткую запись.")
        except FileNotFoundError:
            finish(record, "DEPENDENCY_UNAVAILABLE", "На сервере не установлен FFmpeg или недоступны рабочие файлы. Обратитесь к администратору.")
        except ValueError as error:
            code = getattr(error, "code", "INVALID_VIDEO" if record.job.stage == "preparing" else "INVALID_ML_RESPONSE")
            message = getattr(error, "message", None)
            if not message:
                # Never expose validation exceptions: they may contain entire base64 frames.
                message = "Не удалось прочитать или преобразовать видео. Загрузите корректный MOV, MP4, AVI, MKV или WEBM." if record.job.stage == "preparing" else "ML-модуль вернул некорректный ответ. Проверьте контракт интеграции."
            finish(record, code, message)
        except Exception as error:
            # No tracebacks or exception messages: third-party errors may contain secrets/media.
            logger.error("Video job failed id=%s kind=%s", record.job.job_id, type(error).__name__)
            finish(record, "PROCESSING_FAILED", "Не удалось завершить обработку. Проверьте доступность ML-модулей и повторите попытку.")
        finally:
            # Covers explicit cancellation and shutdown after the media child has stopped.
            delete_inputs(record)
            if record.job.status == "cancelled": active.pop(record.job.job_id,None)

    async def worker():
        while True:
            job_id = await queue.get()
            record = active.get(job_id)
            try:
                if record is None or record.job.status != "processing":
                    continue
                if time.monotonic() >= record.deadline:
                    finish(record, "TIMEOUT", "Истекло время ожидания в очереди. Повторите проверку позже.")
                    continue
                record.work_task = asyncio.create_task(process(record))
                try:
                    await record.work_task
                except asyncio.CancelledError:
                    # A job's deadline cancels that job, without losing a queue worker.
                    if asyncio.current_task().cancelling():
                        raise
            finally:
                queue.task_done()

    async def cleanup_loop():
        while True:
            await asyncio.sleep(config.cleanup_interval)
            cleanup()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal store
        config.validate()
        config.storage.mkdir(parents=True, exist_ok=True)
        (config.storage / "videos").mkdir(exist_ok=True)
        store = JobStore(config.storage / "jobs.sqlite3", retention_hours=config.retention_hours)
        app.state.store = store
        app.state.cleanup = cleanup
        app.state.active = active
        app.state.unsaved_failures = unsaved_failures
        app.state.normalization_reservations = normalization_reservations
        app.state.upload_reservations = upload_reservations
        # No input survives restart: explicitly fail pending work and preserve its identifier.
        now = time.time()
        for job in store.unfinished():
            job.status = job.stage = "failed"
            job.verdict, job.violations = None, []
            job.error_code = "SERVER_RESTARTED"
            job.error = "Сервер перезапустился до завершения проверки. Загрузите видео повторно."
            job.completed_at = iso(now)
            job.expires_at = iso(now + config.retention_hours * 3600)
            job.timings_sec["total"] = round(max(0, now - datetime.fromisoformat(job.created_at).timestamp()), 3)
            store.save(job)
        for path in [*config.storage.glob("*.upload"), *config.storage.glob("*.normalized.mp4")]:
            delete_source(path)
        known = store.retained_video_names()
        for path in (config.storage / "videos").glob("*.mp4"):
            if path.name not in known: delete_source(path)
        cleanup()
        workers = [asyncio.create_task(worker()) for _ in range(config.workers)]
        janitor = asyncio.create_task(cleanup_loop())
        try:
            yield
        finally:
            timers = []
            for record in active.values():
                if record.timer:
                    record.timer.cancel()
                    timers.append(record.timer)
            for task in [janitor, *workers]:
                task.cancel()
            await asyncio.gather(janitor, *workers, *timers, return_exceptions=True)
            for path in [*config.storage.glob("*.upload"), *config.storage.glob("*.normalized.mp4")]:
                delete_source(path)
            store.close()

    app = FastAPI(title="Cashier Guard API", version="0.4.0", lifespan=lifespan)
    app.add_middleware(UploadBudgetMiddleware, settings=config,
                       reserve_upload=reserve_upload, release_upload=release_upload)

    @app.exception_handler(HTTPException)
    async def request_error(request: Request, error: HTTPException):
        code = {400: "INVALID_UPLOAD", 401: "UNAUTHORIZED", 404: "JOB_NOT_FOUND",
                408: "TIMEOUT", 413: "UPLOAD_TOO_LARGE", 415: "UNSUPPORTED_FILE_TYPE",
                409: "JOB_ACTIVE", 410: "VIDEO_EXPIRED", 422: "INVALID_REQUEST", 503: "SERVICE_BUSY"}.get(error.status_code, "REQUEST_FAILED")
        return JSONResponse({"detail": error.detail, "error_code": code}, error.status_code, headers=error.headers)

    async def authorize(x_api_key: Annotated[str | None, Header()] = None):
        if not x_api_key or not hmac.compare_digest(x_api_key.encode(), config.api_key.encode()):
            raise HTTPException(401, "Неверный ключ API. Проверьте ключ доступа.")

    @app.get("/api/v1/health")
    async def health():
        return {"status": "ok", "mode": config.mode, "max_upload_mb": config.max_upload_mb, "job_timeout_seconds": config.timeout, "upload_timeout_seconds": min(config.upload_timeout, config.timeout), "result_ttl_hours": config.retention_hours, "video_ttl_hours": config.video_retention_hours, "max_storage_mb": config.max_storage_mb}

    @app.get("/api/v1/ready")
    async def ready():
        return await inspect_readiness(config)

    @app.post("/api/v1/analyze", status_code=202, dependencies=[Depends(authorize)])
    async def submit(
        request: Request,
        file: Annotated[UploadFile, File()],
        demo_scenario: Annotated[str, Form()] = "violation",
        tags: Annotated[str, Form()] = "[]",
        idempotency_key: Annotated[str | None, Header()] = None,
    ):
        filename = Path(file.filename or "video.mov").name
        path = None
        try:
            if idempotency_key and not re.fullmatch(r"[a-zA-Z0-9_-]{16,100}",idempotency_key):
                raise HTTPException(422,"Некорректный ключ повторной отправки.")
            try: metadata=TagsUpdate.model_validate({'tags':json.loads(tags)})
            except ValueError: raise HTTPException(422,"Укажите не более 10 меток по 64 символа.")
            if Path(filename).suffix.lower() not in {".mov", ".mp4", ".avi", ".mkv", ".webm"}:
                raise HTTPException(415, "Поддерживаются файлы MOV, MP4, AVI, MKV и WEBM.")
            if demo_scenario not in pipeline.DEMO_SCENARIOS:
                raise HTTPException(422, "Неизвестный демонстрационный сценарий.")
            cleanup()
            previous=store.submission(idempotency_key) if idempotency_key else None
            if unsaved_failures:
                raise HTTPException(503, "Хранилище результатов недоступно. Повторите загрузку после восстановления сервиса.")
            if not previous and (queue.full() or store.count() >= config.max_jobs):
                raise HTTPException(503, "Очередь или хранилище результатов заполнены. Повторите загрузку позже.")
            started = request.state.upload_started_mono
            started_at = request.state.upload_started_at
            deadline = started + config.timeout
            upload_deadline = started + min(config.upload_timeout, config.timeout)
            if time.monotonic() >= upload_deadline:
                raise HTTPException(408, "Истекло время загрузки и подготовки запроса. Повторите попытку.")
            job_id = uuid4().hex
            path = config.storage / f"{job_id}.upload"
            size = 0
            digest=hashlib.sha256()
            digest.update(json.dumps([filename,sorted(metadata.tags),demo_scenario if config.mode=='demo' else None],ensure_ascii=False).encode())
            try:
                async with asyncio.timeout(max(0, upload_deadline - time.monotonic())):
                    with path.open("wb") as target:
                        while chunk := await file.read(1024 * 1024):
                            size += len(chunk)
                            digest.update(chunk)
                            if size > config.max_upload_mb * 1024 * 1024:
                                raise HTTPException(413, f"Максимальный размер файла — {config.max_upload_mb} МБ.")
                            if not previous and len(chunk) > available_bytes():
                                raise HTTPException(503, "На сервере недостаточно места. Повторите позже.")
                            if not previous: target.write(chunk)
                            # Account actual bytes before the next upload can be admitted.
                            target.flush()
            except TimeoutError:
                raise HTTPException(408, "Истекло время загрузки. Выберите меньший файл или повторите попытку.")
            if not size:
                raise HTTPException(400, "Файл пуст. Выберите другую запись.")
            now = time.monotonic()
            if now >= upload_deadline:
                raise HTTPException(408, "Истекло время загрузки. Выберите меньший файл или повторите попытку.")
            fingerprint=digest.hexdigest()
            # No await between this lookup and the durable insert: single-process
            # admission cannot create two jobs with the same key.
            existing=store.submission(idempotency_key) if idempotency_key else None
            if previous and not existing:
                raise HTTPException(409,"Срок прежней отправки истёк во время запроса. Создайте новую проверку явно.")
            if existing:
                if existing[1]!=fingerprint: raise HTTPException(409,"Этот ключ отправки уже использован для другого файла или меток.")
                job=store.get(existing[0])
                delete_source(path)
                return {"job_id":job.job_id,"status":job.status,"mode":job.mode,"deadline_at":job.deadline_at,"expires_at":job.expires_at}
            # Concurrent uploads can have yielded while writing their file.
            if queue.full() or store.count() >= config.max_jobs:
                raise HTTPException(503, "Очередь или хранилище результатов заполнены. Повторите позже.")
            job = JobResponse(job_id=job_id, status="processing", stage="queued", mode=config.mode,
                              filename=filename, tags=metadata.tags, size_bytes=size, created_at=iso(started_at), deadline_at=iso(started_at + config.timeout),
                              expires_at=iso(started_at + config.timeout + config.retention_hours * 3600),
                              demo_scenario=demo_scenario if config.mode == "demo" else None,
                              timings_sec={"upload": round(now - started, 3)})
            record = RunningJob(job, path, demo_scenario, started, now, deadline, now)
            store.save(job,submission=(idempotency_key,fingerprint)) if idempotency_key else store.save(job)
            active[job_id] = record
            queue.put_nowait(job_id)
            record.timer = asyncio.create_task(expire(record))
        except sqlite3.Error:
            rollback_after_write_error()
            if path: delete_source(path)
            raise HTTPException(503, "Не удалось сохранить задание. Повторите отправку с тем же ключом.") from None
        except OSError:
            if path:
                delete_source(path)
            raise HTTPException(503, "Не удалось сохранить видео на сервере. Проверьте свободное место и доступность хранилища.") from None
        except BaseException:
            if path:
                delete_source(path)
            raise
        finally:
            await file.close()
        return {"job_id": job_id, "status": "processing", "mode": config.mode, "deadline_at": job.deadline_at, "expires_at": job.expires_at}

    def period(date_from, date_to):
        for value in (date_from, date_to):
            if value is not None and value.utcoffset() is None:
                raise HTTPException(422, "Укажите часовой пояс в датах периода.")
        if date_from and date_to and date_from >= date_to:
            raise HTTPException(422, "Начало периода должно быть раньше окончания.")
        return dict(date_from=date_from.timestamp() if date_from else None,
                    date_to=date_to.timestamp() if date_to else None)

    @app.get("/api/v1/jobs", response_model=HistoryPage, dependencies=[Depends(authorize)])
    async def history(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                      search: str = Query("", max_length=255), status: str | None = None,
                      date_from: datetime | None = None, date_to: datetime | None = None,
                      category_id: str | None = Query(None, max_length=200), mode: str | None = None, tag: str | None = Query(None,max_length=64)):
        if status not in (None, "processing", "done", "failed", "cancelled") or mode not in (None, "live", "demo"):
            raise HTTPException(422, "Неизвестный статус или режим.")
        filters = period(date_from,date_to)
        cleanup()
        return store.history(page,page_size,search=search,status=status,category_id=category_id,mode=mode,tag=tag,**filters)

    @app.get("/api/v1/analytics", response_model=AnalyticsResponse, dependencies=[Depends(authorize)])
    async def analytics(date_from: datetime | None = None, date_to: datetime | None = None):
        filters = period(date_from,date_to)
        cleanup()
        return store.analytics(**filters)

    @app.get("/api/v1/submissions/{request_key}", response_model=JobResponse, dependencies=[Depends(authorize)])
    async def find_submission(request_key: str):
        row=store.submission(request_key)
        if not row: raise HTTPException(404,"Отправка не найдена. Она ещё не принята сервером или срок хранения истёк.")
        return await get_job(row[0])

    @app.get("/api/v1/review-queue/options",response_model=ReviewQueueOptions,dependencies=[Depends(authorize)])
    async def queue_options():
        cleanup()
        return store.queue_options()

    @app.get("/api/v1/review-queue",response_model=ReviewQueuePage,dependencies=[Depends(authorize)])
    async def review_queue(page: int=Query(1,ge=1),page_size: int=Query(20,ge=1,le=50),
                           date_from: datetime | None=None,date_to: datetime | None=None,
                           category_id: str | None=Query(None,max_length=200),tag: str | None=Query(None,max_length=64),
                           exclude_event_id: str | None=Query(None,max_length=200)):
        filters=period(date_from,date_to);cleanup()
        return store.review_queue(page,page_size,category_id=category_id,tag=tag,exclude_event_id=exclude_event_id,**filters)

    @app.get("/api/v1/jobs/{job_id}", response_model=JobResponse, dependencies=[Depends(authorize)])
    async def get_job(job_id: str):
        job = unsaved_failures.get(job_id) or store.get(job_id)
        if job is None or (job.status != "processing" and datetime.fromisoformat(job.expires_at).timestamp() <= time.time()):
            raise HTTPException(404, "Проверка не найдена или срок хранения истёк. Загрузите видео заново.")
        return job

    @app.delete("/api/v1/jobs/{job_id}", dependencies=[Depends(authorize)])
    async def delete_job(job_id: str):
        job = await get_job(job_id)
        if job.status == "processing" or job_id in active:
            raise HTTPException(409, "Дождитесь завершения обработки, затем удалите проверку.")
        try:
            path = store.delete(job_id)
        except sqlite3.Error:
            rollback_after_write_error()
            raise HTTPException(503, "Не удалось удалить проверку. Повторите после восстановления хранилища.")
        if path: delete_source(path)
        unsaved_failures.pop(job_id,None)
        return {"deleted": True, "job_id": job_id}

    @app.patch("/api/v1/jobs/{job_id}/events/{event_id}/review", response_model=HumanReview, dependencies=[Depends(authorize)])
    async def review_event(job_id: str, event_id: str, update: ReviewUpdate):
        job = await get_job(job_id)
        if job.status != "done":
            raise HTTPException(409, "Решения доступны только для завершённой проверки.")
        if 3 * len(update.comment.encode()) + 16_384 > available_bytes():
            raise HTTPException(503,"Недостаточно места для сохранения решения. Освободите хранилище.")
        try:
            result = store.update_review(job_id,event_id,update)
        except sqlite3.Error:
            rollback_after_write_error()
            raise HTTPException(503, "Не удалось сохранить решение. Повторите после восстановления хранилища.")
        if result is None: raise HTTPException(404,"Событие не найдено в этой проверке.")
        return result

    @app.patch("/api/v1/jobs/{job_id}/tags",response_model=TagsUpdate,dependencies=[Depends(authorize)])
    async def change_tags(job_id: str, update: TagsUpdate):
        await get_job(job_id)
        if 3*len(update.model_dump_json().encode())+16384 > available_bytes():
            raise HTTPException(503,"Недостаточно места для сохранения меток.")
        try: return {"tags":store.set_tags(job_id,update.tags)}
        except sqlite3.Error:
            rollback_after_write_error()
            raise HTTPException(503,"Не удалось сохранить метки. Введённые данные можно отправить повторно.")

    @app.get("/api/v1/jobs/{job_id}/review-log",response_model=ReviewLogPage,dependencies=[Depends(authorize)])
    async def review_log(job_id: str,page: int=Query(1,ge=1),page_size: int=Query(20,ge=1,le=100)):
        await get_job(job_id)
        return store.review_log(job_id,page,page_size)

    @app.post("/api/v1/jobs/{job_id}/cancel",response_model=JobResponse,dependencies=[Depends(authorize)])
    async def cancel_job(job_id: str):
        job=await get_job(job_id)
        if job.status!='processing': return job
        record=active.get(job_id)
        cancelled=job.model_copy(deep=True)
        cancelled.status=cancelled.stage='cancelled'
        cancelled.verdict=None;cancelled.violations=[]
        cancelled.error_code='CANCELLED'
        cancelled.error='Проверка отменена пользователем. Внешний ML-сервис может завершить свой запрос отдельно; его поздний ответ не будет сохранён.'
        cancelled.completed_at=iso(time.time())
        cancelled.expires_at=iso(time.time()+config.retention_hours*3600)
        if not try_save_terminal(cancelled):
            raise HTTPException(503,"Не удалось сохранить отмену. Обновите статус и повторите запрос.")
        if record:
            # Publish the terminal state before yielding or cancelling I/O. Every
            # callback/finish now sees cancelled, even a cancellation-resistant ML.
            record.job=cancelled
            if record.timer: record.timer.cancel()
            if record.work_task:
                record.work_task.cancel()
                await asyncio.wait({record.work_task},timeout=5)
            else:
                delete_inputs(record);active.pop(job_id,None)
        return await get_job(job_id)

    @app.get("/api/v1/jobs/{job_id}/report.pdf",dependencies=[Depends(authorize)])
    async def report(job_id: str):
        if pdf_slots.locked():
            raise HTTPException(503,"Другой отчёт ещё формируется. Повторите через несколько секунд.")
        async with pdf_slots:
            job=await get_job(job_id)
            try: pdf=await asyncio.to_thread(build_report,job)
            except Exception:
                raise HTTPException(503,"Не удалось сформировать PDF. Результат проверки сохранён; повторите загрузку отчёта.") from None
        return Response(pdf,media_type='application/pdf',headers={'Content-Disposition':f'attachment; filename="cashier-guard-{job_id}.pdf"','Cache-Control':'private, no-store'})

    @app.get("/api/v1/jobs/{job_id}/video", dependencies=[Depends(authorize)])
    async def video(job_id: str):
        job = await get_job(job_id)
        path = store.video_path(job_id)
        if not path:
            raise HTTPException(410,"Видеозапись недоступна: срок её хранения истёк или файл не был сохранён. Результат и кадры доступны отдельно.")
        return FileResponse(path, media_type="video/mp4", filename=Path(job.filename).stem + ".mp4",
                            content_disposition_type="inline", headers={"Cache-Control":"private, no-store"})

    dist = ROOT / "frontend" / "dist"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    async def frontend():
        if (dist / "index.html").is_file():
            return FileResponse(dist / "index.html")
        return {"message": "Run the frontend dev server on port 5173, or build frontend/dist.", "docs": "/docs"}

    return app


app = create_app()
