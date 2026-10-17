import asyncio
import hmac
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import pipeline
from .config import ROOT, Settings
from .models import JobResponse

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    jobs: dict[str, JobResponse] = {}
    deadlines: dict[str, float] = {}
    queue: asyncio.Queue = asyncio.Queue(maxsize=config.queue_size)

    async def worker():
        while True:
            job_id, path, scenario = await queue.get()
            job = jobs[job_id]
            try:
                remaining = config.timeout - (time.monotonic() - deadlines[job_id])
                if remaining <= 0:
                    raise TimeoutError
                async with asyncio.timeout(remaining):
                    job.stage = "preparing"
                    job.duration_sec = await pipeline.probe(path)
                    result = await pipeline.analyze(path, job.duration_sec, config, scenario, lambda stage: setattr(job, "stage", stage))
                    job.verdict = result.verdict
                    job.violations = result.violations
                    job.status = "done"
                    job.stage = "done"
            except TimeoutError:
                job.status, job.stage = "failed", "failed"
                job.error = "Превышено время обработки. Попробуйте более короткую запись."
            except FileNotFoundError:
                job.status, job.stage = "failed", "failed"
                job.error = "На сервере не установлен FFmpeg. Обратитесь к администратору."
            except ValueError as error:
                job.status, job.stage = "failed", "failed"
                # Schema internals may include frame data. Only expose our short, actionable messages.
                job.error = str(error) if len(str(error)) < 250 else "ML-модуль вернул некорректный результат. Проверьте контракт интеграции."
            except Exception:
                logger.exception("Video job failed: %s", job_id)
                job.status, job.stage = "failed", "failed"
                job.error = "Не удалось завершить обработку. Проверьте доступность ML-модулей и повторите попытку."
            finally:
                path.unlink(missing_ok=True)
                queue.task_done()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config.validate()
        config.storage.mkdir(parents=True, exist_ok=True)
        # Jobs are session-local. Remove uploads left by an interrupted previous run.
        for path in config.storage.glob("*.upload"):
            path.unlink(missing_ok=True)
        workers = [asyncio.create_task(worker()) for _ in range(config.workers)]
        yield
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        for path in config.storage.glob("*.upload"):
            path.unlink(missing_ok=True)

    app = FastAPI(title="Cashier Guard API", version="0.1.0", lifespan=lifespan)

    async def authorize(x_api_key: Annotated[str | None, Header()] = None):
        if not x_api_key or not hmac.compare_digest(x_api_key.encode(), config.api_key.encode()):
            raise HTTPException(401, "Неверный ключ API. Проверьте ключ доступа.")

    @app.get("/api/v1/health")
    async def health():
        return {"status": "ok", "mode": config.mode, "max_upload_mb": config.max_upload_mb}

    @app.post("/api/v1/analyze", status_code=202, dependencies=[Depends(authorize)])
    async def submit(
        file: Annotated[UploadFile, File()],
        demo_scenario: Annotated[Literal["violation", "no_violation"], Form()] = "violation",
    ):
        filename = Path(file.filename or "video.mov").name
        if Path(filename).suffix.lower() not in {".mov", ".mp4"}:
            await file.close()
            raise HTTPException(415, "Поддерживаются файлы MOV и MP4.")
        # Bound result memory and retain completed jobs for one hour.
        for key in list(jobs):
            if jobs[key].status != "processing" and time.monotonic() - deadlines[key] > 3600:
                del jobs[key]
                del deadlines[key]
        if queue.full() or len(jobs) >= 128:
            await file.close()
            raise HTTPException(503, "Очередь заполнена. Повторите загрузку позже.")
        job_id = uuid4().hex
        path = config.storage / f"{job_id}.upload"
        size = 0
        try:
            with path.open("wb") as target:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > config.max_upload_mb * 1024 * 1024:
                        raise HTTPException(413, f"Максимальный размер файла — {config.max_upload_mb} МБ.")
                    target.write(chunk)
            if not size:
                raise HTTPException(400, "Файл пуст. Выберите другую запись.")
            jobs[job_id] = JobResponse(job_id=job_id, status="processing", stage="queued", mode=config.mode,
                                       filename=filename, created_at=datetime.now(timezone.utc).isoformat())
            deadlines[job_id] = time.monotonic()
            try:
                queue.put_nowait((job_id, path, demo_scenario))
            except asyncio.QueueFull:
                del jobs[job_id]
                del deadlines[job_id]
                raise HTTPException(503, "Очередь заполнена. Повторите загрузку позже.")
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        finally:
            await file.close()
        return {"job_id": job_id, "status": "processing", "mode": config.mode}

    @app.get("/api/v1/jobs/{job_id}", response_model=JobResponse, dependencies=[Depends(authorize)])
    async def get_job(job_id: str):
        if job_id not in jobs:
            raise HTTPException(404, "Проверка не найдена. После перезапуска сервиса загрузите видео заново.")
        return jobs[job_id]

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

