"""Small end-to-end augmentation check; fresh detections, open videos only."""
from __future__ import annotations
import argparse
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
import sys
import time
import av
from av.video.reformatter import Colorspace
import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from eval.v8_distances import number,median_scene,transform,transform_facts,summary,signature
from backend.pipeline.video import VideoReader
from backend.pipeline.perception.distances import ImageDistance,PlanarDistance,RelativeDepthDistance,auto_workzone,annotate_proximity
from backend.pipeline.perception.roles_v2 import assign_temporal_roles


def augment_video(source: Path, target: Path, variant: str):
    """Reencode every source frame with its PTS, including the control video."""
    target.parent.mkdir(parents=True,exist_ok=True)
    with VideoReader(source) as oriented,av.open(str(source)) as original:
        stream=original.streams.video[0]
        base=stream.time_base
        first=oriented.read_at(0).frame_bgr
        transformed,matrix=transform(first,variant)
        height,width=transformed.shape[:2]
        height+=height%2;width+=width%2
        with av.open(str(target),'w',format='mp4') as output:
            encoded=output.add_stream('libx264',rate=stream.average_rate or Fraction(30))
            encoded.width,encoded.height=width,height
            encoded.pix_fmt='yuv420p'
            encoded.time_base=encoded.codec_context.time_base=base
            encoded.codec_context.thread_count=2
            encoded.options={'preset':'veryfast','crf':'18','bf':'0'}
            original.streams.video[0].codec_context.thread_count=1
            for raw in original.decode(stream):
                # Same explicit color conversion and orientation as production.
                image=oriented._orient(raw.to_ndarray(format='bgr24',src_colorspace=Colorspace.ITU601))
                image,_=transform(image,variant)
                image=cv2.copyMakeBorder(image,0,height-image.shape[0],0,width-image.shape[1],cv2.BORDER_CONSTANT,value=(64,64,64))
                frame=av.VideoFrame.from_ndarray(image,format='bgr24')
                frame.pts,frame.time_base=raw.pts,raw.time_base
                for packet in encoded.encode(frame):output.mux(packet)
            for packet in encoded.encode():output.mux(packet)
    return matrix


def iou(a,b):
    a,b=np.asarray(a),np.asarray(b)
    inter=np.maximum(np.minimum(a[2:],b[2:])-np.maximum(a[:2],b[:2]),0).prod()
    return float(inter/max(np.prod(a[2:]-a[:2])+np.prod(b[2:]-b[:2])-inter,1e-9))


def matched_stability(reference: dict, current: dict, matrix) -> dict:
    projected,_=transform_facts(reference,matrix,(current['video']['height'],current['video']['width']))
    original_count=0;matches=[]
    for row in projected['frames']:
        t=row['actual_timestamp_sec']
        other=min(current['frames'],key=lambda r:abs(r['actual_timestamp_sec']-t))
        old=[p for p in row['persons'] if p.get('counted') and not p.get('is_reflection')]
        new=[p for p in other['persons'] if p.get('counted') and not p.get('is_reflection')]
        original_count+=len(old)
        if not old or not new or abs(other['actual_timestamp_sec']-t)>.05:continue
        costs=np.array([[1-iou(a['bbox'],b['bbox']) for b in new] for a in old])
        left,right=linear_sum_assignment(costs)
        for a,b in zip(left,right):
            if costs[a,b]<=.8:matches.append((old[a],new[b]))
    return dict(matched=len(matches),reference_observations=original_count,
                coverage=len(matches)/max(1,original_count),
                **{key:float(np.mean([a.get(key)==b.get(key) for a,b in matches])) if matches else None
                   for key in ('role','near_table','near_machine')})


def run(args):
    if sys.platform=='win32':
        import ctypes
        ctypes.WinDLL('kernel32').SetThreadExecutionState(0x80000001)
    from backend.pipeline.perception.config import load_config
    from backend.pipeline.perception.run import perceive_video
    from backend.pipeline.perception.detector import get_detector
    from backend.pipeline.perception.semantic_model import get_semantic_model
    from backend.pipeline.perception.depth import LocalDepthSmall
    root=args.open_root.resolve()
    videos={number(p):p.resolve() for p in (root/'videos').glob('*.mov')}
    if any(not p.is_relative_to(root) for p in videos.values()):raise ValueError('Outside open dataset')
    config=load_config()
    config.model_path=str(args.model_root/'rtdetr_r18vd')
    config.fixture_model_path=str(args.model_root/'siglip-base-patch16-224')
    detector=get_detector(config)
    semantic=get_semantic_model(config.fixture_model_path,config.torch_threads,config.device)
    depth_model=LocalDepthSmall(args.depth_model,threads=config.torch_threads)
    args.output.mkdir(parents=True,exist_ok=True)
    records=[];references={}
    for n in args.videos:
        for variant in ('original','mirror','rotate_20','rotate_-20'):
            path=args.output/f'{n:02}-{variant}.mp4'
            matrix=augment_video(videos[n],path,variant)
            semantic.encoder.clear_video_cache()
            started=time.perf_counter();facts=perceive_video(path,config,detector=detector);wall=time.perf_counter()-started
            (args.output/f'{n:02}-{variant}.facts.json').write_text(json.dumps(facts,ensure_ascii=False,indent=2),encoding='utf-8')
            picture,median_sec=median_scene(path)
            started=time.perf_counter();hypothesis=auto_workzone(picture,facts);quad_sec=time.perf_counter()-started
            depth,depth_sec=depth_model.predict(picture)
            h,w=picture.shape[:2]
            metrics={'pixel':ImageDistance(w,h),'foot':ImageDistance(w,h,use_feet=True)}
            if hypothesis is not None:
                metrics.update(A=PlanarDistance(w,h,hypothesis),B=RelativeDepthDistance(w,h,depth,hypothesis))
            else:
                records.extend(dict(video=n,variant=variant,method=name,status='unavailable',
                                    reason='No automatic desk/workzone hypothesis',
                                    perception_sec=wall,complete=facts['runtime']['complete'])
                               for name in ('A','B'))
            for name,metric in metrics.items():
                copy=deepcopy(facts)
                started=time.perf_counter()
                try:
                    assign_temporal_roles(copy,config.role_settings,distance_model=None if name=='pixel' else metric)
                    annotate_proximity(copy,metric)
                    extra=(time.perf_counter()-started)+(median_sec+quad_sec+(depth_sec if name=='B' else 0) if name in {'A','B'} else 0)
                    record=dict(video=n,variant=variant,method=name,summary=summary(copy),
                                perception_sec=wall,extra_sec=extra,complete=facts['runtime']['complete'],
                                detection_cache=False,source='fresh_end_to_end_detections',status='ok')
                    if variant=='original':references[n,name]=deepcopy(copy)
                    else:record['stability']=matched_stability(references[n,name],copy,matrix)
                    records.append(record)
                except ValueError as exc:
                    records.append(dict(video=n,variant=variant,method=name,error=str(exc)))
            (args.output/'records.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
            print(json.dumps(dict(video=n,variant=variant,perception_sec=wall,depth_sec=depth_sec,complete=facts['runtime']['complete'])),flush=True)
    semantic.encoder.clear_video_cache()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--open-root',type=Path,required=True)
    parser.add_argument('--model-root',type=Path,required=True)
    parser.add_argument('--depth-model',type=Path,default=ROOT/'models/depth-anything-v2-small')
    parser.add_argument('--output',type=Path,default=ROOT/'cache/v8/end_to_end')
    parser.add_argument('--videos',type=int,nargs='+',default=[18,33])
    run(parser.parse_args())
