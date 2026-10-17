"""Open-set geometry experiment; detections replayed to isolate distances.

This does not claim end-to-end detector robustness or metric floor calibration.
All source pixels must be under the explicitly supplied open-dataset directory.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import sys
import time
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.pipeline.video import VideoReader
from backend.pipeline.perception.config import load_config
from backend.pipeline.perception.roles_v2 import assign_temporal_roles
from backend.pipeline.perception.distances import (
    ImageDistance, PlanarDistance, RelativeDepthDistance, auto_workzone,
    annotate_proximity, corners, footpoint,
)


def number(path: Path) -> int:
    match = re.fullmatch(r'[XХ]-(\d+)', path.stem)
    if not match:
        raise ValueError('Expected X/Х-number video name')
    return int(match[1])


def median_scene(path: Path) -> tuple[np.ndarray, float]:
    started = time.perf_counter()
    with VideoReader(path) as reader:
        images = [reader.read_at(float(t)).frame_bgr for t in
                  np.linspace(.05,.95,9)*reader.metadata.duration_sec]
    return np.median(np.stack(images),axis=0).astype(np.uint8), time.perf_counter()-started


def transform(image: np.ndarray, variant: str):
    h,w = image.shape[:2]
    if variant == 'original':
        return image.copy(), np.array([[1,0,0],[0,1,0]],float)
    if variant == 'mirror':
        return image[:,::-1].copy(), np.array([[-1,0,w],[0,1,0]],float)
    angle = float(variant.split('_')[1])
    matrix = cv2.getRotationMatrix2D((w/2,h/2),angle,1)
    radians = np.deg2rad(angle)
    new_w = int(np.ceil(w*abs(np.cos(radians))+h*abs(np.sin(radians))))
    new_h = int(np.ceil(h*abs(np.cos(radians))+w*abs(np.sin(radians))))
    matrix[:,2] += [(new_w-w)/2,(new_h-h)/2]
    return cv2.warpAffine(image,matrix,(new_w,new_h),borderValue=(64,64,64)), matrix


def warp_points(points, matrix, old_size, new_size):
    return (np.c_[np.asarray(points)*old_size,np.ones(len(points))]@matrix.T)/new_size


def transform_facts(facts: dict, matrix, shape) -> tuple[dict,float]:
    result=deepcopy(facts)
    old_size=np.array([facts['video']['width'],facts['video']['height']],float)
    new_size=np.array([shape[1],shape[0]],float)
    errors=[]
    def box(value):
        p=warp_points(corners(value),matrix,old_size,new_size)
        return np.r_[p.min(axis=0),p.max(axis=0)].clip(0,1).tolist()
    for frame in result['frames']:
        for person in frame['persons']:
            original=person['bbox']
            transformed=box(original)
            ideal=warp_points([footpoint(original)],matrix,old_size,new_size)[0]
            errors.append(float(np.linalg.norm((ideal-footpoint(transformed))*new_size)/np.linalg.norm(new_size)))
            person['bbox']=transformed
        for obj in frame.get('objects',[]):obj['bbox']=box(obj['bbox'])
    for obj in result.get('fixtures',[]):obj['bbox']=box(obj['bbox'])
    result['video'].update(width=int(new_size[0]),height=int(new_size[1]))
    return result, float(np.median(errors)) if errors else 0


def signature(facts: dict) -> dict:
    return {(i,p['id']):(p.get('role','unknown'),bool(p.get('near_table')),bool(p.get('near_machine')))
            for i,row in enumerate(facts['frames']) for p in row['persons']
            if p.get('counted') and not p.get('is_reflection')}


def summary(facts: dict) -> dict:
    people=[p for row in facts['frames'] for p in row['persons'] if p.get('counted') and not p.get('is_reflection')]
    tracks={}
    for identifier in sorted({p['id'] for p in people}):
        rows=[p for p in people if p['id']==identifier]
        tracks[str(identifier)]=dict(
            role=sorted({p['role'] for p in rows}),
            cashier_prob=max(p.get('cashier_prob',0) for p in rows),
            client_prob=max(p.get('client_prob',0) for p in rows),
            near_table_fraction=float(np.mean([p['near_table'] for p in rows])),
            near_machine_fraction=float(np.mean([p['near_machine'] for p in rows])),
            uncertain=any(p.get('uncertain') for p in rows))
    return dict(cashier=sorted({p['id'] for p in people if p['role']=='cashier_candidate'}),
                clients=sorted({p['id'] for p in people if p['role']=='client_candidate'}),tracks=tracks)


def run(args):
    import ctypes
    if sys.platform=='win32':ctypes.WinDLL('kernel32').SetThreadExecutionState(0x80000001)
    from backend.pipeline.perception.depth import LocalDepthSmall
    np.random.seed(42)
    args.output.mkdir(parents=True,exist_ok=True)
    source=args.open_root.resolve()
    videos={number(p):p.resolve() for p in (source/'videos').glob('*.mov')}
    if any(not p.is_relative_to(source) for p in videos.values()):raise ValueError('Outside open dataset')
    config=load_config()
    model=LocalDepthSmall(args.depth_model,device=args.device,threads=config.torch_threads)
    records=[]
    signatures={}
    for n in args.videos:
        facts=json.loads((args.facts_dir/f'{n:02}.facts.json').read_text(encoding='utf-8'))
        if number(Path(facts['video']['name']))!=n:raise ValueError('Facts/video mismatch')
        image,median_sec=median_scene(videos[n])
        for variant in ('original','mirror','rotate_20','rotate_-20'):
            picture,matrix=transform(image,variant)
            transformed,foot_error=transform_facts(facts,matrix,picture.shape)
            h,w=picture.shape[:2]
            start=time.perf_counter();hypothesis=auto_workzone(picture,transformed);quad_sec=time.perf_counter()-start
            depth,depth_sec=model.predict(picture)  # exactly once per virtual video
            candidates={'pixel':ImageDistance(w,h),'foot':ImageDistance(w,h,use_feet=True)}
            if hypothesis is not None:
                candidates['A']=PlanarDistance(w,h,hypothesis)
                candidates['B']=RelativeDepthDistance(w,h,depth,hypothesis)
            else:
                records.extend(dict(video=n,variant=variant,method=name,status='unavailable',
                                    reason='No automatic desk/workzone hypothesis')
                               for name in ('A','B'))
            np.savez_compressed(args.output/f'{n:02}-{variant}.npz',depth=depth,quad=hypothesis.quad if hypothesis else np.empty((0,2)))
            for name,metric in candidates.items():
                copy=deepcopy(transformed)
                started=time.perf_counter()
                try:
                    assign_temporal_roles(copy,config.role_settings,distance_model=None if name=='pixel' else metric)
                    annotate_proximity(copy,metric)
                    elapsed=time.perf_counter()-started
                    record=dict(video=n,variant=variant,method=name,summary=summary(copy),
                        geometry_sec=elapsed,median_sec=median_sec,
                        quad_sec=quad_sec if name=='A' else 0,
                        depth_sec=depth_sec if name=='B' else 0,
                        extra_sec=0,calibrated_floor=False,
                        hypothesis_source=hypothesis.source if hypothesis and name in {'A','B'} else None,
                        footpoint_rotation_error_diag=foot_error,
                        source='replayed_unmodified_detections',status='ok')
                    record['extra_sec']=(median_sec+quad_sec+(depth_sec if name=='B' else 0)+elapsed) if name in {'A','B'} else elapsed
                    signatures[n,variant,name]=signature(copy)
                except ValueError as exc:
                    record=dict(video=n,variant=variant,method=name,status='unavailable',reason=str(exc))
                records.append(record)
                (args.output/'records.json').write_text(json.dumps(dict(records=records,model_load_sec=model.load_sec),indent=2),encoding='utf-8')
            print(json.dumps({'video':n,'variant':variant,'depth_sec':depth_sec,'median_sec':median_sec,'quad':hypothesis.source if hypothesis else None}),flush=True)
    for record in records:
        n,v,m=record['video'],record['variant'],record['method']
        if record['status']!='ok' or v=='original':continue
        original=signatures[n,'original',m];current=signatures[n,v,m]
        keys=sorted(set(original)&set(current))
        record['stability']={key:float(np.mean([original[k][i]==current[k][i] for k in keys])) if keys else None
                             for i,key in enumerate(('role','near_table','near_machine'))}
        record['compared_observations']=len(keys)
    (args.output/'records.json').write_text(json.dumps(dict(records=records,model_load_sec=model.load_sec),indent=2),encoding='utf-8')
    return records


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--open-root',type=Path,required=True)
    parser.add_argument('--facts-dir',type=Path,required=True)
    parser.add_argument('--depth-model',type=Path,default=ROOT/'models/depth-anything-v2-small')
    parser.add_argument('--output',type=Path,default=ROOT/'cache/v8')
    parser.add_argument('--videos',nargs='+',type=int,default=[2,3,4,14,17,18,33,43])
    parser.add_argument('--device',default='cpu')
    run(parser.parse_args())
