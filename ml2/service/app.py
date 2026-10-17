"""Local ML1 transport service. Run from ml2 with exactly one Uvicorn worker."""

from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
import json
import logging
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(
    HF_HUB_OFFLINE="1",
    TRANSFORMERS_OFFLINE="1",
    HF_HUB_DISABLE_TELEMETRY="1",
    DO_NOT_TRACK="1",
)

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from backend.pipeline.analyze import analyze_video, AnalysisIncomplete
from backend.pipeline.perception.config import load_config, PerceptionConfig
from backend.pipeline.resident import ResidentRuntime, RuntimeBusy
from service.evidence import observations

LOG = logging.getLogger(__name__)


def service_config() -> PerceptionConfig:
    config = load_config()
    model_root = os.environ.get("ML_MODELS_DIR")
    if model_root:
        config.model_path = str(Path(model_root).resolve() / "rtdetr_r18vd")
        config.fixture_model_path = str(
            Path(model_root).resolve() / "siglip-base-patch16-224"
        )
    gate = json.loads(
        (ROOT / "configs/rule_validation.json").read_text(encoding="utf-8")
    )
    if not set(config.validated_rule_ids or []) <= set(gate["enabled_rule_ids"]):
        raise ValueError("Configured rule did not pass the measured validation gate")
    return config


def create_app(
    *, runtime_factory=ResidentRuntime, config: PerceptionConfig | None = None
) -> FastAPI:
    selected = config if config is not None else service_config()

    @asynccontextmanager
    async def lifespan(app):
        runtime = runtime_factory(selected)
        await asyncio.to_thread(runtime.start)
        app.state.runtime = runtime
        try:
            yield
        finally:
            await asyncio.to_thread(runtime.close)

    app = FastAPI(
        title="Cashier Guard local video analysis (ML1 contract)", lifespan=lifespan
    )

    @app.get("/health")
    def health() -> JSONResponse:
        runtime = app.state.runtime
        ready = runtime.ready and runtime.process.is_alive()
        return JSONResponse(
            dict(
                status="ok" if ready else "unavailable",
                local_only=True,
                analysis_status="ready" if selected.validated_rule_ids else "partial",
                enabled_rule_ids=selected.validated_rule_ids or [],
                model_loads=runtime.model_loads,
            ),
            status_code=200 if ready else 503,
        )

    def process(path: Path) -> tuple[dict, dict]:
        class Capture:
            report = None

            def analyze(self, video: Path) -> dict:
                self.report = app.state.runtime.analyze(video)
                return self.report

        capture = Capture()
        events = analyze_video(path, config=selected, runtime=capture)
        return observations(events), capture.report

    @app.post("/analyze")
    async def analyze(file: UploadFile = File(...)) -> JSONResponse:
        suffix = Path(file.filename or "video.mov").suffix.lower()
        if suffix not in {".mov", ".mp4"}:
            raise HTTPException(415, "Upload a MOV or MP4 video")
        directory = ROOT / "cache/uploads"
        directory.mkdir(parents=True, exist_ok=True)
        path = None
        try:
            max_bytes = int(os.environ.get("ML_MAX_UPLOAD_MB", "512")) * 1024 * 1024
            size = 0
            with tempfile.NamedTemporaryFile(
                dir=directory, suffix=suffix, delete=False
            ) as output:
                path = Path(output.name)
                async with asyncio.timeout(60):
                    while chunk := await file.read(1024 * 1024):
                        size += len(chunk)
                        if size > max_bytes:
                            raise HTTPException(
                                413, "Upload exceeds the local service size limit"
                            )
                        output.write(chunk)
            if size == 0:
                raise HTTPException(400, "Empty video")
            body, report = await asyncio.to_thread(process, path)
            return JSONResponse(
                body,
                headers={
                    "X-Analysis-Status": report["status"],
                    "X-Analysis-Complete": str(report["analysis_complete"]).lower(),
                    "X-Perception-Complete": str(report["perception_complete"]).lower(),
                    "X-Enabled-Rule-Count": str(len(report["enabled_rule_ids"])),
                    "X-Input-Cache": "disabled-between-requests",
                    "X-Elapsed-Seconds": f"{report['elapsed_sec']:.3f}",
                },
            )
        except HTTPException:
            raise
        except TimeoutError:
            raise HTTPException(408, "Upload timed out") from None
        except RuntimeBusy:
            raise HTTPException(
                503, "Local model is busy; retry after the current request"
            ) from None
        except AnalysisIncomplete as exc:
            kind = (exc.report or {}).get("error_type")
            code = (
                422
                if kind == "ValueError"
                else (504 if kind in {None, "BudgetExpired", "TimeoutError"} else 500)
            )
            LOG.warning("Incomplete local inference: %s", kind or "time budget")
            raise HTTPException(
                code,
                "Local analysis did not complete; no clean-video verdict was produced",
            ) from None
        except Exception:
            LOG.exception("Local analyze request error")
            raise HTTPException(
                500, "Local analysis error; no clean-video verdict was produced"
            ) from None
        finally:
            await file.close()
            if path is not None:
                path.unlink(missing_ok=True)

    return app


app = create_app()
