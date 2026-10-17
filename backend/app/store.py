"""Small single-process SQLite result store. Never stores API keys or video bytes."""
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import JobResponse


class JobStore:
    def __init__(self, path: Path):
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA auto_vacuum = FULL")
        self.connection.execute("""CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY, status TEXT NOT NULL,
            expires_at REAL NOT NULL, payload TEXT NOT NULL
        )""")
        self.connection.execute("CREATE INDEX IF NOT EXISTS jobs_expiry ON jobs(expires_at)")
        self.connection.commit()

    def save(self, job: JobResponse):
        expiry = datetime.fromisoformat(job.expires_at).timestamp()
        self.connection.execute(
            "INSERT OR REPLACE INTO jobs VALUES (?, ?, ?, ?)",
            (job.job_id, job.status, expiry, job.model_dump_json()),
        )
        self.connection.commit()

    def get(self, job_id: str) -> JobResponse | None:
        row = self.connection.execute("SELECT job_id, status, expires_at, payload FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return self._decode(row) if row else None

    def _decode(self, row) -> JobResponse:
        job_id, status, expiry, payload = row
        try:
            job = JobResponse.model_validate_json(payload)
            if job.job_id != job_id or job.status != status:
                raise ValueError("Stored identity or status does not match")
            # API expiry and restart recovery also need these timestamps to parse.
            for value in (job.created_at, job.expires_at):
                if value is None or not math.isfinite(datetime.fromisoformat(value).timestamp()):
                    raise ValueError("Invalid stored timestamp")
            return job
        except (ValueError, TypeError, OverflowError):
            # A damaged/unknown assessment is a failed check, never an empty success.
            # Do not copy frames, verdicts, errors or arbitrary model fields from it.
            try:
                raw = json.loads(payload)
            except (ValueError, TypeError, RecursionError):
                raw = {}
            if not isinstance(raw, dict):
                raw = {}
            now = datetime.now(timezone.utc)
            try:
                expires_at = datetime.fromtimestamp(expiry, timezone.utc).isoformat()
            except (ValueError, TypeError, OverflowError, OSError):
                expires_at = now.isoformat()
            filename = raw.get("filename")
            mode = raw.get("mode")
            job = JobResponse(
                job_id=job_id, status="failed", stage="failed",
                mode=mode if isinstance(mode, str) and mode in {"demo", "live"} else "live",
                filename=filename if isinstance(filename, str) and filename else "Видео",
                created_at=now.isoformat(), expires_at=expires_at, completed_at=now.isoformat(),
                verdict=None, violations=[], error_code="RESULT_INVALID",
                error="Сохранённый результат не соответствует контракту. Проверка не завершена; загрузите видео повторно.",
            )
            try:
                self.save(job)
            except sqlite3.Error:
                self.connection.rollback()
            return job

    def unfinished(self) -> list[JobResponse]:
        rows = self.connection.execute(
            "SELECT job_id, status, expires_at, payload FROM jobs WHERE status = 'processing'"
        ).fetchall()
        return [job for row in rows if (job := self._decode(row)).status == "processing"]

    def count(self) -> int:
        return self.connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    def delete_expired(self, now: float):
        self.connection.execute("DELETE FROM jobs WHERE expires_at <= ? AND status != 'processing'", (now,))
        self.connection.commit()

    def close(self):
        self.connection.close()
