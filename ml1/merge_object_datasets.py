"""Merge validated local labeling batches; preserve original split and human labels."""
import argparse,collections,datetime,json,shutil,hashlib
from pathlib import Path
from run_ollama_trial import ROOT,write_json

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--datasets',type=Path,nargs='+',required=True);args=p.parse_args();out=ROOT/'local'/('merged-objects-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir();(out/'crops').mkdir();rows=[];seen=set();groups={}
 for folder in args.datasets:
  folder=folder.resolve()
  if not folder.is_relative_to((ROOT/'local').resolve()):p.error('Local dataset required')
  d=json.loads((folder/'dataset.local.json').read_text())
  for r in d['examples']:
   identity=(r['image_sha256'],tuple(r['bbox_xyxy_px']),r['object_kind'])
   if identity in seen:continue
   seen.add(identity);source=(folder/r['crop_file']).resolve()
   if not source.is_relative_to(folder) or hashlib.sha256(source.read_bytes()).hexdigest()!=r['crop_sha256']:raise ValueError('Crop integrity failure')
   name=f'crops/object-{len(rows):03d}.png';shutil.copy2(source,out/name);rows.append(dict(r,crop_file=name,source_set_id=d['set_id'],source_dataset=str(folder)))
   groups.setdefault(r['video_sha256'],set()).add(r['split'])
 if any(len(v)>1 for v in groups.values()):raise ValueError('Video crosses split boundary')
 summary={'examples':len(rows),'classes_by_split':{split:dict(collections.Counter(r['object_kind'] for r in rows if r['split']==split)) for split in ['development','heldout']},'videos':len(groups),'cross_split_video_duplicates':0,'labels_source':'human','visual_correctness_rechecked':False}
 write_json(out/'dataset.local.json',{'schema_version':1,'examples':rows,'source_datasets':[str(p.resolve()) for p in args.datasets],'summary':summary});write_json(out/'summary.local.json',summary)
 print('MERGED_OBJECT_DATASET_READY:',out,flush=True);print(json.dumps(summary))
if __name__=='__main__':main()
