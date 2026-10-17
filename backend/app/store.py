"""SQLite history, immutable ML payloads and independent event review/video metadata."""
import hashlib
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from .models import JobResponse, HumanReview, ReviewUpdate


def stamp(value):
    return datetime.fromisoformat(value).timestamp() if value else None


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


class JobStore:
    def __init__(self, path: Path, retention_hours: float | None = None):
        self.directory = path.parent
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA auto_vacuum = FULL")
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        self.connection.execute("""CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY, status TEXT NOT NULL,
            expires_at REAL NOT NULL, payload TEXT NOT NULL
        )""")
        self.connection.execute("CREATE INDEX IF NOT EXISTS jobs_expiry ON jobs(expires_at)")
        self.connection.execute("""CREATE TABLE IF NOT EXISTS job_index (
            job_id TEXT PRIMARY KEY REFERENCES jobs(job_id) ON DELETE CASCADE,
            filename TEXT NOT NULL, filename_search TEXT NOT NULL, created_at REAL NOT NULL,
            completed_at REAL, mode TEXT NOT NULL, status TEXT NOT NULL
        )""")
        self.connection.execute("CREATE INDEX IF NOT EXISTS history_date ON job_index(created_at DESC, job_id)")
        self.connection.execute("""CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
            position INTEGER NOT NULL, category_id TEXT NOT NULL, type TEXT NOT NULL, assessment TEXT,
            decision TEXT NOT NULL DEFAULT 'unreviewed' CHECK(decision IN ('unreviewed','confirmed','rejected')),
            comment TEXT NOT NULL DEFAULT '', updated_at TEXT, UNIQUE(job_id, position)
        )""")
        self.connection.execute("CREATE INDEX IF NOT EXISTS event_category ON events(category_id, job_id)")
        self.connection.execute("""CREATE TABLE IF NOT EXISTS videos (
            job_id TEXT PRIMARY KEY REFERENCES jobs(job_id) ON DELETE CASCADE,
            filename TEXT, size_bytes INTEGER NOT NULL, expires_at REAL NOT NULL,
            reason TEXT
        )""")
        # Keep every legacy row still present in SQLite through a fresh history
        # lifetime. Rows already deleted by the old cleanup cannot be recovered.
        if version < 2:
            now = datetime.now(timezone.utc).timestamp()
            rows = self.connection.execute("SELECT job_id,status,expires_at,payload FROM jobs").fetchall()
            for row in rows:
                job = self._decode(row)
                if retention_hours and job.status != "processing" :
                    base = stamp(job.completed_at or job.created_at)
                    job.expires_at = iso(max(row[2], now + retention_hours * 3600, base + retention_hours * 3600))
                self.save(job)
            self.connection.execute("PRAGMA user_version = 2")
        self.connection.commit()

    def save(self, job: JobResponse, video: dict | None = None):
        # Human decisions never enter the stored model response.
        payload = job.model_dump()
        for event in payload['violations']:
            for name in ('event_id', 'category_id', 'human_review'):
                event.pop(name, None)
        self.connection.execute(
            """INSERT INTO jobs VALUES (?, ?, ?, ?) ON CONFLICT(job_id) DO UPDATE SET
            status=excluded.status, expires_at=excluded.expires_at, payload=excluded.payload""",
            (job.job_id, job.status, stamp(job.expires_at), json.dumps(payload, ensure_ascii=False)),
        )
        self.connection.execute("""INSERT INTO job_index VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(job_id) DO UPDATE SET filename=excluded.filename, filename_search=excluded.filename_search,
            created_at=excluded.created_at,completed_at=excluded.completed_at,mode=excluded.mode,status=excluded.status""",
            (job.job_id, job.filename, job.filename.casefold(), stamp(job.created_at), stamp(job.completed_at), job.mode, job.status))
        if job.status == 'done':
            for position, event in enumerate(job.violations):
                event_id = uuid5(NAMESPACE_URL, f'cashier-guard:{job.job_id}:{position}').hex
                category = 'type:' + hashlib.sha256(event.type.encode()).hexdigest()
                self.connection.execute("""INSERT INTO events(event_id,job_id,position,category_id,type,assessment)
                    VALUES (?,?,?,?,?,?) ON CONFLICT(job_id,position) DO NOTHING""",
                    (event_id, job.job_id, position, category, event.type, event.assessment))
        else:
            self.connection.execute('DELETE FROM events WHERE job_id=?', (job.job_id,))
        if video:
            self.connection.execute('INSERT OR REPLACE INTO videos VALUES (?,?,?,?,NULL)',
                                    (job.job_id, video['filename'], video['size_bytes'], video['expires_at']))
        self.connection.commit()

    def get(self, job_id: str) -> JobResponse | None:
        row = self.connection.execute("SELECT job_id,status,expires_at,payload FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            return None
        job = self._decode(row)
        events = self.connection.execute('SELECT event_id,position,category_id,decision,comment,updated_at FROM events WHERE job_id=?', (job_id,)).fetchall()
        for event_id, position, category, decision, comment, updated in events:
            if position < len(job.violations):
                event = job.violations[position]
                event.event_id, event.category_id = event_id, category
                event.human_review = HumanReview(decision=decision, comment=comment, updated_at=updated)
        info = self.video_info(job_id)
        if info:
            job.video_expires_at = iso(info['expires_at'])
            job.video_size_bytes = info['size_bytes']
            job.video_available = bool(self.video_path(job_id))
            job.video_unavailable_reason = None if job.video_available else (
                'expired' if info['expires_at'] <= datetime.now(timezone.utc).timestamp() else info['reason'] or 'missing')
        else:
            job.video_unavailable_reason = 'not_retained'
        return job

    def video_info(self, job_id):
        row = self.connection.execute('SELECT filename,size_bytes,expires_at,reason FROM videos WHERE job_id=?', (job_id,)).fetchone()
        return dict(zip(('filename','size_bytes','expires_at','reason'), row)) if row else None

    def video_path(self, job_id):
        info = self.video_info(job_id)
        if not info or not info['filename'] or info['expires_at'] <= datetime.now(timezone.utc).timestamp():
            return None
        name = info['filename']
        if Path(name).name != name or not name.endswith('.mp4'):
            return None
        path = self.directory / 'videos' / name
        return path if path.is_file() and not path.is_symlink() else None

    def _decode(self, row):
        job_id, status, expiry, payload = row
        try:
            job = JobResponse.model_validate_json(payload)
            if job.job_id != job_id or job.status != status:
                raise ValueError('Stored identity or status does not match')
            for value in (job.created_at, job.expires_at):
                if value is None or not math.isfinite(stamp(value)):
                    raise ValueError('Invalid stored timestamp')
            return job
        except (ValueError, TypeError, OverflowError):
            try:
                raw = json.loads(payload)
            except (ValueError, TypeError, RecursionError):
                raw = {}
            if not isinstance(raw, dict): raw = {}
            now = datetime.now(timezone.utc)
            try: expires = iso(expiry)
            except (ValueError, TypeError, OverflowError, OSError): expires = now.isoformat()
            filename, mode = raw.get('filename'), raw.get('mode')
            job = JobResponse(job_id=job_id,status='failed',stage='failed',
                mode=mode if mode in ('live','demo') else 'live',
                filename=filename if isinstance(filename,str) and filename else 'Видео',
                created_at=now.isoformat(),expires_at=expires,completed_at=now.isoformat(),
                error_code='RESULT_INVALID',error='Сохранённый результат не соответствует контракту. Проверка не завершена; загрузите видео повторно.')
            try: self.save(job)
            except sqlite3.Error: self.connection.rollback()
            return job

    def unfinished(self):
        rows = self.connection.execute("SELECT job_id,status,expires_at,payload FROM jobs WHERE status='processing'").fetchall()
        return [job for row in rows if (job := self._decode(row)).status == 'processing']

    def retained_video_names(self):
        return {row[0] for row in self.connection.execute('SELECT filename FROM videos WHERE filename IS NOT NULL')}

    def count(self):
        return self.connection.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]

    def delete(self, job_id):
        info = self.video_info(job_id)
        self.connection.execute('DELETE FROM jobs WHERE job_id=?', (job_id,))
        self.connection.commit()
        if info and info['filename'] and Path(info['filename']).name == info['filename']:
            return self.directory / 'videos' / info['filename']

    def delete_expired(self, now):
        rows = self.connection.execute("SELECT job_id FROM jobs WHERE expires_at <= ? AND status != 'processing'", (now,)).fetchall()
        return [path for (job_id,) in rows if (path := self.delete(job_id))]

    def expire_videos(self, now):
        rows = self.connection.execute('SELECT job_id,filename FROM videos WHERE expires_at<=? AND filename IS NOT NULL', (now,)).fetchall()
        paths=[]
        for job_id, name in rows:
            if Path(name).name == name: paths.append(self.directory/'videos'/name)
            self.connection.execute("UPDATE videos SET filename=NULL,reason='expired' WHERE job_id=?", (job_id,))
        self.connection.commit()
        return paths

    def update_review(self, job_id, event_id, update: ReviewUpdate):
        updated = datetime.now(timezone.utc).isoformat()
        cursor = self.connection.execute('UPDATE events SET decision=?,comment=?,updated_at=? WHERE job_id=? AND event_id=?',
                                       (update.decision, update.comment, updated, job_id, event_id))
        self.connection.commit()
        return HumanReview(decision=update.decision,comment=update.comment,updated_at=updated) if cursor.rowcount else None

    def _where(self, *, search='', status=None, date_from=None, date_to=None, category_id=None, mode=None):
        conditions=['(j.status=\'processing\' OR j.expires_at>?)'];params=[datetime.now(timezone.utc).timestamp()]
        for sql, value in [('instr(i.filename_search,?)>0',search.casefold() if search else None),('i.status=?',status),
                           ('i.created_at>=?',date_from),('i.created_at<?',date_to),('i.mode=?',mode)]:
            if value is not None: conditions.append(sql);params.append(value)
        if category_id:
            conditions.append('EXISTS(SELECT 1 FROM events e WHERE e.job_id=j.job_id AND e.category_id=?)');params.append(category_id)
        return ' AND '.join(conditions),params

    def history(self, page, page_size, **filters):
        where, params = self._where(**filters)
        base=' FROM jobs j JOIN job_index i ON j.job_id=i.job_id WHERE '+where
        total=self.connection.execute('SELECT COUNT(*)'+base,params).fetchone()[0]
        rows=self.connection.execute('SELECT j.job_id,i.filename,i.created_at,i.completed_at,j.expires_at,i.status,i.mode'+base+' ORDER BY i.created_at DESC,j.job_id DESC LIMIT ? OFFSET ?',[*params,page_size,(page-1)*page_size]).fetchall()
        items=[]
        for job_id,filename,created,completed,expires,status,mode in rows:
            red,yellow,unreviewed=self.connection.execute("""SELECT
                COALESCE(SUM(assessment='strong_evidence'),0),
                COALESCE(SUM(assessment IS NULL OR assessment!='strong_evidence'),0),
                COALESCE(SUM(decision='unreviewed'),0) FROM events WHERE job_id=?""",(job_id,)).fetchone()
            info=self.video_info(job_id)
            items.append(dict(job_id=job_id,filename=filename,created_at=iso(created),completed_at=iso(completed) if completed else None,
                expires_at=iso(expires),status=status,mode=mode,red_count=red,yellow_count=yellow,
                unreviewed_count=unreviewed,video_available=bool(self.video_path(job_id)),
                video_expires_at=iso(info['expires_at']) if info else None))
        return dict(items=items,total=total,page=page,page_size=page_size)

    def analytics(self, date_from=None, date_to=None):
        where,params=self._where(status='done',mode='live',date_from=date_from,date_to=date_to)
        base=' FROM jobs j JOIN job_index i ON j.job_id=i.job_id WHERE '+where
        videos=self.connection.execute('SELECT COUNT(*)'+base,params).fetchone()[0]
        with_events=self.connection.execute('SELECT COUNT(*)'+base+' AND EXISTS(SELECT 1 FROM events e WHERE e.job_id=j.job_id)',params).fetchone()[0]
        base=' FROM events e JOIN jobs j ON e.job_id=j.job_id JOIN job_index i ON i.job_id=j.job_id WHERE '+where
        counts=dict(self.connection.execute('SELECT e.decision,COUNT(*)'+base+' GROUP BY e.decision',params).fetchall())
        top=self.connection.execute("SELECT e.category_id,e.type,COUNT(*),SUM(e.decision='confirmed')"+base+' GROUP BY e.category_id,e.type ORDER BY COUNT(*) DESC,e.category_id LIMIT 3',params).fetchall()
        return dict(successful_videos=videos,videos_with_events=with_events,detected_events=sum(counts.values()),
            confirmed_events=counts.get('confirmed',0),rejected_events=counts.get('rejected',0),unreviewed_events=counts.get('unreviewed',0),
            top_types=[dict(category_id=c,type=t,detected=n,confirmed=h) for c,t,n,h in top],date_basis='created_at')

    def close(self):
        self.connection.close()
