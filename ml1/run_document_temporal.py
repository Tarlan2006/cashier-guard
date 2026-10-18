"""Associate local candidates across saved frames without deriving identity violations."""
import argparse, datetime, hashlib, json
from pathlib import Path
import cv2
import numpy as np
from run_ollama_trial import ROOT,write_json
from import_document_search_review import validate
from scene_mvp.document_search import crop_box
from scene_mvp.document_temporal import SPEC,associate


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--trial',type=Path,required=True);args=parser.parse_args()
    trial=args.trial.resolve()
    if not trial.is_relative_to((ROOT/'local').resolve()):parser.error('Local candidate trial required')
    protocol=json.loads((trial/'protocol.local.json').read_text());predictions=json.loads((trial/'predictions.local.json').read_text())
    source=ROOT/'local'/protocol['source_session'];session=json.loads((source/'session.local.json').read_text())
    if sha(Path(session['source_video']))!=protocol['source_video_sha256']:parser.error('Source video changed')
    out=ROOT/'local'/('document-temporal-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir()
    write_json(out/'protocol.local.json',{'spec':SPEC,'input_protocol_sha256':sha(trial/'protocol.local.json'),
       'input_predictions_sha256':sha(trial/'predictions.local.json'),'source_video_sha256':protocol['source_video_sha256'],
       'source_session':protocol['source_session'],'temporal_module_sha256':sha(ROOT/'scene_mvp/document_temporal.py'),
       'runner_sha256':sha(Path(__file__)),'prior_source_human_labels_known':True,'independent_evaluation':False,
       'automatic_candidate_deletion':False,'approved_for_rule_engine':False,'legal_violation_label':None})
    frames={round(f['timestamp_sec'],6):f for f in session['frames']};rows=[]
    for row in predictions['timeline']:
        frame=frames[round(row['timestamp_sec'],6)];path=source/frame['file']
        if sha(path)!=row['frame_sha256']:raise ValueError('Predicted frame changed')
        image=cv2.imread(str(path));h,w=image.shape[:2];proposals=[]
        for index,p in enumerate(row['proposals']):
            if p['selection_state']!='retained_candidate':continue
            crop,_=crop_box(image,p['bbox']);hsv=cv2.cvtColor(crop,cv2.COLOR_BGR2HSV)
            hist=cv2.calcHist([hsv],[0,1],None,[8,4],[0,180,0,256]).ravel().astype(float);hist/=max(hist.sum(),1)
            proposals.append({**p,'proposal_index':index,'appearance':hist.tolist(),
                 'association_box_px':[p['bbox'][0]*w,p['bbox'][1]*h,p['bbox'][2]*w,p['bbox'][3]*h]})
        rows.append({'timestamp_sec':row['timestamp_sec'],'proposals':proposals})
    result=associate(rows);write_json(out/'candidate-tracks.local.json',result)
    tracks={tr['track_id']:tr for tr in result['tracks']}
    lookup={(round(r['timestamp_sec'],6),p['proposal_index']):tracks[p['track_id']]['priority'] for r in result['timeline'] for p in r['candidate_tracks']}
    # Human labels enter only this post-association development audit.
    review=json.loads((trial/'human-candidate-review.accepted.local.json').read_text());validate(review,trial)
    checks=[]
    for row in review['reviews']:
        selection=row['human_selection']
        indices=list(range(len(row['proposals']))) if selection=='none' else [ord(selection)-65] if selection in {'A','B','C'} else []
        for index in indices:
            priority=lookup.get((round(row['timestamp_sec'],6),index),'rejected_by_patch_filter')
            checks.append({'timestamp_sec':row['timestamp_sec'],'proposal_index':index,'human_positive':selection!='none','temporal_priority':priority})
    summary={'input_retained_boxes':sum(len(r['proposals']) for r in rows),'candidate_tracks':len(tracks),
       'repeated_candidate_tracks':sum(tr['priority']=='repeated_candidate' for tr in tracks.values()),
       'short_candidate_tracks':sum(tr['priority']!='repeated_candidate' for tr in tracks.values()),
       'reviewed_positive_boxes':sum(c['human_positive'] for c in checks),
       'reviewed_positive_boxes_with_repeated_priority':sum(c['human_positive'] and c['temporal_priority']=='repeated_candidate' for c in checks),
       'reviewed_incorrect_boxes_with_repeated_priority':sum(not c['human_positive'] and c['temporal_priority']=='repeated_candidate' for c in checks),
       'reviewed_incorrect_retained_boxes_with_short_priority':sum(not c['human_positive'] and c['temporal_priority']=='short_candidate_needs_review' for c in checks),
       'all_input_candidates_preserved_for_review':True,'reviewed_source_already_known_development_only':True,
       'document_identity_or_presentation_established':False,'approved_for_rule_engine':False}
    write_json(out/'development-audit.local.json',{'summary':summary,'reviewed_boxes':checks})
    write_json(ROOT/'local/document-temporal-current.local.json',{'trial':str(out),'status':'candidate_association_experimental','summary':summary})
    print('DOCUMENT_TEMPORAL_READY:',out);print(json.dumps(summary))


if __name__=='__main__':main()
