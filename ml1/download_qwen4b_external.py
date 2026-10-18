"""Download pinned public Qwen weights, with resumable verified ranges. No video access."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import http.client
import json
from pathlib import Path
import shutil
import os
import threading
import time
import urllib.request
import urllib.parse

ROOT=Path('/Volumes/Downloads/cashier-guard-local-models')
FOLDER=ROOT/'local'/'qwen-4b-download'
BASE='https://registry.ollama.ai/v2/library/qwen3-vl/'
EXPECTED_MODEL_SHA='16b83be682148a4d8201dbf720ea7eace5de98b69f63f05e0c908b4d7977ecb5'
CHUNK=1024*1024


def checksum(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
    return h.hexdigest()


def get(url):
    with urllib.request.urlopen(url,timeout=45) as r:return r.read()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers',type=int,choices=range(1,65),default=16)
    args=parser.parse_args()
    FOLDER.mkdir(parents=True,exist_ok=True)
    (FOLDER/'download-process.json').write_text(json.dumps({'pid':os.getpid()}))
    manifest=FOLDER/'manifest.json'
    if not manifest.exists():manifest.write_bytes(get(BASE+'manifests/4b-instruct'))
    raw=manifest.read_bytes();m=json.loads(raw)
    entries=list({x['digest']:x for x in [*m['layers'],m['config']]}.values())
    primary=next(x for x in entries if x.get('mediaType')=='application/vnd.ollama.image.model')
    if primary['digest']!='sha256:'+EXPECTED_MODEL_SHA:raise RuntimeError('Model tag changed; review before download')
    size=primary['size'];url=BASE+'blobs/'+primary['digest']
    blobs=ROOT/'models'/'ollama'/'blobs';blobs.mkdir(parents=True,exist_ok=True)
    final=blobs/primary['digest'].replace(':','-')
    partial=FOLDER/'model.part';state=FOLDER/'ranges.json'
    if final.exists() and final.stat().st_size==size and checksum(final)==EXPECTED_MODEL_SHA:
        print('Main model already verified',flush=True)
    else:
        total=(size+CHUNK-1)//CHUNK
        if state.exists():
            saved=json.loads(state.read_text())
            if saved['size']!=size or saved['chunk']!=CHUNK or saved['url']!=url:raise RuntimeError('Resume metadata mismatch')
            if not partial.exists() or partial.stat().st_size!=size:raise RuntimeError('Partial file missing or truncated')
            done=set(saved['done'])
        else:
            if shutil.disk_usage(FOLDER).free-size < 2*1024**3:raise RuntimeError('Need at least 2 GiB free after download')
            done=set()
            with partial.open('wb') as f:f.truncate(size)
        def save():
            temp=state.with_suffix('.tmp')
            temp.write_text(json.dumps({'size':size,'chunk':CHUNK,'url':url,'done':sorted(done)}))
            temp.replace(state)
        save()
        # Reuse a direct CDN connection per worker instead of doing registry
        # redirects and TLS handshakes for every small block.
        endpoint_lock=threading.Lock()
        def resolve_endpoint():
            req=urllib.request.Request(url,headers={'Range':'bytes=0-0'})
            with urllib.request.urlopen(req,timeout=45) as r:
                endpoint=r.geturl()
                r.read(1)
            if urllib.parse.urlsplit(endpoint).scheme!='https':raise ValueError('HTTPS required')
            return endpoint
        endpoint=[resolve_endpoint()]
        thread_state=threading.local()
        def fetch(i):
            a=i*CHUNK;b=min(size,a+CHUNK)-1
            for attempt in range(4):
                try:
                    current=endpoint[0];parts=urllib.parse.urlsplit(current)
                    host=(parts.hostname,parts.port or 443)
                    if getattr(thread_state,'host',None)!=host or getattr(thread_state,'connection',None) is None:
                        thread_state.connection=http.client.HTTPSConnection(*host,timeout=45)
                        thread_state.host=host
                    connection=thread_state.connection
                    path=parts.path+('?' + parts.query if parts.query else '')
                    connection.request('GET',path,headers={'Range':f'bytes={a}-{b}'})
                    r=connection.getresponse()
                    if r.status in (401,403):
                        r.close()
                        with endpoint_lock:
                            if endpoint[0]==current:endpoint[0]=resolve_endpoint()
                        raise ValueError('Refreshing expired public download link')
                    if r.status!=206 or r.getheader('Content-Range')!=f'bytes {a}-{b}/{size}':
                        r.close();raise ValueError('Invalid byte range')
                    data=r.read(b-a+2);r.close()
                    if len(data)!=b-a+1:raise ValueError('Incomplete byte range')
                    return i,data
                except (OSError,ValueError,http.client.HTTPException):
                    if getattr(thread_state,'connection',None) is not None:
                        thread_state.connection.close();thread_state.connection=None
                    if attempt==3:raise
                    time.sleep(attempt+1)
        start=time.monotonic();initial=len(done)
        print('Qwen model:',len(done),'/',total,'blocks; workers:',args.workers,flush=True)
        with partial.open('r+b') as f,ThreadPoolExecutor(max_workers=args.workers) as pool:
            jobs={pool.submit(fetch,i) for i in range(total) if i not in done}
            for job in as_completed(jobs):
                jobs.remove(job)  # Do not retain every downloaded block in RAM.
                try:i,data=job.result()
                except Exception as e:print('Block failed:',type(e).__name__,flush=True);continue
                f.seek(i*CHUNK);f.write(data);f.flush();done.add(i);save()
                if len(done)%16==0 or len(done)==total:
                    rate=(len(done)-initial)*CHUNK/max(.001,time.monotonic()-start)/1e6
                    print('Qwen progress:',len(done),'/',total,'speed_MB_s:',round(rate,3),flush=True)
        if len(done)!=total:raise RuntimeError('Some blocks missing; rerun to resume')
        if checksum(partial)!=EXPECTED_MODEL_SHA:raise RuntimeError('Model checksum mismatch; no model registered')
        partial.replace(final)
        print('Main model SHA-256 verified',flush=True)
    for e in entries:
        if e['digest']==primary['digest']:continue
        sha=e['digest'].split(':')[1]
        if len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha):raise ValueError('Invalid digest')
        p=blobs/('sha256-'+sha)
        if p.exists() and p.stat().st_size==e['size'] and checksum(p)==sha:continue
        data=get(BASE+'blobs/'+e['digest'])
        if len(data)!=e['size'] or hashlib.sha256(data).hexdigest()!=sha:raise RuntimeError('Metadata checksum mismatch')
        temp=p.with_suffix('.tmp');temp.write_bytes(data);temp.replace(p)
    destination=ROOT/'models'/'ollama'/'manifests'/'registry.ollama.ai'/'library'/'qwen3-vl'/'4b-instruct'
    destination.parent.mkdir(parents=True,exist_ok=True)
    temp=destination.with_suffix('.tmp');temp.write_bytes(raw);temp.replace(destination)
    (FOLDER/'provenance.json').write_text(json.dumps({'model':'qwen3-vl:4b-instruct','manifest_sha256':hashlib.sha256(raw).hexdigest(),
        'files':[{'sha256':e['digest'],'size':e['size']} for e in entries]},indent=2))
    print('QWEN_LOCAL_MODEL_READY',flush=True)


if __name__=='__main__':main()
