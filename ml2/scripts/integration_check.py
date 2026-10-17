"""Local open-set transport check; never invents or bypasses a rules catalog."""

from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
import httpx
import jsonschema

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def wait_health(client, url, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = client.get(url, timeout=1)
            if response.status_code == 200:
                return response.json()
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise RuntimeError("Local health deadline reached: " + url)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--open-root", type=Path, required=True)
    parser.add_argument("--ffmpeg-bin", type=Path, required=True)
    parser.add_argument(
        "--backend-python", type=Path, default=REPO / "backend/.venv/Scripts/python.exe"
    )
    parser.add_argument("--models", type=Path)
    parser.add_argument("--existing-ml1", action="store_true")
    parser.add_argument(
        "--rules-path",
        type=Path,
        help="Optional existing/converted catalog; never alters data/rules.json",
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / "cache/integration")
    args = parser.parse_args()
    open_root = args.open_root.resolve()
    if open_root.name != "open" or open_root.parent.name != "data":
        parser.error("Use the explicitly authorized data/open directory")
    files = {}
    for path in (open_root / "videos").glob("*.mov"):
        number = re.search(r"[XХxх]-(\d+)", path.name)
        if number:
            files[int(number.group(1))] = path
    if not {2, 14} <= files.keys():
        raise ValueError("Open videos 2 and 14 are required")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    schema = json.loads(
        (REPO / "contracts/ml1-response.schema.json").read_text(encoding="utf-8")
    )
    key = secrets.token_urlsafe(32)
    env = os.environ.copy()
    env.update(
        API_KEY=key,
        PIPELINE_MODE="live",
        ML1_URL="http://127.0.0.1:8001",
        ML2_URL="http://127.0.0.1:8002",
        STORAGE_DIR=str(output / "storage"),
        WORKERS="1",
        PYTHONUTF8="1",
    )
    env["PATH"] = str(args.ffmpeg_bin.resolve()) + os.pathsep + env.get("PATH", "")
    if args.models:
        env["ML_MODELS_DIR"] = str(args.models.resolve())
    catalog_path = (
        args.rules_path.resolve() if args.rules_path else REPO / "data/rules.json"
    )
    env["RULES_PATH"] = str(catalog_path)
    processes = []
    logs = []

    def start(python, module, cwd, port, name):
        log = (output / (name + ".log")).open("w", encoding="utf-8")
        logs.append(log)
        process = subprocess.Popen(
            [
                str(python),
                "-X",
                "utf8",
                "-m",
                "uvicorn",
                module,
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--workers",
                "1",
                "--no-access-log",
            ],
            cwd=cwd,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        processes.append(process)

    report = dict(
        direct_ml1=[],
        backend=[],
        rules_catalog_count=len(
            json.loads(catalog_path.read_text(encoding="utf-8"))["rules"]
        ),
        synthetic_catalog_used=False,
        backend_code_modified=False,
        converted_research_catalog=bool(args.rules_path),
        backend_python=subprocess.check_output(
            [str(args.backend_python), "--version"], text=True
        ).strip(),
        ml1_python=sys.version.split()[0],
    )
    try:
        if not args.existing_ml1:
            start(sys.executable, "service.app:app", ROOT, 8001, "ml1")
        start(sys.executable, "scripts.ml2_stub:app", ROOT, 8002, "ml2_stub")
        start(args.backend_python, "app.main:app", REPO / "backend", 8000, "backend")
        with httpx.Client(trust_env=False, timeout=190) as client:
            report["health_before"] = wait_health(
                client, "http://127.0.0.1:8001/health"
            )
            wait_health(client, "http://127.0.0.1:8002/health")
            wait_health(client, "http://127.0.0.1:8000/api/v1/health")
            for number in (2, 14):
                path = files[number]
                if not path.resolve().is_relative_to(open_root):
                    raise ValueError("Input escaped open data")
                started = time.perf_counter()
                with path.open("rb") as video:
                    response = client.post(
                        "http://127.0.0.1:8001/analyze",
                        files={"file": (path.name, video, "video/quicktime")},
                    )
                elapsed = time.perf_counter() - started
                record = dict(
                    video=number,
                    http_status=response.status_code,
                    wall_sec=elapsed,
                    headers={
                        k: v for k, v in response.headers.items() if k.startswith("x-")
                    },
                )
                if response.is_success:
                    jsonschema.validate(response.json(), schema)
                    record.update(
                        schema_valid=True, event_count=len(response.json()["events"])
                    )
                else:
                    record["error"] = response.json()
                report["direct_ml1"].append(record)
                print(json.dumps(dict(stage="direct_ml1", **record)), flush=True)
                started = time.perf_counter()
                with path.open("rb") as video:
                    response = client.post(
                        "http://127.0.0.1:8000/api/v1/analyze",
                        headers={"X-API-Key": key},
                        files={"file": (path.name, video, "video/quicktime")},
                    )
                record = dict(video=number, post_http_status=response.status_code)
                if response.status_code == 202:
                    identifier = response.json()["job_id"]
                    deadline = time.monotonic() + 295
                    while time.monotonic() < deadline:
                        result = client.get(
                            "http://127.0.0.1:8000/api/v1/jobs/" + identifier,
                            headers={"X-API-Key": key},
                        )
                        result.raise_for_status()
                        job = result.json()
                        if job["status"] != "processing":
                            record.update(
                                backend_legacy_status=job["status"],
                                verdict=job["verdict"],
                                error_code=job["error_code"],
                                timings_sec=job["timings_sec"],
                            )
                            break
                        time.sleep(0.2)
                    else:
                        record["error_code"] = "POLL_TIMEOUT"
                else:
                    record["error"] = response.json()
                record["wall_sec"] = time.perf_counter() - started
                report["backend"].append(record)
                print(json.dumps(dict(stage="backend", **record)), flush=True)
            report["health_after"] = client.get("http://127.0.0.1:8001/health").json()
            invalid = client.post(
                "http://127.0.0.1:8001/analyze",
                files={"file": ("invalid.mov", b"not a video")},
            )
            report["invalid_video_http_status"] = invalid.status_code
    finally:
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
        for log in logs:
            log.close()
        (output / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(
        "Local integration report saved; credentials and frames were not printed",
        flush=True,
    )


if __name__ == "__main__":
    main()
