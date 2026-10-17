"""Synthetic model fixtures exercising real HTTP auth, SQLite and retention."""
import base64
import json
import sqlite3
import time
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image
from fastapi.testclient import TestClient
from app import media, pipeline
from app.config import Settings
from app.main import create_app
from app.models import AnalysisResult, EvidenceFrame, Rule, Violation, JobResponse
from app.store import JobStore

KEY='history-private-fixture-key'
HEADERS={'X-API-Key':KEY}


def setup(tmp_path,monkeypatch,**options):
    calls=[]
    async def probe(path,**kwargs): return SimpleNamespace(duration_sec=12,start_time=0)
    async def normalize(source,target,info,**kwargs):
        target.write_bytes(b'fixture-mp4-bytes')
        return info
    buf=BytesIO();Image.new('RGB',(32,24),'white').save(buf,'JPEG')
    frame=EvidenceFrame(timestamp_sec=1,image_base64=base64.b64encode(buf.getvalue()).decode())
    rule=Rule(id='fixture-rule',title='Synthetic fixture',visual_signs=['fixture'],document='Not a legal claim',section='test',url='https://example.org/fixture')
    async def analyze(path,duration,settings,scenario,on_stage):
        calls.append(path.name);on_stage('analyzing')
        return AnalysisResult(verdict='violation',violations=[
            Violation(type='Exact fixture A',timecode_sec=1,description='synthetic',evidence_frames=[frame,frame,frame],assessment='strong_evidence',assessment_reason='fixture reason',rule_id=rule.id,rule=rule),
            Violation(type='Exact fixture B',timecode_sec=2,description='synthetic',evidence_frames=[frame],assessment='needs_review'),
        ])
    monkeypatch.setattr(media,'inspect_video',probe);monkeypatch.setattr(media,'normalize_video',normalize);monkeypatch.setattr(pipeline,'analyze',analyze)
    return Settings(api_key=KEY,mode=options.pop('mode','live'),storage=tmp_path/'store',**options),calls


def upload(client,name='fixture.mov'):
    response=client.post('/api/v1/analyze',headers=HEADERS,files={'file':(name,b'synthetic')})
    assert response.status_code==202,response.text
    job_id=response.json()['job_id']
    for _ in range(100):
        job=client.get('/api/v1/jobs/'+job_id,headers=HEADERS).json()
        if job['status']!='processing':
            assert job['status']=='done',job
            return job
        time.sleep(.01)
    pytest.fail('fixture did not finish')


def test_four_checks_restart_open_review_analytics_delete(tmp_path,monkeypatch):
    config,calls=setup(tmp_path,monkeypatch)
    with TestClient(create_app(config)) as client:
        jobs=[upload(client,f'Касса {n}.mov') for n in range(4)]
        page=client.get('/api/v1/jobs?page_size=2',headers=HEADERS).json()
        assert page['total']==4 and len(page['items'])==2
        assert page['items'][0]['red_count']==1 and page['items'][0]['yellow_count']==1
        assert page['items'][0]['unreviewed_count']==2
        assert len(client.get('/api/v1/jobs?page=2&page_size=2',headers=HEADERS).json()['items'])==2
        assert client.get('/api/v1/jobs?search=касса%202',headers=HEADERS).json()['total']==1
        assert client.get('/api/v1/jobs?status=failed',headers=HEADERS).json()['total']==0
        assert client.get('/api/v1/jobs?date_from=2099-01-01T00:00:00Z',headers=HEADERS).json()['total']==0
        original=jobs[0];jid=original['job_id'];event=original['violations'][0]
        assert original['video_available']
        raw=client.portal.call(lambda: client.app.state.store.connection.execute('SELECT payload FROM jobs WHERE job_id=?',(jid,)).fetchone()[0])
        response=client.patch(f'/api/v1/jobs/{jid}/events/{event["event_id"]}/review',headers=HEADERS,json={'decision':'confirmed','comment':'Проверено человеком'})
        assert response.status_code==200 and response.json()['updated_at']
        other=original['violations'][1]
        client.patch(f'/api/v1/jobs/{jid}/events/{other["event_id"]}/review',headers=HEADERS,json={'decision':'rejected','comment':'Контекст не подтверждает'})
        assert client.portal.call(lambda: client.app.state.store.connection.execute('SELECT payload FROM jobs WHERE job_id=?',(jid,)).fetchone()[0])==raw
        for _ in range(3): assert client.get(f'/api/v1/jobs/{jid}',headers=HEADERS).status_code==200
        stats=client.get('/api/v1/analytics',headers=HEADERS).json()
        assert (stats['successful_videos'],stats['videos_with_events'],stats['detected_events'])==(4,4,8)
        assert (stats['confirmed_events'],stats['rejected_events'],stats['unreviewed_events'])==(1,1,6)
        category=stats['top_types'][0]['category_id']
        assert client.get('/api/v1/jobs',headers=HEADERS,params={'category_id':category,'status':'done','mode':'live'}).json()['total']==4
        video=client.get(f'/api/v1/jobs/{jid}/video',headers={**HEADERS,'Range':'bytes=0-6'})
        assert video.status_code==206 and video.content==b'fixture'
    with TestClient(create_app(config)) as restarted:
        assert restarted.get('/api/v1/jobs',headers=HEADERS).json()['total']==4
        restored=restarted.get(f'/api/v1/jobs/{jid}',headers=HEADERS).json()
        assert restored['violations'][0]['event_id']==event['event_id']
        assert restored['violations'][0]['human_review']['comment']=='Проверено человеком'
        assert restored['violations'][0]['assessment']==event['assessment']
        assert restored['video_available']
        assert restarted.get(f'/api/v1/jobs/{jid}/video',headers=HEADERS).status_code==200
        assert len(calls)==4  # GET, decisions and restart never invoke ML.
        assert restarted.delete(f'/api/v1/jobs/{jid}',headers=HEADERS).status_code==200
        assert restarted.get('/api/v1/jobs',headers=HEADERS).json()['total']==3
        assert restarted.get('/api/v1/analytics',headers=HEADERS).json()['detected_events']==6
        assert restarted.get(f'/api/v1/jobs/{jid}',headers=HEADERS).status_code==404
        assert not (config.storage/'videos'/f'{jid}.mp4').exists()


def test_auth_validation_and_cross_job_event(tmp_path,monkeypatch):
    config,_=setup(tmp_path,monkeypatch)
    with TestClient(create_app(config)) as client:
        a,b=upload(client),upload(client)
        review=f'/api/v1/jobs/{a["job_id"]}/events/{a["violations"][0]["event_id"]}/review'
        for method,path in [('get','/api/v1/jobs'),('get','/api/v1/analytics'),('delete','/api/v1/jobs/'+a['job_id']),('get','/api/v1/jobs/'+a['job_id']+'/video'),('patch',review)]:
            for headers in ({},{'X-API-Key':'wrong'}):
                assert client.request(method,path,headers=headers,json={'decision':'confirmed'} if method=='patch' else None).status_code==401
        assert client.get('/api/v1/jobs?api_key='+KEY).status_code==401
        assert client.patch(review,headers=HEADERS,json={'decision':'invalid'}).status_code==422
        assert client.patch(review,headers=HEADERS,json={'decision':'confirmed','assessment':'needs_review'}).status_code==422
        assert client.patch(review,headers=HEADERS,json={'decision':'confirmed','comment':'x'*4001}).status_code==422
        cross=f'/api/v1/jobs/{b["job_id"]}/events/{a["violations"][0]["event_id"]}/review'
        assert client.patch(cross,headers=HEADERS,json={'decision':'confirmed'}).status_code==404
        for query in ('page=0','page_size=101','status=unknown','date_from=2026-01-01T00:00:00','date_from=2026-02-01T00:00:00Z&date_to=2026-01-01T00:00:00Z'):
            assert client.get('/api/v1/jobs?'+query,headers=HEADERS).status_code==422


def test_video_and_result_expiry_are_independent(tmp_path,monkeypatch):
    config,_=setup(tmp_path,monkeypatch,retention_hours=720,video_retention_hours=.00001,cleanup_interval=60)
    with TestClient(create_app(config)) as client:
        job=upload(client);jid=job['job_id'];time.sleep(.06)
        client.portal.call(client.app.state.cleanup)
        result=client.get('/api/v1/jobs/'+jid,headers=HEADERS).json()
        assert result['status']=='done' and result['violations'][0]['evidence_frames']
        assert not result['video_available'] and result['video_unavailable_reason']=='expired'
        assert client.get('/api/v1/jobs/'+jid+'/video',headers=HEADERS).status_code==410
        assert client.get('/api/v1/jobs',headers=HEADERS).json()['total']==1
        def expire_result():
            client.app.state.store.connection.execute('UPDATE jobs SET expires_at=0 WHERE job_id=?',(jid,));client.app.state.store.connection.commit()
            client.app.state.cleanup()
        client.portal.call(expire_result)
        assert client.get('/api/v1/jobs/'+jid,headers=HEADERS).status_code==404
        assert client.get('/api/v1/jobs',headers=HEADERS).json()['total']==0


def test_demo_failed_processing_excluded_and_exact_types_not_merged(tmp_path,monkeypatch):
    config,_=setup(tmp_path,monkeypatch,mode='demo')
    with TestClient(create_app(config)) as client:
        upload(client)
        assert client.get('/api/v1/analytics',headers=HEADERS).json()['successful_videos']==0
        def seed():
            now=datetime.now(timezone.utc).isoformat();future='2099-01-01T00:00:00+00:00'
            store=client.app.state.store
            for status in ('processing','failed'):
                store.save(JobResponse(job_id=status,status=status,stage='queued' if status=='processing' else 'failed',mode='live',filename=status,created_at=now,expires_at=future))
        client.portal.call(seed)
        stats=client.get('/api/v1/analytics',headers=HEADERS).json()
        assert stats['successful_videos']==stats['detected_events']==0
        assert client.delete('/api/v1/jobs/processing',headers=HEADERS).status_code==409


def test_legacy_migration_preserves_payload_and_stable_ids(tmp_path,monkeypatch):
    config,_=setup(tmp_path,monkeypatch)
    config.storage.mkdir()
    path=config.storage/'jobs.sqlite3';conn=sqlite3.connect(path)
    conn.execute('CREATE TABLE jobs(job_id TEXT PRIMARY KEY,status TEXT NOT NULL,expires_at REAL NOT NULL,payload TEXT NOT NULL)')
    now=time.time();payload=dict(job_id='legacy',status='done',stage='done',mode='demo',filename='legacy.mov',created_at=datetime.fromtimestamp(now,timezone.utc).isoformat(),expires_at=datetime.fromtimestamp(now+3600,timezone.utc).isoformat(),verdict='no_violation',violations=[],error=None)
    conn.execute('INSERT INTO jobs VALUES(?,?,?,?)',('legacy','done',now+3600,json.dumps(payload)));conn.commit();conn.close()
    with TestClient(create_app(config)) as client:
        job=client.get('/api/v1/jobs/legacy',headers=HEADERS).json()
        assert job['verdict']=='no_violation' and job['filename']=='legacy.mov'
        assert datetime.fromisoformat(job['expires_at']).timestamp()>now+700*3600
        assert job['video_unavailable_reason']=='not_retained'
        assert client.get('/api/v1/jobs',headers=HEADERS).json()['total']==1
        assert client.portal.call(lambda:client.app.state.store.connection.execute('PRAGMA user_version').fetchone()[0])==2


def test_archived_video_counts_towards_quota_and_expiry_releases_space(tmp_path,monkeypatch):
    config,_=setup(tmp_path,monkeypatch,max_storage_mb=1,cleanup_interval=60)
    with TestClient(create_app(config)) as client:
        job=upload(client);path=config.storage/'videos'/f'{job["job_id"]}.mp4'
        path.write_bytes(b'x'*(900*1024))
        blocked=client.post('/api/v1/analyze',headers=HEADERS,files={'file':('next.mov',b'video')})
        assert blocked.status_code==503
        assert client.get('/api/v1/jobs',headers=HEADERS).json()['total']==1
        def expire():
            client.app.state.store.connection.execute('UPDATE videos SET expires_at=0');client.app.state.store.connection.commit();client.app.state.cleanup()
        client.portal.call(expire)
        assert not path.exists()
        assert upload(client,'after-expiry.mov')['status']=='done'
        assert client.get('/api/v1/jobs',headers=HEADERS).json()['total']==2


def test_result_expiry_deletes_video_even_if_video_lifetime_is_longer(tmp_path,monkeypatch):
    config,_=setup(tmp_path,monkeypatch,retention_hours=.00004,video_retention_hours=168,cleanup_interval=60)
    with TestClient(create_app(config)) as client:
        job=upload(client);path=config.storage/'videos'/f'{job["job_id"]}.mp4'
        assert path.exists()
        time.sleep(.17);client.portal.call(client.app.state.cleanup)
        assert not path.exists()
        assert client.get('/api/v1/jobs/'+job['job_id'],headers=HEADERS).status_code==404
        assert client.get('/api/v1/analytics',headers=HEADERS).json()['successful_videos']==0
