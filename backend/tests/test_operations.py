"""Real HTTP/SQLite scenarios using deterministic model fixtures, not model accuracy tests."""
import asyncio
import json
import sqlite3
import time
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfReader
from app import pipeline
from app.main import create_app
from app.models import JobResponse
from app.reports import build_report
from test_history import setup, upload, HEADERS


def submit(c,name='Касса.mov',key=None,tags=None):
    return c.post('/api/v1/analyze',headers={**HEADERS,**({'Idempotency-Key':key} if key else {})},files={'file':(name,b'synthetic')},data={'tags':json.dumps(tags or [],ensure_ascii=False)})


def wait(c,jid):
    for _ in range(200):
        job=c.get('/api/v1/jobs/'+jid,headers=HEADERS).json()
        if job['status']!='processing': return job
        time.sleep(.01)
    raise AssertionError('Fixture still processing')


def test_idempotency_tags_and_restart(tmp_path,monkeypatch):
    config,calls=setup(tmp_path,monkeypatch);key='submission-key-test-012345'
    with TestClient(create_app(config)) as c:
        jid=submit(c,key=key,tags=['Филиал 1','Касса А']).json()['job_id'];job=wait(c,jid)
        assert job['tags']==['Касса А','Филиал 1']
        assert c.patch(f'/api/v1/jobs/{jid}/tags',headers=HEADERS,json={'tags':['Новая метка']}).status_code==200
        for _ in range(3): assert submit(c,key=key,tags=['Филиал 1','Касса А']).json()['job_id']==jid
        assert c.get('/api/v1/jobs',headers=HEADERS).json()['total']==1 and len(calls)==1
        assert c.get('/api/v1/submissions/'+key,headers=HEADERS).json()['tags']==['Новая метка']
        assert submit(c,key=key,tags=['Другая']).status_code==409
        assert c.get('/api/v1/jobs',headers=HEADERS,params={'tag':'Новая метка'}).json()['total']==1
        assert submit(c,key='short').status_code==422
        assert c.patch(f'/api/v1/jobs/{jid}/tags',headers=HEADERS,json={'tags':['x']*11}).status_code==422
    with TestClient(create_app(config)) as c:
        assert submit(c,key=key,tags=['Филиал 1','Касса А']).json()['job_id']==jid and len(calls)==1


def test_queue_progress_audit_pdf_and_expiry(tmp_path,monkeypatch):
    config,calls=setup(tmp_path,monkeypatch,cleanup_interval=60)
    with TestClient(create_app(config)) as c:
        jobs=[wait(c,submit(c,f'Филиал видео {n}.mov',tags=['Филиал',f'Касса {n}']).json()['job_id']) for n in range(4)]
        q=c.get('/api/v1/review-queue?page_size=3',headers=HEADERS).json()
        assert (q['total'],q['total_events'],q['reviewed_events'],len(q['items']))==(8,8,0,3)
        assert q['items'][0]['frame']['image_base64']
        assert len(c.get('/api/v1/review-queue?page=3&page_size=3',headers=HEADERS).json()['items'])==2
        jid=jobs[0]['job_id'];eid=jobs[0]['violations'][0]['event_id'];path=f'/api/v1/jobs/{jid}/events/{eid}/review'
        raw=c.portal.call(lambda:c.app.state.store.connection.execute('SELECT payload FROM jobs WHERE job_id=?',(jid,)).fetchone()[0])
        for decision,comment in [('confirmed','Подтверждаю по кадрам'),('rejected','После просмотра контекста отклонено'),('rejected','После просмотра контекста отклонено')]:
            assert c.patch(path,headers=HEADERS,json={'decision':decision,'comment':comment}).status_code==200
        log=c.get(f'/api/v1/jobs/{jid}/review-log',headers=HEADERS).json()
        assert log['total']==2 and log['items'][0]['previous']['decision']=='confirmed'
        assert c.portal.call(lambda:c.app.state.store.connection.execute('SELECT payload FROM jobs WHERE job_id=?',(jid,)).fetchone()[0])==raw
        filtered=c.get('/api/v1/review-queue',headers=HEADERS,params={'tag':'Касса 0','category_id':jobs[0]['violations'][0]['category_id']}).json()
        assert (filtered['total'],filtered['total_events'],filtered['reviewed_events'])==(0,1,1)
        q=c.get('/api/v1/review-queue',headers=HEADERS).json();assert(q['total'],q['reviewed_events'])==(7,1)
        assert c.get('/api/v1/review-queue',headers=HEADERS,params={'date_from':'2099-01-01T00:00:00Z'}).json()['total']==0
        before=c.get('/api/v1/analytics',headers=HEADERS).json()
        c.get('/api/v1/review-queue',headers=HEADERS,params={'exclude_event_id':eid})
        pdf=c.get(f'/api/v1/jobs/{jid}/report.pdf',headers=HEADERS)
        assert pdf.status_code==200 and pdf.headers['content-type']=='application/pdf'
        reader=PdfReader(BytesIO(pdf.content));text='\n'.join(p.extract_text() for p in reader.pages)
        assert 'Филиал видео 0.mov' in text and 'После просмотра контекста отклонено' in text and 'Не рассмотрено' in text
        assert any('/XObject' in page['/Resources'] for page in reader.pages)
        assert c.get('/api/v1/analytics',headers=HEADERS).json()==before and len(calls)==4
        def expire_video():
            db=c.app.state.store.connection;db.execute('UPDATE videos SET expires_at=0 WHERE job_id=?',(jid,));db.commit();c.app.state.cleanup()
        c.portal.call(expire_video)
        text='\n'.join(p.extract_text() for p in PdfReader(BytesIO(c.get(f'/api/v1/jobs/{jid}/report.pdf',headers=HEADERS).content)).pages)
        assert 'Недоступен' in text and 'После просмотра' in text
    with TestClient(create_app(config)) as c:
        assert c.get(f'/api/v1/jobs/{jid}/review-log',headers=HEADERS).json()['total']==2
        assert c.get('/api/v1/review-queue',headers=HEADERS).json()['reviewed_events']==1
        def expire_result():
            db=c.app.state.store.connection;db.execute('UPDATE jobs SET expires_at=0 WHERE job_id=?',(jid,));db.commit();c.app.state.cleanup()
        c.portal.call(expire_result)
        for suffix in ('/report.pdf','/review-log','/video'): assert c.get(f'/api/v1/jobs/{jid}'+suffix,headers=HEADERS).status_code==404
        assert c.portal.call(lambda:c.app.state.store.connection.execute('SELECT COUNT(*) FROM review_log').fetchone()[0])==0


def test_cancel_targets_queued_and_running_and_preserves_other_jobs(tmp_path,monkeypatch):
    config,_=setup(tmp_path,monkeypatch,workers=1);original=pipeline.analyze;calls=[]
    async def slow_first(path,*args,**kwargs):
        calls.append(path.stem)
        if len(calls)==1: await asyncio.sleep(30)
        return await original(path,*args,**kwargs)
    monkeypatch.setattr(pipeline,'analyze',slow_first)
    with TestClient(create_app(config)) as c:
        first=submit(c,'Первая.mov').json()['job_id']
        for _ in range(100):
            if calls:break
            time.sleep(.01)
        second=submit(c,'Вторая.mov').json()['job_id'];third=submit(c,'Третья.mov').json()['job_id']
        for jid in (second,first): assert c.post(f'/api/v1/jobs/{jid}/cancel',headers=HEADERS).json()['status']=='cancelled'
        assert wait(c,third)['status']=='done' and not any(second in call for call in calls)
        assert c.post(f'/api/v1/jobs/{third}/cancel',headers=HEADERS).json()['status']=='done'
        assert c.get('/api/v1/jobs?status=cancelled',headers=HEADERS).json()['total']==2
        assert c.get('/api/v1/analytics',headers=HEADERS).json()['successful_videos']==1
        assert not list(config.storage.glob('*.upload')) and not list(config.storage.glob('*.normalized.mp4'))
    with TestClient(create_app(config)) as c:
        assert c.get(f'/api/v1/jobs/{first}',headers=HEADERS).json()['status']=='cancelled'
        assert c.get('/api/v1/jobs',headers=HEADERS).json()['total']==3


def test_cancel_ignores_late_model_response(tmp_path,monkeypatch):
    config,_=setup(tmp_path,monkeypatch);original=pipeline.analyze;started=[]
    async def resistant(*args,**kwargs):
        started.append(True)
        try: await asyncio.sleep(20)
        except asyncio.CancelledError: pass
        await asyncio.sleep(.03)
        return await original(*args,**kwargs)
    monkeypatch.setattr(pipeline,'analyze',resistant)
    with TestClient(create_app(config)) as c:
        jid=submit(c).json()['job_id']
        for _ in range(100):
            if started:break
            time.sleep(.01)
        assert c.post(f'/api/v1/jobs/{jid}/cancel',headers=HEADERS).json()['status']=='cancelled'
        job=c.get(f'/api/v1/jobs/{jid}',headers=HEADERS).json()
        assert job['status']=='cancelled' and not job['violations'] and job['verdict'] is None
        assert c.get('/api/v1/analytics',headers=HEADERS).json()['successful_videos']==0


def test_new_routes_are_private(tmp_path,monkeypatch):
    config,_=setup(tmp_path,monkeypatch)
    with TestClient(create_app(config)) as c:
        jid=upload(c)['job_id']
        paths=[('get','/api/v1/review-queue'),('get','/api/v1/review-queue/options'),('get','/api/v1/submissions/request-key'),('get',f'/api/v1/jobs/{jid}/report.pdf'),('get',f'/api/v1/jobs/{jid}/review-log'),('post',f'/api/v1/jobs/{jid}/cancel'),('patch',f'/api/v1/jobs/{jid}/tags')]
        for method,path in paths:
            for headers in ({},{'X-API-Key':'wrong'}): assert c.request(method,path,headers=headers,json={'tags':[]} if method=='patch' else None).status_code==401


def test_v2_migration_preserves_decision_as_explicit_snapshot(tmp_path,monkeypatch):
    config,_=setup(tmp_path,monkeypatch)
    with TestClient(create_app(config)) as c: job=upload(c)
    jid=job['job_id'];eid=job['violations'][0]['event_id'];expiry=job['expires_at'];db=sqlite3.connect(config.storage/'jobs.sqlite3')
    for table in ('review_log','submissions','job_tags'):db.execute('DROP TABLE '+table)
    db.execute("UPDATE events SET decision='confirmed',comment='Старое решение',updated_at='2026-10-17T12:00:00Z' WHERE event_id=?",(eid,));db.execute('PRAGMA user_version=2');db.commit();db.close()
    for _ in range(2):
        with TestClient(create_app(config)) as c:
            log=c.get(f'/api/v1/jobs/{jid}/review-log',headers=HEADERS).json()
            assert log['total']==1 and log['items'][0]['origin']=='migration_snapshot' and log['items'][0]['previous'] is None
            assert log['items'][0]['current']['comment']=='Старое решение'
            restored=c.get(f'/api/v1/jobs/{jid}',headers=HEADERS).json()
            assert restored['violations'][0]['event_id']==eid and restored['expires_at']==expiry


def test_long_cyrillic_pdf_wraps_and_preserves_literal_markup(tmp_path,monkeypatch):
    config,_=setup(tmp_path,monkeypatch)
    with TestClient(create_app(config)) as c:data=upload(c)
    data['filename']='Очень длинное видео '+('кириллица_'*50)+'.mov';event=data['violations'][1]
    event['description']='Длинное объяснение <script> & текст без вымышленных данных. '*110
    event['type']='Событие '+('ДлинноеСлово'*40);data['violations']=[event]*5;data['video_available']=False
    pdf=build_report(JobResponse.model_validate(data));reader=PdfReader(BytesIO(pdf))
    text='\n'.join(p.extract_text() for p in reader.pages)
    assert len(reader.pages)>5 and 'кириллица' in text and '<script>' in text and 'Источник правила недоступен' in text
    out=Path(__file__).resolve().parents[2]/'work/pdf-validation';out.mkdir(parents=True,exist_ok=True);(out/'long-report.pdf').write_bytes(pdf)


def test_cancel_reaps_managed_video_subprocess(tmp_path,monkeypatch):
    import os
    import sys
    from app import media
    config,_=setup(tmp_path,monkeypatch)
    pidfile=tmp_path/'child.pid'
    async def managed(source,target,info,**kwargs):
        await media.command(sys.executable,'-c','import os,time,sys;open(sys.argv[1],"w").write(str(os.getpid()));time.sleep(60)',str(pidfile),timeout=90)
        return info
    monkeypatch.setattr(media,'normalize_video',managed)
    with TestClient(create_app(config)) as c:
        jid=submit(c).json()['job_id']
        for _ in range(100):
            if pidfile.exists(): break
            time.sleep(.01)
        assert pidfile.exists();pid=int(pidfile.read_text())
        assert c.post(f'/api/v1/jobs/{jid}/cancel',headers=HEADERS).json()['status']=='cancelled'
        import pytest
        with pytest.raises(ProcessLookupError):os.kill(pid,0)
        assert not list(config.storage.glob('*.upload'))


def test_review_and_journal_roll_back_together(tmp_path,monkeypatch):
    config,_=setup(tmp_path,monkeypatch)
    with TestClient(create_app(config)) as c:
        job=upload(c);jid=job['job_id'];eid=job['violations'][0]['event_id']
        class Fault:
            def __init__(self,db):self.db=db;self.pending=False
            def __getattr__(self,key):return getattr(self.db,key)
            def execute(self,sql,*args):
                if sql.startswith('UPDATE events SET decision'):self.pending=True
                return self.db.execute(sql,*args)
            def commit(self):
                if self.pending:self.pending=False;raise sqlite3.OperationalError('fixture')
                return self.db.commit()
        def inject():c.app.state.store.connection=Fault(c.app.state.store.connection)
        c.portal.call(inject)
        assert c.patch(f'/api/v1/jobs/{jid}/events/{eid}/review',headers=HEADERS,json={'decision':'confirmed','comment':'Не сохранено'}).status_code==503
        assert c.get(f'/api/v1/jobs/{jid}/review-log',headers=HEADERS).json()['total']==0
        assert c.get(f'/api/v1/jobs/{jid}',headers=HEADERS).json()['violations'][0]['human_review']['decision']=='unreviewed'


def test_simultaneous_replays_create_only_one_job(tmp_path,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    config,calls=setup(tmp_path,monkeypatch)
    with TestClient(create_app(config)) as c:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses=list(pool.map(lambda _:submit(c,key='concurrent-replay-key-0123'),range(2)))
        assert all(r.status_code==202 for r in responses)
        ids={r.json()['job_id'] for r in responses}
        assert len(ids)==1 and wait(c,ids.pop())['status']=='done'
        assert c.get('/api/v1/jobs',headers=HEADERS).json()['total']==1 and len(calls)==1


def test_failed_cancellation_save_does_not_claim_or_apply_cancellation(tmp_path,monkeypatch):
    config,_=setup(tmp_path,monkeypatch)
    original=pipeline.analyze
    async def slow(*args,**kwargs):
        await asyncio.sleep(30)
        return await original(*args,**kwargs)
    monkeypatch.setattr(pipeline,'analyze',slow)
    with TestClient(create_app(config)) as c:
        jid=submit(c).json()['job_id'];store=c.app.state.store;save=store.save;faults=[]
        def fail_once(job,*args,**kwargs):
            if job.status=='cancelled' and not faults:
                faults.append(True);raise sqlite3.OperationalError('fixture')
            return save(job,*args,**kwargs)
        monkeypatch.setattr(store,'save',fail_once)
        assert c.post(f'/api/v1/jobs/{jid}/cancel',headers=HEADERS).status_code==503
        assert c.get(f'/api/v1/jobs/{jid}',headers=HEADERS).json()['status']=='processing'
        assert c.post(f'/api/v1/jobs/{jid}/cancel',headers=HEADERS).json()['status']=='cancelled'


def test_late_normalization_after_cancel_does_not_start_ml(tmp_path,monkeypatch):
    from app import media
    config,calls=setup(tmp_path,monkeypatch);started=[]
    async def resistant(source,target,info,**kwargs):
        started.append(True)
        try: await asyncio.sleep(20)
        except asyncio.CancelledError: pass
        target.write_bytes(b'late normalized bytes')
        return info
    monkeypatch.setattr(media,'normalize_video',resistant)
    with TestClient(create_app(config)) as c:
        jid=submit(c).json()['job_id']
        for _ in range(100):
            if started:break
            time.sleep(.01)
        assert c.post(f'/api/v1/jobs/{jid}/cancel',headers=HEADERS).json()['status']=='cancelled'
        assert calls==[] and not list(config.storage.glob('*.normalized.mp4'))
