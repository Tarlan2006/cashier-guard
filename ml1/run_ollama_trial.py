"""Small local captioning trial on macOS. Only technical status is printed.

Requires an installed Ollama and already downloaded vision model in ml1/models/ollama.
Includes optional joint comparison of sampled frames; not full video or legal analysis.
"""
import argparse
import base64
import datetime
import html
import json
import math
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import time
import traceback
import urllib.request
import urllib.error
import zlib

ROOT = Path(__file__).resolve().parent
SMOL_MODEL = 'ahmadwaqar/smolvlm2-256m-video:q8_0'
QWEN_MODEL = 'qwen3-vl:2b-instruct'
MODEL = QWEN_MODEL  # Replacement selected by the user; never silently fall back to SmolVLM.
LOCAL_OLLAMA = ROOT/'local'/'runtime'/'ollama-v0.40.5'/'ollama'
CONTEXT_PREFIX = 'First image is the full scene; second image is a detail from the same moment. '
PROMPTS = {
    'general': 'Describe only what is directly visible in this image in one or two short sentences.',
    'hands': ('Describe the positions of visible hands and any small objects touching or held by them. '
              'Name an object only if its appearance is clear; otherwise say unclear. '
              'If no hands are visible, say so. Do not infer intentions or actions outside this image. '
              'Give one or two short sentences about these details rather than a general scene description.'),
    'bank-hands': (
        'This image is from a security camera at a bank cash desk during a banking transaction. '
        'The participants are a cashier and a customer. Objects may include banknotes, documents, cards and receipts. '
        'Focus on visible hands: their positions, what they hold or touch, and where each object is located '
        '(on the desk, on either side of the desk, near clothing or in storage). '
        'Identify objects from visible details; the bank setting alone does not prove that an object is money. '
        'If a hand or object is unclear, say unclear. Do not infer intent or movements between frames. '
        'Describe the hands and objects in two or three short sentences.'
    ),
    'bank-focus': ('This is a bank cash desk. Describe only the hands and the objects touching them. '
                   'Refer to the upper person and the lower person. Do not guess unreadable details. '
                   'If an object is unclear, say unclear. Use two short sentences.'),
}
SEQUENCE_PROMPT = (
    'These images show consecutive moments of a bank cash-desk transaction, in chronological order. '
    'Track hands and the same visible object across images. Identify the cashier by the workstation '
    'and the customer across the desk only when clear. For each image, say whose hand holds or touches '
    'the object and where the object is. Then report whether the object is merely offered, touched by '
    'both people, received by the other person, or whether transfer is unclear. '
    'An outstretched hand alone does not prove receipt. Identify banknotes only from visible details; '
    'otherwise call it an unclear object. Do not infer intent or wrongdoing. Give a brief comparison.'
)
SYNTHETIC_SEQUENCE_PROMPT = (
    'These images are in chronological order. Describe the position of the colored shape '
    'in the first and second images. Does it shift left, right, or stay in the same position? '
    'Use only what is visible. Give a brief comparison.'
)


def write_json(path, data):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def synthetic_frames(folder, color=(0, 0, 255)):
    """Make two artificial PNGs with stdlib only; no dataset or extra packages."""
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    frames = []
    for index, left in enumerate((40, 220)):
        rows = bytearray()
        for y in range(256):
            rows.append(0)
            for x in range(384):
                rows.extend(color if left <= x <= left + 70 and 90 <= y <= 160 else (255, 255, 255))
        png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', 384, 256, 8, 2, 0, 0, 0))
        png += chunk(b'IDAT', zlib.compress(bytes(rows))) + chunk(b'IEND', b'')
        name = f'frame-{index:02d}.png'
        (folder/name).write_bytes(png)
        frames.append({'index': index, 'timestamp_sec': float(index), 'file': name})
    return 2.0, frames


def request(port, endpoint, payload=None, timeout=120):
    # A fixed loopback address and disabled proxies keep inputs on this machine.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(f'http://127.0.0.1:{port}/api/{endpoint}', data=body,
                                 headers={'Content-Type': 'application/json'})
    with opener.open(req, timeout=timeout) as response:
        return json.load(response)


def process_tree_rss(server_pid):
    """RSS snapshot of this trial's server and children, not whole-system or peak RAM."""
    output = subprocess.check_output(['ps', '-axo', 'pid=,ppid=,rss='], text=True)
    rows = [tuple(map(int, line.split())) for line in output.splitlines() if line.strip()]
    included = {server_pid}
    while True:
        found = {pid for pid, parent, _ in rows if parent in included} - included
        if not found:
            break
        included.update(found)
    return sum(rss * 1024 for pid, _, rss in rows if pid in included)


def create_report(folder, status, frames, results):
    esc = html.escape
    def image_src(name):
        path = (folder/name).resolve()
        if not path.is_relative_to(folder.resolve()) or not path.is_file():
            raise ValueError('Invalid report image path')
        mime = 'image/jpeg' if path.suffix.lower() in ('.jpg', '.jpeg') else 'image/png'
        return 'data:'+mime+';base64,'+base64.b64encode(path.read_bytes()).decode('ascii')
    source_name = esc(status.get('source_name', 'Искусственные изображения'))
    window = status.get('requested_window_sec')
    window_note = ''
    if window:
        end = f'{window[1]:g} с' if window[1] is not None else 'конец видео'
        window_note = (f'<p class="note">Выбранный фрагмент: {window[0]:g} с — {end}. '
                       'Фрагмент задан заранее; это проверка описаний на выбранном участке, '
                       'а не автоматический поиск эпизода по всему ролику.</p>')
    cards = ''
    for f, r in zip(frames, results):
        context = (f'<details><summary>Полный кадр для проверки выбранной области</summary>'
                   f'<img src="{image_src(f["context_file"])}" alt="Полный кадр"></details>'
                   if f.get('context_file') else '')
        image_label = 'Выбранная область рук и стола' if f.get('context_file') else 'Полный кадр'
        details = ''.join(
            f'<section><h3>Увеличенный участок {i+1}</h3>'
            f'<img src="{image_src(v["file"])}" alt="Участок кадра">'
            f'<pre>{esc(v["response"])}</pre></section>'
            for i, v in enumerate(r.get('detail_views', []))
        )
        cards += (
            f'<article><h2>Кадр {f["index"]+1} · {f["timestamp_sec"]:.3f} с</h2>'
            f'{context}<p>{image_label}</p>'
            f'<img src="{image_src(f["file"])}" alt="Выбранный кадр">'
            f'<h3>Черновое описание изображения (английский)</h3><pre>{esc(r["response"])}</pre>'
            f'<div class="tiles">{details}</div></article>'
        )
    prompt_note = ''
    prompt_mode = status.get('prompt_mode', 'general')
    if prompt_mode in ('hands', 'bank-hands', 'bank-focus'):
        context_note = ('Модели заранее сообщили контекст банковской кассы. '
                        'Предметы нужно определять по изображению, а не только по контексту. '
                        if prompt_mode in ('bank-hands', 'bank-focus') else '')
        prompt_note = ('<p class="note">'+context_note+'Направленная проба: модель спрашивали о руках и предметах. '
                       'Увеличенные участки обработаны отдельно. Описание ожидаемого нарушения '
                       'не передавалось. Объединять ответы в подтверждённое действие без проверки нельзя.</p>'
                       f'<details><summary>Точный запрос модели</summary><pre>{esc((CONTEXT_PREFIX if status.get("include_context") else "") + PROMPTS[prompt_mode])}</pre></details>')
    sequence_section = ''
    if status.get('sequence_enabled'):
        sequence_path = folder/'sequence.local.json'
        if status.get('sequence_status') == 'completed' and sequence_path.is_file():
            sequence = json.loads(sequence_path.read_text())
            sequence_section = ('<article><h2>Сравнение последовательности кадров</h2>'
                '<p>Выбранные изображения переданы вместе в хронологическом порядке. '
                'Это черновое сравнение выбранных моментов; промежутки между ними могут скрывать действие.</p>'
                f'<pre>{esc(sequence["response"])}</pre>'
                f'<details><summary>Запрос для последовательности</summary><pre>{esc(sequence["prompt"])}</pre></details></article>')
        else:
            sequence_section = '<p class="note">Совместный анализ кадров технически не выполнен; ниже только отдельные описания.</p>'
    coverage_note = ('Выбранные полные кадры дополнительно переданы вместе для сравнения. '
                     if status.get('sequence_status') == 'completed' else
                     'Модель описывает каждый кадр отдельно. Действия между кадрами не проверены. ')
    (folder/'report.html').write_text(f'''<!doctype html><html lang="ru"><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Проба локальной модели</title>
<style>body{{font:16px system-ui;max-width:1000px;margin:32px auto;padding:0 24px;background:#f5f7fb;color:#14243a}}
article{{background:white;border-radius:16px;padding:24px;margin:24px 0}}img{{width:100%;max-width:640px}}
pre{{white-space:pre-wrap;line-height:1.6}}.note{{background:#fff0ce;padding:20px;border-radius:16px;line-height:1.6}}
h1{{font-size:30px}}h2{{font-size:20px}}h3{{font-size:16px}}</style>
<h1>Проба локальной модели</h1>
<p>Источник: <strong>{source_name}</strong></p>
<p>{esc(status['model'])} · {len(results)} кадров · {status.get('elapsed_sec', 0):.1f} с</p>
{window_note}
{prompt_note}
<p class="note">{coverage_note}
Это проверка запуска на этом Mac, а не полный анализ ролика и не подтверждённые нарушения.
Описания могут быть ошибочными; сравните их с изображениями самостоятельно.
Облачные функции Ollama отключены. Кадры и ответы сохранены локально и исключены из Git.</p>
<style>.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:20px}}.tiles section{{border-top:1px solid #d9e0ea;padding-top:12px}}</style>
{sequence_section}{cards}</html>''', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--video', type=Path)
    source.add_argument('--synthetic', action='store_true')
    parser.add_argument('--frames', type=int, choices=range(2, 9), default=4)
    parser.add_argument('--start-sec', type=float, default=0, help='Start of a manually selected video window')
    parser.add_argument('--end-sec', type=float, help='End of the video window; defaults to end of video')
    parser.add_argument('--image-size', type=int, choices=(448, 960, 1280), default=960)
    parser.add_argument('--prompt-mode', choices=tuple(PROMPTS), help='Default: bank-focus for video; general for synthetic input')
    parser.add_argument('--tiles', action='store_true', help='Also caption four overlapping crops per video frame')
    parser.add_argument('--sequence', action=argparse.BooleanOptionalAction, help='Compare selected moments together; enabled for video by default')
    parser.add_argument('--roi', type=float, nargs=4, metavar=('X', 'Y', 'W', 'H'),
                        help='Manually selected normalized image region; camera-specific')
    parser.add_argument('--port', type=int, default=11435)
    parser.add_argument('--ollama-bin', type=Path, help='Explicit local Ollama executable')
    parser.add_argument('--model', choices=(SMOL_MODEL, QWEN_MODEL), default=MODEL)
    parser.add_argument('--include-context', action='store_true', help='Send the full frame alongside each selected ROI')
    args = parser.parse_args()
    args.prompt_mode = args.prompt_mode or ('bank-focus' if args.video else 'general')
    args.sequence = args.sequence if args.sequence is not None else bool(args.video)
    selected_model = args.model
    if args.video and not args.video.is_file():
        parser.error('Video does not exist')
    if not math.isfinite(args.start_sec) or args.start_sec < 0:
        parser.error('Start must be a finite nonnegative timestamp')
    if args.end_sec is not None and (not math.isfinite(args.end_sec) or args.end_sec <= args.start_sec):
        parser.error('End must be finite and greater than start')
    if args.synthetic and (args.start_sec != 0 or args.end_sec is not None):
        parser.error('Time windows apply only to video')
    if args.synthetic and args.tiles:
        parser.error('Tile extraction applies only to video')
    if args.roi:
        x,y,w,h=args.roi
        if args.synthetic or not all(math.isfinite(v) for v in args.roi) or min(x,y)<0 or min(w,h)<=0 or x+w>1 or y+h>1:
            parser.error('ROI must be a valid normalized video region')
    if args.include_context and not args.roi:
        parser.error('Include-context requires a selected ROI')
    if not 1024 <= args.port <= 65535:
        parser.error('Invalid port')
    executable = str(args.ollama_bin.resolve()) if args.ollama_bin else (str(LOCAL_OLLAMA) if LOCAL_OLLAMA.is_file() else shutil.which('ollama'))
    if executable is None:
        parser.error('Ollama is not installed')
    with socket.socket() as probe:
        # A completed previous trial may leave TCP connections in TIME_WAIT.
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(('127.0.0.1', args.port))
        except OSError:
            parser.error('Trial port is occupied; stop the previous trial server first')
    folder = ROOT/'local'/('ollama-trial-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'))
    folder.mkdir(parents=True)
    status = {'status': 'running', 'phase': 'starting_server', 'model': selected_model,
              'synthetic': args.synthetic, 'cloud_disabled': True,
              'prompt_mode': args.prompt_mode, 'image_size_limit_px': args.image_size,
              'tiles_enabled': args.tiles, 'completed_views': 0,
              'sequence_enabled': args.sequence,
              'roi_normalized': args.roi,
              'include_context': args.include_context,
              'context_size': 4096 if selected_model=='qwen3-vl:2b-instruct' else 2048,
              'coverage': 'independent_sampled_frames_not_full_video_review'}
    if args.video:
        status['source_name'] = args.video.name
        if args.start_sec != 0 or args.end_sec is not None:
            status['requested_window_sec'] = [args.start_sec, args.end_sec]
    write_json(folder/'status.json', status)
    print('Trial directory:', folder, flush=True)
    start = time.monotonic()
    server = None
    results = []
    frames = []
    try:
        env = {k: v for k, v in os.environ.items() if not k.startswith('OLLAMA_')}
        env.update({'OLLAMA_HOST': f'127.0.0.1:{args.port}', 'OLLAMA_NO_CLOUD': '1',
                    'OLLAMA_MODELS': str(ROOT/'models'/'ollama'), 'OLLAMA_KEEP_ALIVE': '0',
                    'OLLAMA_MAX_LOADED_MODELS': '1', 'OLLAMA_NUM_PARALLEL': '1',
                    'OLLAMA_DEBUG_LOG_REQUESTS': 'false'})
        with (folder/'server.local.log').open('w') as log:
            server = subprocess.Popen([executable, 'serve'], env=env, stdout=log, stderr=log,
                                      stdin=subprocess.DEVNULL, start_new_session=True)
        status['server_pid'] = server.pid
        deadline = time.monotonic() + 60
        while True:
            if server.poll() is not None:
                raise RuntimeError('Local server exited')
            try:
                version = request(args.port, 'version', timeout=2)
                break
            except (OSError, ValueError):
                if time.monotonic() > deadline:
                    raise TimeoutError('Local server startup timed out')
                time.sleep(0.2)
        status['ollama_version'] = version['version']
        if 'Ollama cloud disabled: true' not in (folder/'server.local.log').read_text():
            raise RuntimeError('Cloud-disabled mode was not confirmed by the local server')
        tags = request(args.port, 'tags')['models']
        local = next((m for m in tags if m.get('name') == selected_model), None)
        if local is None:
            raise RuntimeError('Download the public model before running the trial')
        info = request(args.port, 'show', {'model': selected_model})
        if 'vision' not in info.get('capabilities', []) or local.get('remote_host') or info.get('remote_host'):
            raise RuntimeError('A local vision model is required')
        status['model_digest'] = local['digest']
        status['phase'] = 'extracting_frames'
        write_json(folder/'status.json', status)
        if args.synthetic:
            duration, frames = synthetic_frames(folder)
            write_json(folder/'frames.json', {'duration_sec': duration, 'frames': frames})
        else:
            binary = ROOT/'local'/'extract_trial_frames'
            swift = ROOT/'extract_trial_frames.swift'
            if not binary.is_file() or binary.stat().st_mtime < swift.stat().st_mtime:
                with (folder/'compile.local.log').open('w') as log:
                    subprocess.run(['xcrun', 'swiftc', '-O', str(swift), '-o', str(binary)],
                                   stdout=log, stderr=log, check=True, timeout=90)
            with (folder/'extract.local.log').open('w') as log:
                extract_command=[str(binary), str(args.video.resolve()), str(folder), str(args.frames), str(args.image_size),
                                str(args.start_sec), str(args.end_sec) if args.end_sec is not None else 'end',
                                'tiles' if args.tiles else 'full']
                if args.roi:
                    extract_command.extend(str(v) for v in args.roi)
                subprocess.run(extract_command,
                               stdout=log, stderr=log, check=True, timeout=60)
            metadata = json.loads((folder/'frames.json').read_text())
            duration, frames = metadata['duration_sec'], metadata['frames']
        status.update({'phase': 'inference', 'duration_sec': duration, 'frame_count': len(frames), 'completed_frames': 0})
        write_json(folder/'status.json', status)
        for frame in frames:
            answers = []
            for view in [{'file': frame['file']}, *frame.get('detail_views', [])]:
                filenames=[frame['context_file'], view['file']] if args.include_context else [view['file']]
                prompt = PROMPTS[args.prompt_mode]
                if args.include_context:
                    prompt = CONTEXT_PREFIX + prompt
                response = request(args.port, 'generate', {
                    'model': selected_model, 'prompt': prompt,
                    'images': [base64.b64encode((folder/name).read_bytes()).decode('ascii') for name in filenames],
                    'stream': False, 'keep_alive': '30s',
                    **({'think': False} if selected_model==QWEN_MODEL else {}),
                    'options': {'temperature': 0, 'seed': 1, 'num_predict': 1024 if selected_model==QWEN_MODEL else 96, 'num_ctx': status['context_size']},
                })
                if response.get('done_reason') == 'length':
                    write_json(folder/'truncated-response.local.json', response)
                    raise RuntimeError('Output token limit reached; description is incomplete')
                if not response.get('done') or not response.get('response', '').strip():
                    raise RuntimeError('Model returned no complete text')
                # Raw model text is deliberately never printed.
                answers.append({**view, 'response': response['response']})
                status['completed_views'] += 1
                metric = {key: response.get(key) for key in
                    ('total_duration', 'load_duration', 'prompt_eval_count', 'prompt_eval_duration', 'eval_count', 'eval_duration', 'done_reason')}
                metric.update({'frame_index': frame['index'], 'view_index': len(answers)-1})
                metric['input_image_count']=len(filenames)
                status.setdefault('frame_metrics', []).append(metric)
            results.append({'frame_index': frame['index'], 'timestamp_sec': frame['timestamp_sec'],
                            'response': answers[0]['response'], 'detail_views': answers[1:],
                            'review_status': 'needs_human_review'})
            write_json(folder/'captions.local.json', {'purpose': status['coverage'], 'captions': results})
            status['completed_frames'] = len(results)
            models = request(args.port, 'ps').get('models', [])
            status['loaded_model_bytes'] = max((m.get('size', 0) for m in models), default=0)
            status['loaded_model_vram_bytes'] = max((m.get('size_vram', 0) for m in models), default=0)
            status.setdefault('ollama_tree_rss_snapshots_bytes', []).append(process_tree_rss(server.pid))
            write_json(folder/'status.json', status)
            print(f'Completed frame {len(results)}/{len(frames)}', flush=True)
        if args.sequence:
            status['phase'] = 'sequence_inference'
            write_json(folder/'status.json', status)
            timestamps = ', '.join(f'image {i+1}: {f["timestamp_sec"]:.3f}s' for i, f in enumerate(frames))
            if args.prompt_mode == 'bank-focus' and not args.synthetic:
                prompt = ('These bank cash-desk images are in time order. Compare the hands and the same object. '
                          'Describe the visible change. Is the object offered, received, or is transfer unclear? '
                          'Do not infer intent. Use three short sentences.')
            else:
                prompt = (SYNTHETIC_SEQUENCE_PROMPT if args.synthetic else SEQUENCE_PROMPT) + ' Image order: ' + timestamps + '.'
            sequence_files=[]
            if args.include_context:
                pairs=[]
                for i,f in enumerate(frames):
                    sequence_files.extend([f['context_file'],f['file']])
                    pairs.append(f'images {2*i+1} and {2*i+2}: {f["timestamp_sec"]:.3f}s')
                prompt = ('Images are pairs: full scene then its detail at the SAME time. Pairs are in time order: '
                          +'; '.join(pairs)+'. '+prompt)
            else:
                sequence_files=[f['file'] for f in frames]
            try:
                sequence_context = max(status['context_size'], 1536*len(sequence_files)+512) if selected_model==QWEN_MODEL else status['context_size']
                status['sequence_context_size'] = sequence_context
                response = request(args.port, 'generate', {
                    'model': selected_model, 'prompt': prompt,
                    'images': [base64.b64encode((folder/name).read_bytes()).decode('ascii') for name in sequence_files],
                    'stream': False, 'keep_alive': '30s',
                    **({'think': False} if selected_model==QWEN_MODEL else {}),
                    'options': {'temperature': 0, 'seed': 1, 'num_predict': 1536 if selected_model==QWEN_MODEL else 256, 'num_ctx': sequence_context},
                })
                if response.get('done_reason') == 'length':
                    write_json(folder/'truncated-sequence.local.json', response)
                    raise RuntimeError('Output token limit reached; sequence description is incomplete')
                if not response.get('done') or not response.get('response', '').strip():
                    raise RuntimeError('No complete sequence response')
                write_json(folder/'sequence.local.json', {'prompt': prompt, 'response': response['response'],
                    'timestamps_sec': [f['timestamp_sec'] for f in frames], 'image_files': sequence_files,
                    'review_status': 'needs_human_review'})
                status['sequence_status'] = 'completed'
                status['coverage'] = 'sampled_frames_with_joint_comparison_not_full_video_review'
                status['sequence_metrics'] = {k: response.get(k) for k in
                    ('total_duration', 'prompt_eval_count', 'eval_count', 'done_reason')}
                status['sequence_metrics']['input_image_count']=len(sequence_files)
            except Exception as error:
                status['sequence_status'] = 'failed'
                status['sequence_error_type'] = type(error).__name__
                if isinstance(error, urllib.error.HTTPError):
                    status['sequence_http_status'] = error.code
                    (folder/'sequence_error.local.txt').write_bytes(error.read())
                else:
                    (folder/'sequence_error.local.txt').write_text(traceback.format_exc())
        status.update({'status': 'completed' if not args.sequence or status['sequence_status']=='completed' else 'completed_with_sequence_error', 'phase': 'done'})
    except Exception as error:
        status.update({'status': 'failed', 'error_type': type(error).__name__})
        (folder/'error.local.txt').write_text(traceback.format_exc(), encoding='utf-8')
    finally:
        if server is not None and server.poll() is None:
            try:
                request(args.port, 'generate', {'model': selected_model, 'keep_alive': 0}, timeout=5)
            except Exception:
                pass
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
        status['elapsed_sec'] = round(time.monotonic()-start, 3)
        status['server_stopped'] = server is None or server.poll() is not None
        write_json(folder/'status.json', status)
        if results:
            create_report(folder, status, frames, results)
        print(json.dumps(status, indent=2), flush=True)
    return 0 if status['status'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
