"""One launcher: Linux native backend, or Docker backend with Windows ML hosts."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_events import read_json, validate_payload, validate_rules
from scripts.run_chain import local_processes, open_videos, poll_job, require_free_ports, wait_health, write_json


def require_runtime(runtime: str, platform: str = os.name) -> str:
    selected = ('docker' if platform == 'nt' else 'native') if runtime == 'auto' else runtime
    if selected == 'native' and platform == 'nt':
        raise RuntimeError('Backend requires Linux (resource/SIGXFSZ). Install WSL2/Docker Desktop or use a Linux machine.')
    if selected == 'docker':
        if shutil.which('docker') is None:
            raise RuntimeError('Docker Desktop is unavailable. Install/start its Linux engine, or use a Linux machine. Nothing was started.')
        result = subprocess.run(['docker','info','--format','{{.OSType}}'],
            capture_output=True, text=True, timeout=15)
        if result.returncode or result.stdout.strip() != 'linux':
            raise RuntimeError('A running Linux Docker engine is required; nothing was started')
    return selected


def prepare_native_backend(output: Path) -> Path:
    """Patch only an ignored source copy; never edit backend/app in the checkout."""
    output = output.resolve()
    if not output.is_relative_to((ROOT/'cache').resolve()):
        raise ValueError('Backend test copy must be inside ignored ml2/cache')
    source = output/'source'
    source.mkdir(exist_ok=False)
    shutil.copytree(ROOT.parent/'backend/app', source/'backend/app',
                    ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copytree(ROOT.parent/'contracts/fixtures', source/'contracts/fixtures')
    subprocess.run(['git','apply','--directory='+source.relative_to(ROOT.parent).as_posix(),
        'ml2/patches/backend-ml-timeouts.patch'],cwd=ROOT.parent,check=True,capture_output=True)
    return source/'backend'


def docker_command(image: str, name: str, rules: Path, storage: Path) -> list[str]:
    if any(',' in str(path) for path in (rules, storage)):
        raise ValueError('Docker bind mount paths must not contain commas')
    command = ['docker','run','--detach','--rm','--pull','never','--name',name,
        '--publish','127.0.0.1:8000:8000',
        '--mount',f'type=bind,source={rules},target=/app/catalog.json,readonly',
        '--mount',f'type=bind,source={storage},target=/app/storage']
    for variable in ('API_KEY','PIPELINE_MODE','WORKERS','ML1_URL','ML2_URL','RULES_PATH','STORAGE_DIR'):
        command += ['--env',variable]  # Pass values in the child environment, not argv/files.
    return command+[image]


def check_open(client: httpx.Client, root: Path, numbers: list[int], output: Path,
               key: str, rules: list[dict], expect_empty: bool) -> bool:
    rows = []
    for number, path in open_videos(root,numbers):
        started = time.perf_counter()
        with path.open('rb') as video:
            response = client.post('http://127.0.0.1:8000/api/v1/analyze',
                headers={'X-API-Key':key}, files={'file':(path.name,video,
                    'video/mp4' if path.suffix.lower()=='.mp4' else 'video/quicktime')})
        if response.status_code != 202:
            raise RuntimeError(f'Backend upload failed: HTTP {response.status_code}')
        job = poll_job(client,'http://127.0.0.1:8000/api/v1/jobs/'+response.json()['job_id'],
                       {'X-API-Key':key},310)
        write_json(output/f'{number:02}.job.json',job)
        row = dict(video=number,status=job['status'],verdict=job.get('verdict'),
            events=len(job.get('violations',[])),wall_sec=round(time.perf_counter()-started,3),
            error_code=job.get('error_code'))
        try:
            validate_payload(job,kind='job',rules=rules,expect_empty=expect_empty)
            row['valid'] = True
        except ValueError as error:
            row.update(valid=False,error=str(error))
        rows.append(row)
        print(json.dumps(row),flush=True)
    write_json(output/'report.json',dict(success=all(row['valid'] for row in rows),videos=rows))
    return all(row['valid'] for row in rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',choices=['auto','native','docker'],default='auto')
    parser.add_argument('--image',default='cashier-guard-backend-ml2:timeouts-v2')
    parser.add_argument('--models',type=Path,required=True)
    parser.add_argument('--rules-path',type=Path,required=True)
    parser.add_argument('--backend-python',type=Path,default=ROOT.parent/'backend/.venv/bin/python')
    parser.add_argument('--ffmpeg-bin',type=Path)
    parser.add_argument('--open-root',type=Path,help='Optional open-set test; otherwise serve until Ctrl+C')
    parser.add_argument('--videos',type=int,nargs='+',default=[2,14])
    parser.add_argument('--expect-empty',action='store_true')
    args = parser.parse_args(argv)
    try:
        runtime = require_runtime(args.runtime)
        key = os.environ.get('API_KEY','')
        if not key.strip() or key == 'replace-with-your-own-key':
            raise ValueError('Set API_KEY in the environment; it will not be printed or saved')
        models = args.models.resolve(strict=True)
        rules_path = args.rules_path.resolve(strict=True)
        catalog = list(validate_rules(read_json(rules_path)['rules']).values())
        if args.open_root:
            open_videos(args.open_root,args.videos)  # Refuse non-open inputs before starting services.
        env = os.environ.copy()
        env.update(PIPELINE_MODE='live',WORKERS='1',ML_MODELS_DIR=str(models),
            HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',PYTHONUTF8='1')
        if args.ffmpeg_bin:
            env['PATH'] = str(args.ffmpeg_bin.resolve(strict=True))+os.pathsep+env.get('PATH','')
        if runtime == 'native':
            for binary in ('ffmpeg','ffprobe'):
                if not shutil.which(binary,path=env.get('PATH')):
                    raise ValueError(f'{binary} is required for Linux backend')
            backend_python = args.backend_python.resolve(strict=True)
        else:
            subprocess.run(['docker','image','inspect',args.image],check=True,capture_output=True)
        require_free_ports([8000,8001,8002])
        output = ROOT/'cache/jury'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        output.mkdir(parents=True,exist_ok=False)
        storage = output/'storage';storage.mkdir()
        host = 'host.docker.internal' if runtime=='docker' else '127.0.0.1'
        env.update(ML1_URL=f'http://{host}:8001',ML2_URL=f'http://{host}:8002',
            RULES_PATH='/app/catalog.json' if runtime=='docker' else str(rules_path),
            STORAGE_DIR='/app/storage' if runtime=='docker' else str(storage))
        backend = prepare_native_backend(output) if runtime=='native' else None
        container = 'cashier-guard-ml2-'+uuid.uuid4().hex[:12]
        container_attempted = False
        with local_processes(env,output) as (start,processes):
            try:
                bind = '0.0.0.0' if runtime=='docker' else '127.0.0.1'
                start(Path(sys.executable),'service.app:app',ROOT,8001,'ml1',host=bind)
                start(Path(sys.executable),'scripts.matching_stub:app',ROOT,8002,'matching_stub',host=bind)
                if runtime=='native':
                    start(backend_python,'app.main:app',backend,8000,'backend')
                else:
                    container_attempted = True
                    subprocess.run(docker_command(args.image,container,rules_path,storage),
                                   env=env,check=True,capture_output=True,timeout=30)
                with httpx.Client(trust_env=False,timeout=190) as client:
                    health = {str(port): wait_health(client,
                        f'http://127.0.0.1:{port}'+('/api/v1/health' if port==8000 else '/health'),processes)
                        for port in (8001,8002,8000)}
                    response = client.get('http://127.0.0.1:8000/api/v1/ready')
                    response.raise_for_status()
                    readiness = response.json()
                    if not readiness.get('ready'):
                        raise RuntimeError('Backend cannot reach ML hosts or catalog; inspect /api/v1/ready and host firewall')
                    write_json(output/'health.json',dict(health=health,readiness=readiness))
                    print(json.dumps(dict(ready=True,ports=[8000,8001,8002],matching_stub=True,
                        ml1_url=env['ML1_URL'],ml2_url=env['ML2_URL'])),flush=True)
                    if args.open_root:
                        return 0 if check_open(client,args.open_root,args.videos,output,key,catalog,args.expect_empty) else 1
                    while True:
                        time.sleep(1)
                        if any(p.poll() is not None for p in processes):
                            raise RuntimeError('A host service exited; inspect cache/jury logs')
                        if runtime=='docker':
                            state = subprocess.run(['docker','inspect','--format','{{.State.Running}}',container],
                                capture_output=True,text=True,timeout=10)
                            if state.returncode or state.stdout.strip()!='true':
                                raise RuntimeError('Backend container exited')
            finally:
                if container_attempted:
                    with (output/'backend.log').open('wb') as log:
                        subprocess.run(['docker','logs',container],stdout=log,stderr=subprocess.STDOUT,timeout=10)
                    subprocess.run(['docker','stop','--time','5',container],capture_output=True,timeout=15)
    except KeyboardInterrupt:
        return 0
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError,httpx.HTTPError) as error:
        # CalledProcessError includes argv, which contains environment names only.
        print(json.dumps(dict(ready=False,error=str(error))),flush=True)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
