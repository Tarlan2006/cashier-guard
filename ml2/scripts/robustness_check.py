"""Run fixed FFmpeg variations of authorized open videos against local ML1.

All media and raw results must stay outside the checkout. This tests HTTP
completion and latency, not recognition accuracy when facts are not exposed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import ipaddress
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_chain import open_videos

FILTERS = {
    "control_reencode": "null",
    "mirror": "hflip",
    "rotate_10_crop": "rotate=10*PI/180:ow=iw:oh=ih:fillcolor=black,"
                      "crop=trunc(iw*0.84/2)*2:trunc(ih*0.84/2)*2",
    "dark_low_contrast": "eq=brightness=-0.12:contrast=0.75",
    "crop_top_15": "crop=trunc(iw/2)*2:trunc(ih*0.85/2)*2:0:trunc(ih*0.15/2)*2",
}


def local_url(value: str) -> str:
    parsed = urlsplit(value)
    try:
        loopback = ipaddress.ip_address(parsed.hostname or "").is_loopback
    except ValueError:
        loopback = False
    if (parsed.scheme != "http" or not loopback or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
        raise ValueError("Only an HTTP loopback IP base URL is allowed")
    return value.rstrip("/")


def external_output(value: Path) -> Path:
    output = value.resolve()
    if output.is_relative_to(ROOT.parent.resolve()):
        raise ValueError("Media output must be outside the repository")
    return output


def observe(client: httpx.Client, base: str, path: Path) -> dict:
    started = time.perf_counter()
    row = dict(status=None, events=None, rules_enabled=None, analysis_status=None,
               perception_complete=None, cashier=None, client=None,
               counter_machine=None, safe=None, diagnostics_available=False)
    try:
        with path.open("rb") as stream:
            response = client.post(base + "/analyze",
                files={"file": (path.name, stream, "video/mp4")})
        row.update(status=response.status_code,
            rules_enabled=response.headers.get("X-Rules-Enabled"),
            analysis_status=response.headers.get("X-Analysis-Status"),
            perception_complete=response.headers.get("X-Perception-Complete"))
        try:
            body = response.json()
        except ValueError:
            body = None
        if (response.status_code == 200 and isinstance(body, dict)
                and body.get("schema_version") == "1.0" and isinstance(body.get("events"), list)):
            row["events"] = len(body["events"])
            row["note"] = "No role/anchor diagnostics in ML1 response; quality not evaluated"
        else:
            row["note"] = "HTTP/contract error; no clean-video conclusion"
    except httpx.HTTPError as exc:
        row["note"] = "Transport error: " + type(exc).__name__
    row["elapsed_sec"] = round(time.perf_counter() - started, 3)
    return row


def markdown(rows: list[dict], health: dict) -> str:
    lines = ["# Open-video HTTP robustness check", "",
        "Date: " + datetime.now(timezone.utc).isoformat(), "",
        "Fixed transforms; CPU, one resident ML1 worker, no parameter changes.",
        "Control is reencoded with the same H.264/yuv420p settings as variations.",
        "Only authorized data/open inputs. All media/raw results stay outside Git.", "",
        "| Video | Variation | HTTP | Seconds | Events | X-Rules-Enabled | X-Analysis-Status | Perception complete |",
        "|---|---|---:|---:|---:|---|---|---|"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(key)) if row.get(key) is not None else "—"
            for key in ("video", "variation", "status", "elapsed_sec", "events",
                        "rules_enabled", "analysis_status", "perception_complete")) + " |")
    lines += ["", "## Limits of this check", "",
        "ML1 does not expose cashier/client/anchor facts. All four fields are unavailable,",
        "not absent. Empty events with no enabled rules do not measure detection quality.",
        "A successful HTTP response establishes completion only. Timing is a single run.",
        "HTTP errors and transport failures remain explicit in the table.", "",
        "Initial health: `" + json.dumps(health, ensure_ascii=True) + "`", "",
        "## FFmpeg filters", ""]
    lines.extend("- `" + name + "`: `" + expression + "`" for name, expression in FILTERS.items())
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--open-root", type=Path, required=True)
    parser.add_argument("--numbers", type=int, nargs="+", default=[2, 14])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8001")
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg"))
    args = parser.parse_args()
    base = local_url(args.url)
    output = external_output(args.output)
    videos = open_videos(args.open_root, args.numbers)
    if not args.ffmpeg:
        raise ValueError("FFmpeg is required; supply --ffmpeg")
    output.mkdir(parents=True, exist_ok=True)
    if (output / "results.json").exists():
        raise ValueError("Use a new output directory; prior results will not be overwritten")
    timeout = httpx.Timeout(190, connect=5, write=60, pool=5)
    rows = []
    with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False) as client:
        health_response = client.get(base + "/health", timeout=10)
        health_response.raise_for_status()
        health = health_response.json()
        for number, source in videos:
            for name, expression in FILTERS.items():
                destination = output / f"{number:02d}_{name}.mp4"
                command = [args.ffmpeg, "-nostdin", "-v", "error", "-n",
                    "-i", str(source), "-map", "0:v:0", "-an", "-sn", "-dn",
                    "-vf", expression, "-c:v", "libx264", "-preset", "fast",
                    "-crf", "18", "-pix_fmt", "yuv420p", "-threads", "2",
                    "-fps_mode", "passthrough", "-map_metadata", "-1",
                    "-metadata:s:v:0", "rotate=0", str(destination)]
                encoded = subprocess.run(command, capture_output=True, text=True, timeout=600)
                if encoded.returncode:
                    row = dict(status=None, events=None, elapsed_sec=None,
                               note="FFmpeg failed: " + encoded.stderr[-1000:])
                else:
                    row = observe(client, base, destination)
                row.update(video=number, variation=name, ffmpeg_filter=expression)
                rows.append(row)
                (output / "results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
                (output / "report.md").write_text(markdown(rows, health), encoding="utf-8")
                print(json.dumps(row), flush=True)
    return int(any(r.get("status") != 200 or r.get("events") is None for r in rows))


if __name__ == "__main__":
    raise SystemExit(main())
