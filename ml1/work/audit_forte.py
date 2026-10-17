"""Local-only audit of archive bytes, labels and QuickTime metadata. No frames decoded."""
from pathlib import Path
import collections
import hashlib
import io
import json
import re
import struct
import zipfile
import zlib
import openpyxl

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = Path.home() / 'Downloads' / 'open.zip'
EXTRACTED = ARCHIVE.parent

def boxes(data, start=0, end=None):
    end = len(data) if end is None else end
    pos = start
    while pos + 8 <= end:
        size, kind = struct.unpack_from('>I4s', data, pos)
        header = 8
        if size == 1:
            size = struct.unpack_from('>Q', data, pos + 8)[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end:
            raise ValueError('Invalid QuickTime box')
        yield kind, data[pos + header:pos + size]
        pos += size

def duration(payload):
    if payload[0] == 1:
        scale = struct.unpack_from('>I', payload, 20)[0]
        ticks = struct.unpack_from('>Q', payload, 24)[0]
    else:
        scale, ticks = struct.unpack_from('>II', payload, 12)
    return ticks / scale if scale else None, scale

def movie_metadata(path):
    moov = None
    with path.open('rb') as f:
        length = path.stat().st_size
        while f.tell() + 8 <= length:
            start = f.tell()
            size, kind = struct.unpack('>I4s', f.read(8))
            header = 8
            if size == 1:
                size = struct.unpack('>Q', f.read(8))[0]
                header = 16
            elif size == 0:
                size = length - start
            if size < header or start + size > length:
                raise ValueError('Invalid top-level box')
            if kind == b'moov':
                moov = f.read(size - header)
                break
            f.seek(start + size)
    if moov is None:
        raise ValueError('No moov metadata')
    result = {'duration_sec': None, 'video_tracks': [], 'audio_tracks': 0}
    for kind, payload in boxes(moov):
        if kind == b'mvhd':
            result['duration_sec'] = duration(payload)[0]
        if kind != b'trak':
            continue
        track = {}
        handler = None
        for k, p in boxes(payload):
            if k == b'tkhd':
                w, h = struct.unpack('>II', p[-8:])
                track.update(width=w / 65536, height=h / 65536)
            if k != b'mdia':
                continue
            for mk, mp in boxes(p):
                if mk == b'hdlr':
                    handler = mp[8:12]
                elif mk == b'mdhd':
                    track['media_duration_sec'], track['timescale'] = duration(mp)
                elif mk == b'minf':
                    for ik, ip in boxes(mp):
                        if ik != b'stbl':
                            continue
                        for sk, sp in boxes(ip):
                            if sk == b'stts':
                                n = struct.unpack_from('>I', sp, 4)[0]
                                counts = [struct.unpack_from('>II', sp, 8 + j * 8) for j in range(n)]
                                track['samples'] = sum(c for c, d in counts)
                                track['sample_ticks'] = sum(c * d for c, d in counts)
        if handler == b'vide':
            ticks = track.get('sample_ticks', 0)
            track['average_fps'] = track.get('samples', 0) * track.get('timescale', 0) / ticks if ticks else None
            result['video_tracks'].append(track)
        elif handler == b'soun':
            result['audio_tracks'] += 1
    return result

def key(name):
    stem = Path(str(name).strip()).stem.replace('Х', 'X').replace('х', 'X').upper()
    if not re.fullmatch(r'X-\d+', stem):
        raise ValueError('Unexpected video identifier')
    return stem

def timestamp(raw):
    if raw is None:
        return None
    match = re.fullmatch(r'\s*(?:(\d+)\s*минут[аы]?\s*)?(\d+(?:[.,]\d+)?)\s*секунд[аы]?\s*', str(raw))
    if not match:
        raise ValueError('Unrecognized timestamp format')
    return 60 * int(match.group(1) or 0) + float(match.group(2).replace(',', '.'))

with zipfile.ZipFile(ARCHIVE) as z:
    xlsx_bytes = z.read('open/open_labels.xlsx')
    sheet = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)['labels']
    raw_rows = [list(row) for row in sheet.iter_rows(values_only=True)]
    labels = {}
    for row in raw_rows[1:]:
        k = key(row[0])
        if k in labels:
            raise ValueError('Duplicate label ID: ' + k)
        labels[k] = row
    rows = []
    for entry in z.infolist():
        if not entry.filename.lower().endswith('.mov'):
            continue
        rel = Path(entry.filename)
        if rel.is_absolute() or '..' in rel.parts:
            raise ValueError('Unsafe archive path')
        path = EXTRACTED / rel
        if not path.is_file() or path.is_symlink():
            raise ValueError('Missing verified extraction: ' + entry.filename)
        sha, crc = hashlib.sha256(), 0
        with path.open('rb') as f:
            for chunk in iter(lambda: f.read(2**20), b''):
                sha.update(chunk)
                crc = zlib.crc32(chunk, crc)
        if path.stat().st_size != entry.file_size or crc != entry.CRC:
            raise ValueError('Extracted bytes differ from archive: ' + entry.filename)
        identifier = key(path.name)
        raw = labels.get(identifier)
        if raw is None:
            raise ValueError('Missing label: ' + identifier)
        t = timestamp(raw[1])
        meta = movie_metadata(path)
        flags = []
        if t is not None and not (0 <= t <= meta['duration_sec']):
            flags.append('Таймкод вне длительности')
        if raw[2] == 'нарушение' and t is None:
            flags.append('Нет таймкода при положительной метке')
        if raw[2] == 'без нарушения' and t is not None:
            flags.append('Таймкод при отрицательной метке')
        rows.append({'id': identifier, 'filename': path.name, 'source_filename': raw[0],
                     'path': str(path), 'bytes': entry.file_size, 'sha256': sha.hexdigest(),
                     'label': raw[2], 'timestamp_raw': raw[1], 'timestamp_sec': t,
                     'metadata': meta, 'flags': flags})

rows.sort(key=lambda r: int(r['id'].split('-')[1]))
groups = collections.defaultdict(list)
for row in rows:
    groups[row['sha256']].append(row)
duplicates = []
for group in groups.values():
    gid = group[0]['id']
    labels_differ = len({r['label'] for r in group}) > 1
    times_differ = len({r['timestamp_sec'] for r in group}) > 1
    for row in group:
        row['content_group'] = gid
        row['copies'] = len(group)
        if len(group) > 1:
            row['flags'].append('Точный дубль: ' + ', '.join(r['filename'] for r in group if r is not row))
        if labels_differ:
            row['flags'].append('Конфликт меток одинакового видео')
        if times_differ:
            row['flags'].append('Разные таймкоды одинакового видео')
    if len(group) > 1:
        duplicates.append({'files':[r['filename'] for r in group], 'labels':[r['label'] for r in group],
                           'times_sec':[r['timestamp_sec'] for r in group], 'label_conflict':labels_differ})

durations=[r['metadata']['duration_sec'] for r in rows]
summary={'videos':len(rows),'unique_video_bytes':len(groups),
         'labels':dict(collections.Counter(r['label'] for r in rows)),
         'total_MiB':sum(r['bytes'] for r in rows)/2**20,
         'duration_min_sec':min(durations),'duration_max_sec':max(durations),
         'total_minutes':sum(durations)/60,
         'unique_minutes':sum(g[0]['metadata']['duration_sec'] for g in groups.values())/60,
         'videos_with_audio_track':sum(r['metadata']['audio_tracks']>0 for r in rows),
         'duplicates':duplicates,
         'timecode_issues':[r['id'] for r in rows if any('Таймкод вне' in f for f in r['flags'])],
         'fps_values':sorted({round(t['average_fps'],3) for r in rows for t in r['metadata']['video_tracks'] if t['average_fps'] is not None}),
         'dimensions':sorted({(t['width'],t['height']) for r in rows for t in r['metadata']['video_tracks']}),
         'source_labels_filename_mismatch':sum(r['filename'] != str(r['source_filename'])+'.mov' for r in rows)}
report={'summary':summary,'records':rows,'raw_labels':raw_rows,
        'method':'CRC32 against archive, SHA-256 exact duplicates, QuickTime container metadata only. No video frames or audio decoded.',
        'archive':str(ARCHIVE)}
(ROOT/'work/forte-data-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
