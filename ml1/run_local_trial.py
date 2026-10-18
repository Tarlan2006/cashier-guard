"""Run a bounded, offline visual-model trial. Print technical metrics only.

Frames and model text are written only under the git-ignored ml1/local directory.
This is a sparse-sampling experiment, not a complete video review or ML1 API.
"""
import argparse
import contextlib
import datetime
import html
import json
import math
import os
from pathlib import Path
import resource
import socket
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL = ROOT / 'models' / 'Qwen3-VL-2B-Instruct-4bit'


def write_json(path, data):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def offline_only():
    os.environ.update({
        'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
        'HF_HUB_DISABLE_TELEMETRY': '1', 'DO_NOT_TRACK': '1',
        'TOKENIZERS_PARALLELISM': 'false', 'OMP_NUM_THREADS': '2',
        'HF_HOME': str(ROOT / 'local' / 'hf-offline'),
    })
    original_socket = socket.socket

    def blocked(*args, **kwargs):
        raise OSError('Network connections are disabled during this local trial')

    class OfflineSocket(original_socket):
        def connect(self, address):
            return blocked()

        def connect_ex(self, address):
            return blocked()

    socket.socket = OfflineSocket
    socket.create_connection = blocked
    socket.getaddrinfo = blocked


def extract_frames(video, folder, count, image_size):
    import av
    frames = []
    with av.open(str(video)) as container:
        stream = container.streams.video[0]
        stream.thread_count = 2
        duration = float(stream.duration * stream.time_base) if stream.duration else float(container.duration / av.time_base)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError('Invalid duration')
        origin = float((stream.start_time or 0) * stream.time_base)
        # Stay away from the exact duration: it is not an addressable video frame.
        last = max(0, duration - 0.1)
        targets = [i * last / (count - 1) for i in range(count)]
        for frame in container.decode(stream):
            if frame.pts is None:
                continue
            timestamp = float(frame.pts * frame.time_base) - origin
            if timestamp < targets[len(frames)] or timestamp >= duration:
                continue
            picture = frame.to_image().convert('RGB')
            picture.thumbnail((image_size, image_size))
            name = f'frame-{len(frames):02d}.jpg'
            picture.save(folder / name, quality=90)
            frames.append({'index': len(frames), 'timestamp_sec': round(timestamp, 6), 'file': name})
            if len(frames) == count:
                break
    if len(frames) < 2:
        raise ValueError('Too few decoded frames')
    return duration, frames


def synthetic_frames(folder):
    from PIL import Image, ImageDraw
    frames = []
    for i, x in enumerate((40, 220)):
        picture = Image.new('RGB', (384, 256), 'white')
        ImageDraw.Draw(picture).rectangle((x, 90, x + 70, 160), fill='blue')
        name = f'frame-{i:02d}.jpg'
        picture.save(folder / name, quality=95)
        frames.append({'index': i, 'timestamp_sec': float(i), 'file': name})
    return 2.0, frames


def parse_observations(text, frames):
    cleaned = text.strip()
    if cleaned.startswith('```'):
        lines = cleaned.splitlines()
        if lines[-1].strip() == '```':
            cleaned = '\n'.join(lines[1:-1])
    payload = json.loads(cleaned)
    if not isinstance(payload, dict) or not isinstance(payload.get('observations'), list):
        raise ValueError('Response must contain an observations array')
    uncertainties = payload.get('uncertainties', [])
    if not isinstance(uncertainties, list) or any(not isinstance(x, str) for x in uncertainties):
        raise ValueError('Invalid uncertainties')
    events = []
    if len(payload['observations']) > 10:
        raise ValueError('Too many observations for a small trial')
    for i, item in enumerate(payload['observations']):
        start, end = item['start_frame'], item['end_frame']
        indices = item['evidence_frame_indices']
        if type(start) is not int or type(end) is not int or not 0 <= start <= end < len(frames):
            raise ValueError('Invalid observation frame interval')
        if not isinstance(indices, list) or not 1 <= len(indices) <= 3:
            raise ValueError('Invalid evidence count')
        if len(set(indices)) != len(indices) or any(type(x) is not int or not start <= x <= end for x in indices):
            raise ValueError('Invalid evidence indices')
        description = item['description']
        if not isinstance(description, str) or not description.strip():
            raise ValueError('Missing description')
        events.append({
            'id': f'trial-{i+1}',
            'start_sec': frames[start]['timestamp_sec'], 'end_sec': frames[end]['timestamp_sec'],
            'description': description,
            'evidence_frames_local': [frames[j] for j in indices],
            'review_status': 'needs_review',
        })
    return {'purpose': 'local_trial_not_ground_truth', 'events': events, 'uncertainties': uncertainties}


def create_report(folder, status, frames, text):
    esc = html.escape
    cards = ''.join(
        f'<figure><img src="{esc(f["file"], quote=True)}" alt="Кадр {f["index"]}">'
        f'<figcaption>Кадр {f["index"]} · {f["timestamp_sec"]:.3f} с</figcaption></figure>'
        for f in frames
    )
    document = f'''<!doctype html><html lang="ru"><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Локальный пробный анализ</title>
<style>body{{font:16px system-ui;margin:32px auto;padding:0 24px;max-width:1100px;color:#17212b;background:#f6f8fb}}
h1{{font-size:28px}}.notice{{background:#fff2d6;padding:18px;border-radius:12px;line-height:1.6}}
.frames{{display:flex;flex-wrap:wrap;gap:16px}}figure{{margin:0;background:white;padding:12px;border-radius:12px}}
img{{max-height:320px;max-width:100%}}figcaption{{padding-top:8px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:white;padding:20px;border-radius:12px;line-height:1.6}}</style>
<h1>Локальный пробный анализ</h1>
<p class="notice">Это эксперимент по редкой выборке кадров, а не полный разбор видео и не юридическое заключение.
Действия между выбранными кадрами могут быть пропущены. Ответ модели требует проверки человеком.
Пустой список событий здесь не означает отсутствие нарушения.</p>
<p>Статус: {esc(status['status'])}. Выбрано кадров: {len(frames)}. Время: {status.get('elapsed_sec',0):.1f} с.
Сетевые обращения из процесса анализа отключены.</p>
<h2>Выбранные кадры</h2><div class="frames">{cards}</div>
<h2>Черновой ответ локальной модели</h2><pre>{esc(text)}</pre></html>'''
    (folder / 'report.html').write_text(document)


def worker(args):
    offline_only()
    folder = Path(args.output).resolve()
    start = time.monotonic()
    status = {'status': 'running', 'phase': 'imports', 'network_disabled': True,
              'coverage': 'sparse_sample_not_full_review', 'synthetic': args.synthetic}
    write_json(folder / 'status.json', status)
    try:
        import mlx.core as mx
        from mlx_vlm import load, generate
        from mlx_vlm.prompt_utils import apply_chat_template
        from PIL import Image

        if not mx.metal.is_available():
            raise RuntimeError('Apple Metal is not available')
        info = mx.metal.device_info()
        limit = min(4 * 2**30, int(info['max_recommended_working_set_size'] * 0.85))
        mx.set_memory_limit(limit)
        mx.set_cache_limit(128 * 2**20)
        status.update({'phase': 'frames', 'mlx_memory_limit_bytes': limit})
        write_json(folder / 'status.json', status)
        if args.synthetic:
            duration, frames = synthetic_frames(folder)
        else:
            duration, frames = extract_frames(Path(args.video), folder, args.frames, args.image_size)
        write_json(folder / 'frames.json', {'duration_sec': duration, 'frames': frames})
        status.update({'phase': 'loading_model', 'frame_count': len(frames), 'duration_sec': duration})
        write_json(folder / 'status.json', status)
        load_start = time.monotonic()
        model, processor = load(str(Path(args.model).resolve()), trust_remote_code=False, local_files_only=True)
        status.update({'phase': 'inference', 'load_sec': round(time.monotonic()-load_start,3)})
        write_json(folder / 'status.json', status)
        times = ', '.join(f'{f["index"]}={f["timestamp_sec"]:.3f}s' for f in frames)
        prompt = (
            'Inspect these sampled frames in chronological order. Frame indices and timestamps: '+times+'. '
            'Describe only directly visible actions or changes between the provided frames. '
            'Use Russian for descriptions. Do not identify people, infer intent, or make legal conclusions. '
            'Do not infer that an action did not happen between sampled frames. '
            'Unclear objects or actions belong in uncertainties. '
            'Return only a JSON object, without markdown: '
            '{"observations":[{"start_frame":0,"end_frame":1,"description":"visible action",'
            '"evidence_frame_indices":[0,1]}],"uncertainties":["uncertainty"]}. '
            'Frame indices must refer to the supplied frames, evidence indices must lie inside the event interval. '
            'Each observation needs 1 to 3 evidence indices. Empty observations is allowed. '
            'At most three brief observations. No text outside JSON.'
        )
        formatted = apply_chat_template(processor, model.config, prompt, num_images=len(frames))
        images = [Image.open(folder / f['file']).convert('RGB') for f in frames]
        inference_start = time.monotonic()
        result = generate(model, processor, formatted, image=images, max_tokens=args.max_tokens,
                          temperature=0.0, verbose=False)
        model_text = result.text
        (folder / 'model_response.txt').write_text(model_text)
        status.update({'inference_sec': round(time.monotonic()-inference_start,3),
                       'elapsed_sec': round(time.monotonic()-start,3),
                       'peak_mlx_GiB': round(mx.get_peak_memory()/2**30,3),
                       'peak_process_GiB': round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/2**30,3),
                       'generation_tokens': int(getattr(result,'generation_tokens',0))})
        try:
            observations = parse_observations(model_text, frames)
            write_json(folder / 'observations.local.json', observations)
            status.update({'status': 'completed', 'phase': 'done', 'structured_output_valid': True})
        except (ValueError, KeyError, TypeError):
            status.update({'status': 'completed_unstructured', 'phase': 'done', 'structured_output_valid': False})
        write_json(folder / 'status.json', status)
        create_report(folder, status, frames, model_text)
        return 0 if status['structured_output_valid'] else 2
    except Exception as error:
        status.update({'status': 'failed', 'error_type': type(error).__name__,
                       'elapsed_sec': round(time.monotonic()-start,3)})
        write_json(folder / 'status.json', status)
        (folder / 'error.local.txt').write_text(traceback.format_exc())
        return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path)
    parser.add_argument('--synthetic', action='store_true')
    parser.add_argument('--model', type=Path, default=DEFAULT_MODEL)
    parser.add_argument('--frames', type=int, default=6)
    parser.add_argument('--image-size', type=int, default=448)
    parser.add_argument('--max-tokens', type=int, default=384)
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--output', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if bool(args.video) == args.synthetic:
        parser.error('Choose exactly one of --video or --synthetic')
    if not 2 <= args.frames <= 8 or not 224 <= args.image_size <= 512 or not 64 <= args.max_tokens <= 768 or not 30 <= args.timeout <= 300:
        parser.error('Trial limits: 2–8 frames, 224–512 px, 64–768 tokens, 30–300 seconds')
    if not args.model.is_dir() or not (args.model/'model.safetensors').is_file():
        parser.error('Download model weights first')
    if args.video and not args.video.is_file():
        parser.error('Video file does not exist')
    if args.worker:
        with (args.output / 'worker.local.log').open('w') as log:
            with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                return worker(args)
    folder = ROOT/'local'/('trial-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'))
    folder.mkdir(parents=True)
    command = [sys.executable,str(Path(__file__).resolve()),*sys.argv[1:],'--worker','--output',str(folder)]
    print('Trial directory:',folder,flush=True)
    print('Only technical status is printed. Frames and model text remain local.',flush=True)
    try:
        with (folder/'process.local.log').open('w') as log:
            completed = subprocess.run(command, stdout=log, stderr=log, timeout=args.timeout)
        code = completed.returncode
    except subprocess.TimeoutExpired:
        code = 124
        status_path = folder/'status.json'
        status = json.loads(status_path.read_text()) if status_path.exists() else {}
        status.update({'status':'timeout','timeout_sec':args.timeout})
        write_json(status_path,status)
    status_path = folder/'status.json'
    if status_path.exists():
        status=json.loads(status_path.read_text())
        if status.get('status')=='running':
            status.update({'status':'worker_exited','exit_code':code})
            write_json(status_path,status)
        print(json.dumps(status,ensure_ascii=False,indent=2),flush=True)
    else:
        print('Worker exited before status was written. Exit code:',code,flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
