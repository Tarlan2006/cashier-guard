import os
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
    timeout: float = field(default_factory=lambda: float(os.getenv("JOB_TIMEOUT_SECONDS", "280")))
    ml1_url: str = field(default_factory=lambda: os.getenv("ML1_URL", "http://127.0.0.1:8001"))
    ml2_url: str = field(default_factory=lambda: os.getenv("ML2_URL", "http://127.0.0.1:8002"))
    storage: Path = ROOT / "backend" / "storage"
    rules_path: Path = ROOT / "data" / "rules.json"
    workers: int = 2
    queue_size: int = 16

    def validate(self):
        if not self.api_key or self.api_key == "replace-with-your-own-key":
            raise RuntimeError("Set a private API_KEY in the root .env file. See README.md.")
        if self.mode not in {"demo", "live"}:
            raise RuntimeError("PIPELINE_MODE must be demo or live")
        if not 0 < self.timeout <= 280 or self.max_upload_mb <= 0:
            raise RuntimeError("Invalid upload limit or job timeout (must be <= 280 seconds)")

