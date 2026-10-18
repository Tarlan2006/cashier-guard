"""Download and checksum only the pinned public RT-DETR source files."""
import hashlib,json,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parent
repo=ROOT.parent
manifest=json.loads((repo/'ml2/configs/model_manifest.json').read_text())
revision=next(x['revision'] for x in manifest['models'] if x['name']=='PekingU/rtdetr_r18vd')
folder=ROOT/'models/rtdetr_r18vd';folder.mkdir(parents=True,exist_ok=True)
def checksum(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
for relative,expected in manifest['source_files'].items():
 if not relative.startswith('rtdetr_r18vd/'):continue
 name=Path(relative).name;destination=folder/name
 if destination.is_file() and checksum(destination)==expected['sha256']:
  print('Already verified:',name,flush=True);continue
 url=f'https://huggingface.co/PekingU/rtdetr_r18vd/resolve/{revision}/{name}?download=true&fresh={int(time.time())}'
 partial=destination.with_suffix(destination.suffix+'.part')
 for attempt in range(3):
  try:
   with urllib.request.urlopen(url,timeout=60) as source,partial.open('wb') as output:
    size=0
    while block:=source.read(1024*1024):
     output.write(block);size+=len(block)
     if size%(8*1024*1024)==0:print(name,'downloaded_MiB',size//1024**2,flush=True)
   if partial.stat().st_size!=expected['size'] or checksum(partial)!=expected['sha256']:raise ValueError('Public source checksum mismatch')
   partial.replace(destination);print('SHA256 verified:',name,flush=True);break
  except Exception:
   if attempt==2:raise
   time.sleep(2)
(folder/'source-provenance.json').write_text(json.dumps({'repository':'PekingU/rtdetr_r18vd','revision':revision,'verified':True},indent=2))
print('PERSON_SOURCE_READY',flush=True)
