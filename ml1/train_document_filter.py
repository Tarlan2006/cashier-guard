"""Train a local reviewed-candidate head with whole-video development folds."""
import datetime, hashlib, json, math, time
from pathlib import Path
import cv2
import numpy as np
from run_ollama_trial import ROOT, write_json
from import_document_search_review import validate as validate_candidate_review
from run_document_reference_search import validate_frames
from scene_mvp.document_search import crop_box
from scene_mvp.document_filter import SPEC, candidate_examples, grouped_folds, fit, scores, decision, metrics
from scene_mvp.neural_features import FrozenDoorFeatures as FrozenPatchFeatures


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def contextual_box(box, factor):
    cx=(box[0]+box[2])/2;cy=(box[1]+box[3])/2
    width=(box[2]-box[0])*factor;height=(box[3]-box[1])*factor
    return [max(0,cx-width/2),max(0,cy-height/2),min(1,cx+width/2),min(1,cy+height/2)]


def patch_features(extractor,image,box):
    tight,_=crop_box(image,box);context,_=crop_box(image,contextual_box(box,SPEC['crop_context_scale']))
    vector=np.r_[extractor.feature(tight),extractor.feature(context)]
    return vector/max(float(np.linalg.norm(vector)),1e-12)


def main():
    cv2.setNumThreads(2);started=time.monotonic()
    search_pointer=json.loads((ROOT/'local/document-search-current.local.json').read_text())
    trial=Path(search_pointer['trial']);review_path=trial/'human-candidate-review.accepted.local.json'
    accepted=json.loads(review_path.read_text())
    if sha(trial/'human-candidate-review.original.local.json') != accepted['review_sha256']:
        raise ValueError('Original human candidate review changed')
    validate_candidate_review(accepted,trial)
    rows=candidate_examples(accepted)
    dataset=Path(json.loads((ROOT/'local/identity-dataset-current.local.json').read_text())['dataset'])
    visual_labels=[json.loads(line) for line in (dataset/'video-observations.jsonl').read_text().splitlines()]
    sessions={}
    for record in visual_labels:
        folder=ROOT/'local'/record['source_session'];session=json.loads((folder/'session.local.json').read_text())
        if sha(Path(session['source_video'])) != record['source_video_sha256']:
            raise ValueError('Original source video changed')
        validate_frames(record,folder,session)
        sessions[record['source_session']]={'folder':folder,'session':session}
        seed=record.get('document_seed')
        if not seed: continue
        if seed['object_kind'] != 'human_confirmed_identity_document': continue
        frame=min(session['frames'],key=lambda f:abs(f['timestamp_sec']-seed['timestamp_sec']))
        if abs(frame['timestamp_sec']-seed['timestamp_sec'])>.001: raise ValueError('Human seed does not bind to exact cached frame')
        frame_sha=sha(folder/frame['file']);frame_group=record['source_video_sha256']+':'+frame_sha
        # Do not count the old X-1 box and its newly reviewed retrieval as separate positives.
        if any(r['frame_group']==frame_group and r['label']==1 for r in rows): continue
        rows.append({'source_session':record['source_session'],'source_video_sha256':record['source_video_sha256'],
                     'frame_sha256':frame_sha,'timestamp_sec':frame['timestamp_sec'],'bbox':seed['bbox'],'label':1,
                     'label_kind':'human_document_seed_box','label_source':'previous_accepted_human_object_box',
                     'frame_group':frame_group,'split_group':record['source_video_sha256']})
    out=ROOT/'local'/('document-filter-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir()
    manifest={'schema_version':'document-candidate-training/1','candidate_review_sha256':sha(review_path),
              'candidate_original_export_sha256':accepted['review_sha256'],'source_search_protocol_sha256':sha(trial/'protocol.local.json'),
              'spec':SPEC,'rows':len(rows),'positive_boxes':sum(r['label']==1 for r in rows),'negative_boxes':sum(r['label']==0 for r in rows),
              'unique_frame_groups':len({r['frame_group'] for r in rows}),'unique_video_groups':len({r['split_group'] for r in rows}),
              'label_scope':'correct_localized_document_candidate_not_whole_video_document_presence',
              'source_reference_video_used_to_mine_candidates':json.loads((trial/'protocol.local.json').read_text())['reference_source_sha256'],
              'proposal_mining_used_known_reference_and_prior_labels':True,
              'cross_validation_scope':'head_only_whole_video_grouped_development_check_not_blind_end_to_end_evaluation',
              'rule_engine_enabled':False,'legal_violation_label':None,'bank_data_uploaded':False,
              'runner_sha256':sha(Path(__file__)),'head_module_sha256':sha(ROOT/'scene_mvp/document_filter.py'),
              'frozen_encoder_module_sha256':sha(ROOT/'scene_mvp/neural_features.py')}
    write_json(out/'protocol.local.json',manifest)
    (out/'examples.local.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
    print('DOCUMENT_FILTER_TRAINING:',out,flush=True)
    extractor=FrozenPatchFeatures(ROOT/'models/rtdetr_r18vd',threads=2);x=[]
    for index,row in enumerate(rows):
        source=sessions[row['source_session']];folder=source['folder'];session=source['session']
        frame=min(session['frames'],key=lambda f:abs(f['timestamp_sec']-row['timestamp_sec']))
        if abs(frame['timestamp_sec']-row['timestamp_sec'])>.001 or sha(folder/frame['file'])!=row['frame_sha256']:
            raise ValueError('Reviewed candidate no longer binds to original cached frame')
        if session['source_video_sha256']!=row['source_video_sha256']: raise ValueError('Wrong source group')
        x.append(patch_features(extractor,cv2.imread(str(folder/frame['file'])),row['bbox']))
        if (index+1)%10==0: print('PATCH_FEATURES:',index+1,'/',len(rows),flush=True)
    x=np.asarray(x,np.float64);np.savez_compressed(out/'features.local.npz',features=x)
    heldout=np.full(len(rows),np.nan);folds=[]
    for group,train,test in grouped_folds(rows):
        head=fit(x[train],[rows[i] for i in train]);values=scores(head,x[test]);heldout[test]=values
        folds.append({'held_out_video_sha256':group,'train_groups':sorted({rows[i]['split_group'] for i in train}),
                      'test_frames':len({rows[i]['frame_group'] for i in test}),
                      'result':metrics([rows[i] for i in test],values)})
    if not np.isfinite(heldout).all(): raise ValueError('Every row requires held-out prediction')
    cv_result=metrics(rows,heldout)
    model=fit(x,rows);np.savez_compressed(out/'candidate-head.local.npz',mean=model['mean'],weight=model['weight'],bias=model['bias'])
    fitted=scores(model,x)
    predictions=[{**r,'held_out_head_score':float(o),'held_out_head_decision':decision(o),'all_data_fit_score':float(s),
                  'all_data_score_is_not_validation':True} for r,o,s in zip(rows,heldout,fitted)]
    write_json(out/'development-predictions.local.json',{'examples':predictions,'folds':folds})
    success=cv_result['accepted_positive_boxes']==cv_result['positive_boxes'] and cv_result['false_accepted_rejected_boxes']==0
    summary={'training_examples':manifest['rows'],'unique_video_groups':manifest['unique_video_groups'],'unique_frame_groups':manifest['unique_frame_groups'],
             'held_out_head_check':cv_result,'fitted_training_check_not_validation':metrics(rows,fitted),
             'development_candidate_gate_passed':success,'end_to_end_detector_validated':False,
             'absence_detection_validated':False,'approved_for_rule_engine':False,'elapsed_sec':round(time.monotonic()-started,2)}
    write_json(out/'model-metadata.local.json',{'spec':SPEC,'feature_spec':extractor.spec,'views':['tight','context_1.5'],
               'feature_normalization':'L2_concat','model_sha256':sha(out/'candidate-head.local.npz'),
               'training_video_sha256':sorted({r['split_group'] for r in rows}),'classifier_scope':manifest['label_scope'],
               'identity_document_semantic_classifier':False,'approved_for_rule_engine':False})
    write_json(out/'summary.local.json',summary)
    write_json(ROOT/'local/document-filter-current.local.json',{'training':str(out),'model':str(out/'candidate-head.local.npz'),
        'status':'experimental_candidate_head_not_deployed','development_candidate_gate_passed':success,
        'identity_verification_established':False,'approved_for_rule_engine':False})
    print('DOCUMENT_FILTER_READY:',out,flush=True);print(json.dumps(summary),flush=True)


if __name__=='__main__': main()
