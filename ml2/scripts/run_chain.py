"""Run local ML1 -> matching STUB -> live backend on authorized data/open videos."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time

import httpx

# Support both `python scripts/run_chain.py` and `python -m scripts.run_chain`.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_events import ContractError, read_json, validate_payload, validate_rules

REPO = ROOT.parent


def open_videos(open_root: Path, numbers: list[int]) -> list[tuple[int, Path]]:
    root = open_root.resolve(strict=True)
    if root.name != 'open' or root.parent.name != 'data':
        raise ValueError('Only the authorized data/open directory is supported')
    files = {}
    for path in (root/'videos').iterdir():
        found = re.fullmatch(r'[X\u0425x\u0445]-(\d+)', path.stem)
        if not found or path.suffix.lower() not in {'.mov', '.mp4'}:
            continue
        number = int(found[1])
        if number not in numbers:
            continue
        if not path.resolve(strict=True).is_relative_to(root):
            raise ValueError('Video escaped the authorized open directory')
        if number in files:
            raise ValueError(f'Multiple files have video number {number}')
        files[number] = path
    if len(numbers) != len(set(numbers)) or any(n not in files for n in numbers):
        raise ValueError('Video numbers must be unique and present in data/open/videos')
    return [(n, files[n]) for n in numbers]


def require_free_ports(ports: list[int]) -> None:
    if len(ports) != len(set(ports)) or any(not 1 <= p <= 65535 for p in ports):
        raise ValueError('Service ports must be distinct and between 1 and 65535')
    for port in ports:
        with socket.socket() as connection:
            if os.name == 'nt':
                connection.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                connection.bind(('127.0.0.1', port))
            except OSError:
                raise RuntimeError(f'Port {port} is occupied; no existing process was stopped') from None


@contextmanager
def local_processes(environment: dict, output: Path):
    processes = []
    logs = []
    def start(python: Path, module: str, cwd: Path, port: int, name: str):
        log = (output/f'{name}.log').open('w', encoding='utf-8')
        logs.append(log)
        process = subprocess.Popen([str(python), '-X', 'utf8', '-m', 'uvicorn', module,
            '--host', '127.0.0.1', '--port', str(port), '--workers', '1', '--no-access-log'],
            cwd=cwd, env=environment, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            start_new_session=os.name != 'nt')
        processes.append(process)
    try:
        yield start, processes
    finally:
        for process in reversed(processes):
            if process.poll() is not None:
                continue
            if os.name == 'nt':
                # Only a process started here, including its resident model child.
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW, timeout=15, check=False)
            else:
                import signal
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name != 'nt':
                    import signal
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                process.wait(timeout=5)
        for log in logs:
            log.close()


def wait_health(client: httpx.Client, url: str, processes: list,
                timeout: float = 60) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(p.poll() is not None for p in processes):
            raise RuntimeError('A child service exited; inspect local logs')
        try:
            response = client.get(url, timeout=1)
            if response.status_code == 200:
                return response.json()
        except httpx.HTTPError:
            pass
        time.sleep(.2)
    raise RuntimeError('Local service did not become ready: '+url)


def poll_job(client: httpx.Client, url: str, headers: dict, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        job = response.json()
        if job.get('status') in {'done', 'failed'}:
            return job
        if job.get('status') != 'processing':
            raise ContractError('Unexpected backend job status')
        time.sleep(.25)
    raise TimeoutError('Backend polling deadline reached')


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--open-root', type=Path, required=True)
    parser.add_argument('--videos', type=int, nargs='+', default=[2, 14])
    parser.add_argument('--rules-path', type=Path, required=True,
                        help='Explicit existing catalog; no automatic replacement of data/rules.json')
    parser.add_argument('--models', type=Path)
    parser.add_argument('--ffmpeg-bin', type=Path)
    parser.add_argument('--backend-python', type=Path,
        default=REPO/('backend/.venv/Scripts/python.exe' if os.name == 'nt' else 'backend/.venv/bin/python'))
    parser.add_argument('--backend-dir', type=Path, default=REPO/'backend',
                        help='Also supports a separately patched test copy')
    parser.add_argument('--existing-ml1', action='store_true')
    parser.add_argument('--direct-ml1', action='store_true', help='Also POST each source video to ML1 before the chain')
    parser.add_argument('--backend-port', type=int, default=8000)
    parser.add_argument('--ml1-port', type=int, default=8001)
    parser.add_argument('--matching-port', type=int, default=8002)
    parser.add_argument('--poll-timeout', type=float, default=310)
    parser.add_argument('--expect-empty', action='store_true', help='Assert disabled-rules behavior, not video accuracy')
    parser.add_argument('--output-dir', type=Path,
        default=ROOT/'cache/chain'/datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    created = False
    report = dict(success=False, matching_stub=True, backend_code_modified=False, videos=[])
    try:
        if not output.is_relative_to((ROOT/'cache').resolve()):
            raise ValueError('Reports, logs and evidence must stay inside ignored ml2/cache')
        output.mkdir(parents=True, exist_ok=False)
        created = True
        files = open_videos(args.open_root, args.videos)
        rules = list(validate_rules(read_json(args.rules_path)['rules']).values())
        if not args.poll_timeout > 0 or not math.isfinite(args.poll_timeout):
            raise ValueError('Polling timeout must be finite and positive')
        ports = [args.backend_port, args.ml1_port, args.matching_port]
        # Validate all three even when ML1 is an existing service.
        if len(set(ports)) != 3 or any(not 1 <= p <= 65535 for p in ports):
            raise ValueError('Service ports must be distinct and between 1 and 65535')
        require_free_ports([p for p in ports if not (args.existing_ml1 and p == args.ml1_port)])
        key = secrets.token_urlsafe(32)
        env = os.environ.copy()
        env.update(API_KEY=key, PIPELINE_MODE='live', WORKERS='1',
            ML1_URL=f'http://127.0.0.1:{args.ml1_port}',
            ML2_URL=f'http://127.0.0.1:{args.matching_port}',
            STORAGE_DIR=str(output/'storage'), RULES_PATH=str(args.rules_path.resolve()),
            PYTHONUTF8='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1')
        if args.models:
            env['ML_MODELS_DIR'] = str(args.models.resolve(strict=True))
        if args.ffmpeg_bin:
            env['PATH'] = str(args.ffmpeg_bin.resolve(strict=True)) + os.pathsep + env.get('PATH', '')
        for binary in ('ffmpeg', 'ffprobe'):
            if not shutil.which(binary, path=env.get('PATH')):
                raise ValueError(f'{binary} is unavailable; pass --ffmpeg-bin')
        backend_dir = args.backend_dir.resolve(strict=True)
        backend_python = args.backend_python.resolve(strict=True)
        report.update(rules_catalog_count=len(rules),
            transport_catalog_only=bool(read_json(args.rules_path).get('integration_test_only')),
            backend_test_copy=backend_dir != (REPO/'backend').resolve(),
            existing_ml1=args.existing_ml1)
        base = f'http://127.0.0.1:{args.backend_port}'
        ml1 = env['ML1_URL']
        with local_processes(env, output) as (start, processes):
            if not args.existing_ml1:
                start(Path(sys.executable), 'service.app:app', ROOT, args.ml1_port, 'ml1')
            start(Path(sys.executable), 'scripts.matching_stub:app', ROOT, args.matching_port, 'matching_stub')
            start(backend_python, 'app.main:app', backend_dir, args.backend_port, 'backend')
            with httpx.Client(trust_env=False, timeout=190, follow_redirects=False) as client:
                report['ml1_health'] = wait_health(client, ml1+'/health', processes)
                matching = wait_health(client, env['ML2_URL']+'/health', processes)
                if matching.get('stub') is not True:
                    raise RuntimeError('Expected the explicit matching transport stub')
                wait_health(client, base+'/api/v1/health', processes)
                for number, path in files:
                    record = dict(video=number, success=False)
                    try:
                        if args.direct_ml1:
                            started = time.perf_counter()
                            with path.open('rb') as stream:
                                response = client.post(ml1+'/analyze', files={'file': (path.name,stream,
                                    'video/mp4' if path.suffix.lower() == '.mp4' else 'video/quicktime')})
                            record['direct_ml1_sec'] = round(time.perf_counter()-started, 3)
                            record['direct_ml1_http'] = response.status_code
                            record['direct_ml1_headers'] = {k:v for k,v in response.headers.items() if k.startswith('x-')}
                            response.raise_for_status()
                            body = response.json()
                            write_json(output/f'{number:02}.ml1.json', body)
                            if (response.headers.get('x-analysis-status','').lower() in {'partial','incomplete'}
                                or response.headers.get('x-analysis-complete','').lower() in {'false','0','no'}):
                                raise ContractError('ML1 reports incomplete processing')
                            validate_payload(body, kind='ml1', expect_empty=args.expect_empty)
                        started = time.perf_counter()
                        with path.open('rb') as stream:
                            response = client.post(base+'/api/v1/analyze', headers={'X-API-Key':key},
                                files={'file':(path.name,stream,
                                    'video/mp4' if path.suffix.lower()=='.mp4' else 'video/quicktime')})
                        record['post_http'] = response.status_code
                        if response.status_code != 202:
                            raise ContractError('Backend did not accept the upload (expected HTTP 202)')
                        identifier = response.json()['job_id']
                        job = poll_job(client, base+'/api/v1/jobs/'+identifier,
                                       {'X-API-Key':key}, args.poll_timeout)
                        write_json(output/f'{number:02}.job.json', job)
                        record.update(wall_sec=round(time.perf_counter()-started,3), status=job['status'],
                            verdict=job.get('verdict'), error_code=job.get('error_code'),
                            timings_sec=job.get('timings_sec'), event_count=len(job.get('violations',[])))
                        validate_payload(job, kind='job', rules=rules, expect_empty=args.expect_empty)
                        record['success'] = True
                    except (ValueError, OSError, KeyError, RuntimeError, TimeoutError, httpx.HTTPError) as error:
                        record['error'] = str(error)
                    report['videos'].append(record)
                    print(json.dumps(record,ensure_ascii=False),flush=True)
                report['success'] = all(row['success'] for row in report['videos'])
    except (ValueError, OSError, KeyError, RuntimeError, httpx.HTTPError) as error:
        report['error'] = str(error)
        print(json.dumps(dict(success=False,error=str(error))),flush=True)
    finally:
        if created:
            write_json(output/'report.json',report)
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
