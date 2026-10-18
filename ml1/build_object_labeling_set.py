"""Prepare local unlabeled candidates; split by content hash, never by individual frame."""
import argparse,base64,datetime,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'ml2'))
from backend.pipeline.video import VideoReader
import cv2

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--video-root',type=Path,required=True)
 p.add_argument('--exclude-sets',type=Path,nargs='*',default=[])
 p.add_argument('--development-only',action='store_true')
 p.add_argument('--videos',type=int,default=12)
 p.add_argument('--fractions',type=float,nargs='+',default=[.25,.5,.75])
 args=p.parse_args()
 if args.videos<2 or not args.fractions or any(not 0<f<1 for f in args.fractions):p.error('Invalid sampling settings')
 excluded=set()
 for prior in args.exclude_sets:
  previous=json.loads((prior/'candidates.local.json').read_text());excluded.update(f['video_sha256'] for f in previous['frames'])
 manifest=json.loads((ROOT/'outputs/forte_dataset_manifest.json').read_text())
 groups={}
 for v in manifest['videos']:
  if v['content_group']=='X-1' or v['sha256'] in excluded:continue
  groups.setdefault(v['sha256'],v)
 ordered=sorted(groups.values(),key=lambda v:int(v['content_group'].split('-')[1]))
 if len(ordered)<args.videos:p.error('Not enough unused video groups')
 selected=[ordered[round(i*(len(ordered)-1)/(args.videos-1))] for i in range(args.videos)]
 assert len({v['sha256'] for v in selected})==args.videos
 out=ROOT/'local'/('object-labeling-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir();frames=[]
 for index,v in enumerate(selected):
  source=(args.video_root/v['relative_path']).resolve()
  if not source.is_relative_to(args.video_root.resolve()):raise ValueError('Invalid source path')
  h=hashlib.sha256(source.read_bytes()).hexdigest()
  if h!=v['sha256']:raise RuntimeError('Source content mismatch')
  split='development' if args.development_only or index%2==0 else 'heldout'
  with VideoReader(source) as reader:
   duration=reader.metadata.duration_sec
   for n,fraction in enumerate(sorted(set(args.fractions))):
    target=min(duration-.1,duration*fraction);sample=reader.read_at(target)
    name=f'{index:02d}-{n}.jpg';ok,encoded=cv2.imencode('.jpg',sample.frame_bgr,[cv2.IMWRITE_JPEG_QUALITY,96])
    if not ok:raise RuntimeError('Encoding failed')
    (out/name).write_bytes(encoded.tobytes())
    height,width=sample.frame_bgr.shape[:2]
    frames.append({'id':f'{v["content_group"]}-{n}','file':name,'video':v['filename'],'content_group':v['content_group'],'video_sha256':h,'split':split,'time_sec':sample.actual_timestamp_sec,'width':width,'height':height,'review_status':'unreviewed','image_sha256':hashlib.sha256(encoded.tobytes()).hexdigest()})
  print('Prepared source',index+1,'/',len(selected),flush=True)
 data={'schema_version':1,'purpose':'object_candidates_require_human_labels','frames':frames,'excluded_tuning_group':'X-1','split_policy':'all copies and frames of a video SHA-256 belong to one split','classes':['banknotes','card','document','other','none','unclear'],'model_predictions_supplied':False,'verified_example_count':0,'excluded_prior_sets':[str(x.resolve()) for x in args.exclude_sets],'development_only':args.development_only}
 (out/'candidates.local.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
 ui_data=[dict(f,image='data:image/jpeg;base64,'+base64.b64encode((out/f['file']).read_bytes()).decode()) for f in frames]
 template=(ROOT/'object_labeling_template.html').read_text();payload=json.dumps(ui_data,ensure_ascii=False).replace('<','\\u003c')
 page=template.replace('__DATA__',payload).replace('__SET_ID__',out.name)
 (out/'label.html').write_text(page,encoding='utf-8')
 print('LABELING_READY:',out/'label.html',flush=True)
 print(json.dumps({'videos':len(selected),'candidate_frames':len(frames),'development_frames':sum(f['split']=='development' for f in frames),'heldout_frames':sum(f['split']=='heldout' for f in frames),'verified_examples':0,'duplicate_video_hashes_across_splits':0}))
if __name__=='__main__':main()
