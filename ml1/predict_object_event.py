"""Apply a locally trained bag/documents event model to saved SAM observations."""
import argparse,hashlib,json
from pathlib import Path
import numpy as np
from scene_mvp.object_event_model import extract,predict

def main():
    p=argparse.ArgumentParser();p.add_argument('--model',type=Path,required=True);p.add_argument('--observations',type=Path,required=True);p.add_argument('--calibration',type=Path,required=True);p.add_argument('--output',type=Path);args=p.parse_args();meta=json.loads((args.model/'model-metadata.local.json').read_text());path=args.model/'object-event-model.npz'
    if meta.get('schema_version')!='object-event-model/1' or hashlib.sha256(path.read_bytes()).hexdigest()!=meta['model_sha256']:p.error('Model version/hash mismatch')
    profile=json.loads(args.calibration.read_text());observations=json.loads(args.observations.read_text());features=extract(observations,profile,meta['feature_spec'])
    with np.load(path,allow_pickle=False) as weights:model={k:weights[k] for k in weights.files}
    result={'schema_version':'object-event-prediction/1','source_video_sha256':profile['source_video_sha256'],'object_kind':profile['target_object_kind'],'model_sha256':meta['model_sha256'],'is_training_video':profile['source_video_sha256'] in meta['source_video_sha256'],'joint_observed_coverage':features['joint_observed_coverage'],'valid_windows':len(features['windows']),**predict(model,features,meta['feature_spec'])}
    if args.output:args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='window_scores'},ensure_ascii=False,allow_nan=False))

if __name__=='__main__':main()
