"""Train the first banknotes/card/other crop head on existing human labels."""
import collections,datetime,hashlib,json,time
from pathlib import Path
import cv2,numpy as np
from run_ollama_trial import ROOT,write_json
from scene_mvp.neural_features import FrozenDoorFeatures as FrozenPatchFeatures
from scene_mvp.crop_object_classifier import SPEC,fit,predict


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    started=time.monotonic();cv2.setNumThreads(2)
    dataset=ROOT/'local/merged-objects-20261017-205427-607791';data_path=dataset/'dataset.local.json';data=json.loads(data_path.read_text())
    rows=[r for r in data['examples'] if r['object_kind'] in SPEC['classes']]
    train=[i for i,r in enumerate(rows) if r['split']=='development'];test=[i for i,r in enumerate(rows) if r['split']=='heldout']
    train_groups={rows[i]['video_sha256'] for i in train};test_groups={rows[i]['video_sha256'] for i in test}
    if not train or not test or train_groups&test_groups or len(train)+len(test)!=len(rows):raise ValueError('Predefined nonoverlapping video groups required')
    out=ROOT/'local'/('object-crop-training-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir()
    protocol={'spec':SPEC,'dataset_sha256':sha(data_path),'training_examples':len(train),'heldout_examples':len(test),
       'train_video_sha256':sorted(train_groups),'heldout_video_sha256':sorted(test_groups),
       'split_predefined_in_original_human_label_set':True,'hyperparameter_search':False,'thresholds_frozen_before_heldout_evaluation':True,
       'labels_source':'human_bounding_box_exports','ambiguous_human_labels_excluded':len(data['examples'])-len(rows),
       'frame_groups_are_not_independent_examples':True,'evaluation_scope':'small_predefined_local_video_group_holdout_not_external_generalization',
       'heldout_labels_used_in_fit':False,'runner_sha256':sha(Path(__file__)),'head_module_sha256':sha(ROOT/'scene_mvp/crop_object_classifier.py'),
       'backbone_module_sha256':sha(ROOT/'scene_mvp/neural_features.py'),'bank_data_uploaded':False,'approved_for_rule_engine':False}
    write_json(out/'protocol.local.json',protocol);print('OBJECT_CROP_TRAINING:',out,flush=True)
    extractor=FrozenPatchFeatures(ROOT/'models/rtdetr_r18vd',threads=2);features=[]
    for i,row in enumerate(rows):
        path=(dataset/row['crop_file']).resolve()
        if not path.is_relative_to(dataset.resolve()) or sha(path)!=row['crop_sha256']:raise ValueError('Human crop changed')
        vector=extractor.feature(cv2.imread(str(path)));features.append(vector/max(float(np.linalg.norm(vector)),1e-12))
        if (i+1)%10==0:print('OBJECT_CROP_FEATURES:',i+1,'/',len(rows),flush=True)
    x=np.asarray(features,float);np.savez_compressed(out/'features.local.npz',features=x)
    model=fit(x[train],[rows[i] for i in train]);np.savez_compressed(out/'object-crop-head.local.npz',**model)
    answers=predict(model,x[test]);expected=[rows[i]['object_kind'] for i in test]
    predictions=[{'example_id':rows[i]['id'],'source_video_sha256':rows[i]['video_sha256'],'expected_human_class':label,**answer}
                 for i,label,answer in zip(test,expected,answers)]
    correct=sum(p['decision']==p['expected_human_class'] for p in predictions);answered=sum(p['decision']!='unclear' for p in predictions)
    confusion={c:{p:sum(r['expected_human_class']==c and r['decision']==p for r in predictions) for p in [*SPEC['classes'],'unclear']} for c in SPEC['classes']}
    majority=collections.Counter(rows[i]['object_kind'] for i in train).most_common(1)[0][0]
    summary={'model_trained_here':True,'backbone_finetuned':False,'training_examples':len(train),'training_video_groups':len(train_groups),
       'heldout_examples':len(test),'heldout_video_groups':len(test_groups),'heldout_top1_correct':sum(r['top_class']==r['expected_human_class'] for r in predictions),
       'heldout_correct_with_unclear_as_unmatched':correct,'heldout_unclear':len(test)-answered,'heldout_answered':answered,
       'heldout_wrong_answered':answered-correct,'majority_baseline_class':majority,'majority_baseline_correct':sum(e==majority for e in expected),
       'confusion':confusion,'elapsed_sec':round(time.monotonic()-started,2),'input_requires_localized_object_crop':True,
       'identity_document_type_not_trained':True,'automatic_violation_detection_established':False,'approved_for_rule_engine':False}
    write_json(out/'heldout-results.local.json',{'predictions':predictions,'summary':summary})
    write_json(out/'model-metadata.local.json',{'spec':SPEC,'feature_spec':extractor.spec,'normalization':'global_L2_frozen_features',
        'model_sha256':sha(out/'object-crop-head.local.npz'),'training_video_sha256':sorted(train_groups),'heldout_not_used_for_refit':True,'approved_for_rule_engine':False})
    write_json(ROOT/'local/object-crop-training-current.local.json',{'training':str(out),'model':str(out/'object-crop-head.local.npz'),
        'status':'experimental_trained_crop_classifier','summary':summary,'approved_for_rule_engine':False})
    print('OBJECT_CROP_TRAINED:',out,flush=True);print(json.dumps(summary),flush=True)


if __name__=='__main__':main()
