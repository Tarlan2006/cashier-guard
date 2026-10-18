"""Freeze the candidate head before checking a new source video locally."""
import argparse, base64, datetime, hashlib, json, time
from pathlib import Path
import cv2
import numpy as np
from run_ollama_trial import ROOT, write_json
from prepare_identity_review import source_session
from run_document_reference_search import validate_frames
from train_document_filter import patch_features
from scene_mvp.neural_features import FrozenDoorFeatures as FrozenPatchFeatures
from scene_mvp.document_search import SPEC as SEARCH_SPEC, crop_box, templates, search
from scene_mvp.document_filter import SPEC, scores


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def select_review(rows):
    """Include retained candidates and rejected controls, without showing decisions in UI."""
    chosen=[]
    for kind in ('retained_candidate','rejected_control'):
        for row in sorted(rows,key=lambda r:-max((p['reference_similarity'] for p in r['proposals'] if p['selection_state']==kind),default=-2)):
            if not any(p['selection_state']==kind for p in row['proposals']): continue
            if any(abs(row['timestamp_sec']-c['timestamp_sec'])<1. for c in chosen): continue
            chosen.append({**row,'selection_reason':kind})
            if sum(c['selection_reason']==kind for c in chosen)>=4: break
    return sorted(chosen,key=lambda r:r['timestamp_sec'])


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--reference-id',default='X-4');args=parser.parse_args()
    cv2.setNumThreads(2);started=time.monotonic()
    training=Path(json.loads((ROOT/'local/document-filter-current.local.json').read_text())['training'])
    metadata=json.loads((training/'model-metadata.local.json').read_text());training_protocol=json.loads((training/'protocol.local.json').read_text())
    model_path=training/'candidate-head.local.npz'
    if sha(model_path)!=metadata['model_sha256'] or metadata['spec']!=SPEC: raise ValueError('Frozen model or specification changed')
    for name,field in [('scene_mvp/document_filter.py','head_module_sha256'),('scene_mvp/neural_features.py','frozen_encoder_module_sha256')]:
        if sha(ROOT/name)!=training_protocol[field]: raise ValueError('Frozen feature/head code changed')
    if sha(ROOT/'train_document_filter.py')!=training_protocol['runner_sha256']: raise ValueError('Frozen crop preprocessing changed')
    catalog_path=ROOT/'outputs/forte_scenarios_from_pdf.json';catalog=json.loads(catalog_path.read_text())
    reference=next(r for r in catalog['records'] if r['video_id']==args.reference_id)
    if reference['video_sha256'] in metadata['training_video_sha256']: parser.error('Use a source video excluded from training')
    old_source=json.loads((ROOT/'local/scene-session-20261018-004941-345977/session.local.json').read_text())
    folder,session=source_session(reference,Path(old_source['source_video']).parent)
    if sha(Path(session['source_video']))!=reference['video_sha256']: raise ValueError('Original source video changed')
    dataset=Path(json.loads((ROOT/'local/identity-dataset-current.local.json').read_text())['dataset'])
    known=[json.loads(line) for line in (dataset/'video-observations.jsonl').read_text().splitlines()]
    positive=next(r for r in known if r['source_session']=='scene-session-20261018-014424-318521')
    ref_folder=ROOT/'local'/positive['source_session'];ref_session=json.loads((ref_folder/'session.local.json').read_text())
    validate_frames(positive,ref_folder,ref_session)
    seed=positive['document_seed'];anchor=min(ref_session['frames'],key=lambda f:abs(f['timestamp_sec']-seed['timestamp_sec']))
    ref_path=ref_folder/anchor['file'];patch,_=crop_box(cv2.imread(str(ref_path)),seed['bbox']);reference_templates=templates(patch)
    out=ROOT/'local'/('document-filter-check-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir()
    protocol={'schema_version':'document-filter-check/1','review_session':out.name,'reference_id':args.reference_id,
        'source_session':folder.name,'source_video_sha256':reference['video_sha256'],'model_sha256':sha(model_path),
        'training_protocol_sha256':sha(training/'protocol.local.json'),'training_video_sha256':metadata['training_video_sha256'],
        'source_excluded_from_training':True,'source_selected_with_known_pdf_summary':True,'catalog_sha256':sha(catalog_path),
        'reference_frame_sha256':sha(ref_path),'reference_seed':seed,'search_spec':SEARCH_SPEC,'candidate_head_spec':SPEC,
        'filter_policy':'reject_candidate_below_0.35_keep_all_unknown_for_human_review',
        'no_match_does_not_establish_absence':True,'decision_cutoff_changed_after_new_labels':False,
        'sampled_frames_not_all_native_frames':True,'model_frozen_before_this_candidate_review':True,
        'runner_sha256':sha(Path(__file__)),'approved_for_rule_engine':False,'bank_data_uploaded':False,'legal_violation_label':None}
    write_json(out/'protocol.local.json',protocol);print('DOCUMENT_FILTER_CHECK:',out,flush=True)
    archive=np.load(model_path,allow_pickle=False);model={k:archive[k] for k in ('mean','weight','bias')}
    extractor=FrozenPatchFeatures(ROOT/'models/rtdetr_r18vd',threads=2)
    if extractor.spec!=metadata['feature_spec']:raise ValueError('Feature extractor changed')
    images=[cv2.imread(str(folder/f['file'])) for f in session['frames']];rows=[]
    for index,frame in enumerate(session['frames']):
        neighbors=[images[n] for n in (index-1,index+1) if 0<=n<len(images)]
        proposals=search(images[index],reference_templates,neighbors=neighbors)
        for prop in proposals:
            value=float(scores(model,[patch_features(extractor,images[index],prop['bbox'])])[0])
            prop.update(candidate_head_score=value,selection_state='rejected_control' if value<=SPEC['rejected_cutoff'] else 'retained_candidate',
                        document_type_verified=False)
        rows.append({'timestamp_sec':frame['timestamp_sec'],'file':frame['file'],'frame_sha256':sha(folder/frame['file']),'proposals':proposals})
        if (index+1)%20==0:print('SEARCH_AND_FILTER:',index+1,'/',len(images),flush=True)
    write_json(out/'predictions.local.json',{'source_session':folder.name,'source_video_sha256':reference['video_sha256'],'timeline':rows})
    cards=[]
    for row in select_review(rows):
        frame_index=min(range(len(session['frames'])),key=lambda i:abs(session['frames'][i]['timestamp_sec']-row['timestamp_sec']))
        image=images[frame_index].copy();h,w=image.shape[:2]
        for i,prop in enumerate(row['proposals']):
            a,b,c,d=map(round,[prop['bbox'][0]*w,prop['bbox'][1]*h,prop['bbox'][2]*w,prop['bbox'][3]*h])
            color=[(50,190,50),(255,170,40),(180,60,220)][i]
            cv2.rectangle(image,(a,b),(c,d),color,1);cv2.putText(image,chr(65+i),(a,max(12,b-3)),cv2.FONT_HERSHEY_SIMPLEX,.45,color,1)
        preview,_=crop_box(image,[.10,.32,.72,.68]);ok,encoded=cv2.imencode('.jpg',preview,[cv2.IMWRITE_JPEG_QUALITY,95])
        if not ok:raise ValueError('Preview encode failed')
        cards.append({'key':str(len(cards)),'source_video_sha256':reference['video_sha256'],'source_session':folder.name,
                      'source_name':session['source_name'],'timestamp_sec':row['timestamp_sec'],'frame_sha256':row['frame_sha256'],
                      'selection_reason':row['selection_reason'],'proposals':row['proposals'],
                      'image':'data:image/jpeg;base64,'+base64.b64encode(encoded).decode()})
    write_json(out/'candidate-manifest.local.json',{'cards':[{k:v for k,v in c.items() if k!='image'} for c in cards]})
    payload={'schema_version':'document-search-review/1','review_session':out.name,'protocol_sha256':sha(out/'protocol.local.json'),
             'candidate_manifest_sha256':sha(out/'candidate-manifest.local.json'),'cards':cards,'approved_for_rule_engine':False}
    page=(ROOT/'scene_mvp/document_search_review.html').read_text()
    start=page.index('<aside>');end=page.index('</aside>',start)+len('</aside>')
    intro='<aside>Проверка фильтра на '+args.reference_id+'. Этот исходный ролик не входил в обучение фильтра. Показаны найденные участки и контрольные участки, которые фильтр хотел убрать. Его ответы скрыты, чтобы не влиять на твою проверку. Рамки A/B/C — только кандидаты. Предмет нужно назвать по изображению; отсутствие подходящей рамки не доказывает отсутствия документа в ролике.</aside>'
    page=page[:start]+intro+page[end:]
    page=page.replace('Поиск документа без рамки на каждом видео','Проверка фильтра на другом видео')
    (out/'review.html').write_text(page.replace('__PAYLOAD__',json.dumps(payload,ensure_ascii=False).replace('<','\\u003c')),encoding='utf-8')
    proposed=sum(len(r['proposals']) for r in rows);rejected=sum(p['selection_state']=='rejected_control' for r in rows for p in r['proposals'])
    summary={'source_name':session['source_name'],'sampled_frames':len(rows),'raw_candidate_boxes':proposed,'rejected_candidate_boxes':rejected,
             'retained_for_human_review':proposed-rejected,'human_review_frames':len(cards),'new_source_accuracy_not_established':True,
             'document_absence_established':False,'elapsed_sec':round(time.monotonic()-started,2),'approved_for_rule_engine':False}
    write_json(out/'summary.local.json',summary)
    write_json(ROOT/'local/document-search-current.local.json',{'trial':str(out),'report':str(out/'review.html'),'status':'needs_candidate_review','source_excluded_from_filter_training':True})
    write_json(ROOT/'local/document-filter-check-current.local.json',{'trial':str(out),'report':str(out/'review.html'),'status':'needs_candidate_review'})
    print('DOCUMENT_FILTER_CHECK_READY:',out/'review.html',flush=True);print(json.dumps(summary),flush=True)


if __name__=='__main__':main()
