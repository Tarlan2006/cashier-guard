import os
import math
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    api_key: str = field(default_factory=lambda: os.getenv("API_KEY", ""))
    mode: str = field(default_factory=lambda: os.getenv("PIPELINE_MODE", "demo"))
    max_upload_mb: int = field(default_factory=lambda: int(os.getenv("MAX_UPLOAD_MB", "100")))
    timeout: float = field(default_factory=lambda: float(os.getenv("JOB_TIMEOUT_SECONDS", "290")))
    upload_timeout: float = field(default_factory=lambda: float(os.getenv("UPLOAD_TIMEOUT_SECONDS", "60")))
    ml1_url: str = field(default_factory=lambda: os.getenv("ML1_URL", "http://127.0.0.1:8001"))
    ml2_url: str = field(default_factory=lambda: os.getenv("ML2_URL", "http://127.0.0.1:8002"))
    storage: Path = field(default_factory=lambda: Path(os.getenv("STORAGE_DIR", str(ROOT / "backend" / "storage"))))
    rules_path: Path = field(default_factory=lambda: Path(os.getenv("RULES_PATH", str(ROOT / "data" / "rules.json"))))
    workers: int = field(default_factory=lambda: int(os.getenv("WORKERS", "2")))
    queue_size: int = field(default_factory=lambda: int(os.getenv("QUEUE_SIZE", "16")))
    max_jobs: int = field(default_factory=lambda: int(os.getenv("MAX_STORED_JOBS", "128")))
    retention_hours: float = field(default_factory=lambda: float(os.getenv("RESULT_TTL_HOURS", "1")))
    cleanup_interval: float = field(default_factory=lambda: float(os.getenv("CLEANUP_INTERVAL_SECONDS", "60")))
    max_storage_mb: int = field(default_factory=lambda: int(os.getenv("MAX_STORAGE_MB", "2048")))
    max_concurrent_uploads: int = field(default_factory=lambda: int(os.getenv("MAX_CONCURRENT_UPLOADS", "2")))

    def validate(self):
        if not self.api_key or self.api_key == "replace-with-your-own-key":
            raise RuntimeError("Set a private API_KEY in the root .env file. See README.md.")
        if self.mode not in {"demo", "live"}:
            raise RuntimeError("PIPELINE_MODE must be demo or live")
        if not 0 < self.timeout <= 295 or self.max_upload_mb <= 0:
            raise RuntimeError("Invalid upload limit or job timeout (must be <= 295 seconds)")
        limits = (self.upload_timeout, self.workers, self.queue_size, self.max_jobs,
                  self.retention_hours, self.cleanup_interval, self.max_storage_mb,
                  self.max_concurrent_uploads)
        if any(not math.isfinite(value) or value <= 0 for value in limits):
            raise RuntimeError("Storage, concurrency, retention and upload settings must be positive")
