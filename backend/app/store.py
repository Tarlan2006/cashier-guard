"""Small single-process SQLite result store. Never stores API keys or video bytes."""
import sqlite3
from datetime import datetime
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
        row = self.connection.execute("SELECT payload FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return JobResponse.model_validate_json(row[0]) if row else None

    def unfinished(self) -> list[JobResponse]:
        return [JobResponse.model_validate_json(row[0]) for row in self.connection.execute(
            "SELECT payload FROM jobs WHERE status = 'processing'"
        )]

    def count(self) -> int:
        return self.connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    def delete_expired(self, now: float):
        self.connection.execute("DELETE FROM jobs WHERE expires_at <= ? AND status != 'processing'", (now,))
        self.connection.commit()

    def close(self):
        self.connection.close()
