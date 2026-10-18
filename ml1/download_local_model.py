"""Download public model weights only. This command never opens dataset files."""
import hashlib
import json
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

MODEL_ID = 'mlx-community/Qwen3-VL-2B-Instruct-4bit'
DEFAULT_REVISION = '9c4f5209e57b31f4b9dfba735de3fb983739c9cc'
DEST = Path(__file__).resolve().parent / 'models' / 'Qwen3-VL-2B-Instruct-4bit'


def get_json(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def download_large(url, partial, size):
    """Resume verified HTTP byte ranges with bounded memory and eight connections."""
    chunk_size = 8 * 1024 * 1024
    total = (size + chunk_size - 1) // chunk_size
    state_path = partial.with_suffix(partial.suffix + '.chunks.json')
    if state_path.exists():
        state = json.loads(state_path.read_text())
        if state['url'] != url or state['size'] != size or state['chunk_size'] != chunk_size:
            raise RuntimeError('Download resume metadata mismatch')
        done = set(state['done'])
        if not partial.exists() or partial.stat().st_size != size:
            raise RuntimeError('Chunk file missing or truncated')
    else:
        prefix = partial.stat().st_size if partial.exists() else 0
        if prefix > size:
            raise RuntimeError('Partial file exceeds expected size')
        done = set(range(prefix // chunk_size))
        with partial.open('r+b' if partial.exists() else 'wb') as output:
            output.truncate(size)
        state = {'url': url, 'size': size, 'chunk_size': chunk_size, 'done': sorted(done)}
        state_path.write_text(json.dumps(state))

    def fetch(index):
        start, end = index * chunk_size, min(size, (index + 1) * chunk_size) - 1
        expected = f'bytes {start}-{end}/{size}'
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, headers={'Range': f'bytes={start}-{end}'})
                with urllib.request.urlopen(req, timeout=60) as response:
                    if response.status != 206 or response.headers.get('Content-Range') != expected:
                        raise RuntimeError('Server did not return the requested byte range')
                    data = response.read(end - start + 2)
                if len(data) != end - start + 1:
                    raise RuntimeError('Incomplete byte range')
                return index, data
            except (OSError, RuntimeError):
                if attempt == 3:
                    raise
                time.sleep(1 + attempt)

    print(f'Resuming weight download: {len(done)}/{total} chunks', flush=True)
    with partial.open('r+b') as output, ThreadPoolExecutor(max_workers=8) as pool:
        pending = {pool.submit(fetch, i): i for i in range(total) if i not in done}
        for future in as_completed(pending):
            index, data = future.result()
            output.seek(index * chunk_size)
            output.write(data)
            output.flush()
            done.add(index)
            state['done'] = sorted(done)
            temporary = state_path.with_suffix(state_path.suffix + '.tmp')
            temporary.write_text(json.dumps(state))
            temporary.replace(state_path)
            del pending[future]
            if len(done) % 8 == 0 or len(done) == total:
                print(f'Weights: {len(done)}/{total} chunks ({len(done)/total:.0%})', flush=True)
    return state_path


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    provenance = DEST / 'model_provenance.json'
    if provenance.exists():
        previous = json.loads(provenance.read_text())
        revision = previous['revision']
        if previous['model_id'] != MODEL_ID:
            raise RuntimeError('Model identity mismatch')
    else:
        revision = DEFAULT_REVISION
    files = get_json(f'https://huggingface.co/api/models/{MODEL_ID}/tree/{revision}?recursive=true&expand=false')
    manifest = {'model_id': MODEL_ID, 'revision': revision, 'files': []}
    for entry in files:
        name = entry['path']
        if entry['type'] != 'file' or name == '.gitattributes':
            continue
        if '/' in name or name in ('.', '..'):
            raise RuntimeError('Unexpected model file path')
        path = DEST / name
        expected_size = entry['size']
        expected_hash = entry.get('lfs', {}).get('oid')
        if path.exists() and path.stat().st_size == expected_size:
            actual_hash = sha256(path)
            if not expected_hash or actual_hash == expected_hash:
                manifest['files'].append({'path': name, 'size': expected_size, 'sha256': actual_hash})
                print(f'Verified {name}', flush=True)
                continue
        partial = path.with_name(path.name + '.part')
        url = f'https://huggingface.co/{MODEL_ID}/resolve/{revision}/{urllib.parse.quote(name)}'
        if expected_size > 256 * 1024 * 1024:
            state_path = download_large(url, partial, expected_size)
            actual_hash = sha256(partial)
            if expected_hash and actual_hash != expected_hash:
                raise RuntimeError('Download checksum mismatch')
            partial.replace(path)
            state_path.unlink()
            manifest['files'].append({'path': name, 'size': expected_size, 'sha256': actual_hash})
            print(f'Downloaded and verified {name}', flush=True)
            continue
        for attempt in range(3):
            try:
                offset = partial.stat().st_size if partial.exists() else 0
                if offset > expected_size:
                    raise RuntimeError('Partial file exceeds expected size')
                if offset < expected_size:
                    request = urllib.request.Request(url, headers={'Range': f'bytes={offset}-'} if offset else {})
                    with urllib.request.urlopen(request, timeout=90) as response:
                        if offset and response.status != 206:
                            offset = 0
                        mode = 'ab' if offset else 'wb'
                        next_progress = offset + 128 * 1024 * 1024
                        with partial.open(mode) as output:
                            while chunk := response.read(4 * 1024 * 1024):
                                output.write(chunk)
                                offset += len(chunk)
                                if offset >= next_progress:
                                    print(f'{name}: {offset / expected_size:.0%}', flush=True)
                                    next_progress = offset + 128 * 1024 * 1024
                if partial.stat().st_size != expected_size:
                    raise RuntimeError('Download size mismatch')
                actual_hash = sha256(partial)
                if expected_hash and actual_hash != expected_hash:
                    raise RuntimeError('Download checksum mismatch')
                partial.replace(path)
                manifest['files'].append({'path': name, 'size': expected_size, 'sha256': actual_hash})
                print(f'Downloaded and verified {name}', flush=True)
                break
            except (OSError, RuntimeError):
                if attempt == 2:
                    raise
                print(f'Retrying download of {name}', flush=True)
                time.sleep(2)
    provenance.write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Model ready: {len(manifest["files"])} verified files; revision {revision}', flush=True)


if __name__ == '__main__':
    main()
