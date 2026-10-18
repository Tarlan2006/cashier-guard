"""Validate exported snapshots against the local candidate set, then materialize labeled crops."""
import argparse,collections,datetime,hashlib,json,math,shutil
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parent
CLASSES={'banknotes','card','document','other','none','unclear'}
def validate(data,manifest):
 if data.get('schema_version')!=1 or data.get('set_id')!=manifest['set_id']:raise ValueError('Wrong label set')
 indexed={f['id']:f for f in manifest['frames']};seen=set()
 for row in data.get('examples',[]):
  if not isinstance(row.get('id'),str) or row['id'] in seen:raise ValueError('Missing or duplicate example ID')
  seen.add(row['id']);frame=indexed.get(row.get('frame_id'))
  if frame is None:raise ValueError('Unknown frame')
  for key in ['video','video_sha256','image_sha256','content_group','split']:
   if row.get(key)!=frame[key]:raise ValueError('Source metadata mismatch: '+key)
  if row.get('image_file')!=frame['file'] or row.get('time_sec')!=frame['time_sec']:raise ValueError('Frame metadata mismatch')
  if row.get('object_kind') not in CLASSES or row.get('review_status')!='human_labeled':raise ValueError('Invalid human label')
  b=row.get('bbox_xyxy_px')
  if not isinstance(b,list) or len(b)!=4 or any(type(x) not in (int,float) or not math.isfinite(x) for x in b):raise ValueError('Invalid bbox')
  if not (0<=b[0]<b[2]<=frame['width'] and 0<=b[1]<b[3]<=frame['height']):raise ValueError('Out-of-frame bbox')
  if not isinstance(row.get('note',''),str):raise ValueError('Invalid note')
 if not isinstance(data.get('skipped',[]),list) or any(i not in indexed for i in data.get('skipped',[])):raise ValueError('Unknown skipped frame')
 return {r['id']:r for r in data['examples']}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--set',type=Path,required=True);p.add_argument('--exports',type=Path,nargs='+',required=True);args=p.parse_args();source=args.set.resolve()
 if not source.is_relative_to((ROOT/'local').resolve()):p.error('Local set required')
 manifest=json.loads((source/'candidates.local.json').read_text());manifest['set_id']=source.name
 snapshots=[];maps=[]
 for file in args.exports:
  data=json.loads(file.read_text());maps.append(validate(data,manifest));snapshots.append(data)
 # A later exported superset is used as one snapshot, not concatenated.
 latest=maps[-1]
 if any(any(k not in latest or latest[k]!=v for k,v in old.items()) for old in maps[:-1]):raise ValueError('Snapshots have deletions or edited IDs; review before merging')
 selected=snapshots[-1];out=ROOT/'local'/('validated-objects-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir();(out/'exports').mkdir();(out/'crops').mkdir()
 for i,file in enumerate(args.exports):shutil.copy2(file,out/'exports'/f'{i}-{file.name}')
 indexed={f['id']:f for f in manifest['frames']};examples=[]
 for i,row in enumerate(selected['examples']):
  frame=indexed[row['frame_id']];image=source/frame['file']
  if hashlib.sha256(image.read_bytes()).hexdigest()!=frame['image_sha256']:raise ValueError('Source image checksum mismatch')
  with Image.open(image) as im:
   if im.size!=(frame['width'],frame['height']):raise ValueError('Image dimensions mismatch')
   b=row['bbox_xyxy_px'];bounds=[math.floor(b[0]),math.floor(b[1]),math.ceil(b[2]),math.ceil(b[3])];crop=im.crop(bounds);name=f'crops/object-{i:03d}.png';crop.save(out/name)
   item=dict(row,crop_file=name,crop_size_px=list(crop.size),crop_sha256=hashlib.sha256((out/name).read_bytes()).hexdigest());examples.append(item)
 groups={}
 for row in examples:
  groups.setdefault(row['video_sha256'],set()).add(row['split'])
 if any(len(s)>1 for s in groups.values()):raise ValueError('Video leakage between splits')
 labeled={r['frame_id'] for r in examples};skipped=set(selected.get('skipped',[]));classes={split:dict(collections.Counter(r['object_kind'] for r in examples if r['split']==split)) for split in ['development','heldout']}
 summary={'example_count':len(examples),'snapshot_counts':[len(m) for m in maps],'old_examples_identical_in_latest':True,'duplicates_avoided':sum(len(m) for m in maps)-len(latest),'classes_by_split':classes,'unique_frames':len(labeled),'unique_videos':len(groups),'skipped_frames':len(skipped),'labeled_and_skipped_overlap':len(labeled&skipped),'unreviewed_frames':len(indexed.keys()-labeled-skipped),'labels_source':'human_exports','visual_correctness_rechecked':False,'crop_boundary_validated':True}
 (out/'dataset.local.json').write_text(json.dumps({'schema_version':1,'set_id':source.name,'source_candidates':str(source),'examples':examples,'summary':summary},ensure_ascii=False,indent=2))
 (out/'summary.local.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print('VALIDATED_DATASET_READY:',out,flush=True);print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
