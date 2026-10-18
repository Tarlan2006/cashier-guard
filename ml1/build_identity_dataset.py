"""Consolidate human document-presentation labels by whole-video SHA, not by frames."""
import datetime,hashlib,json
from pathlib import Path
from run_ollama_trial import ROOT,write_json

def main():
    groups={}
    paths=sorted((ROOT/'local').glob('identity-review-*/human-review.accepted.local.json'),key=lambda p:json.loads(p.read_text())['accepted_at_utc'])
    for path in paths:
        review=json.loads(path.read_text())
        if review.get('confirmed') is not True:continue
        for c in review['accepted_observations']:
            if c.get('legal_violation_label') is not None or c.get('identity_verification_status')!='unknown_no_bank_record':raise ValueError('Visual observations only')
            key=c['source_video_sha256'];item=groups.setdefault(key,{'current':None,'review_history':[]})
            item['current']=c;item['review_history'].append({'path':str(path),'accepted_file_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                'source_export_sha256':review['review_sha256'],'accepted_at_utc':review['accepted_at_utc'],'observation':c['physical_document_observation']})
    labels=[];seeds=[]
    for key,item in groups.items():
        row={**item['current'],'review_history':item['review_history'],'label_unit':'whole_video_visual_observation','split_group':key,
             'frame_labels_outside_presentation_window':None,'identity_failure_label':None,'legal_violation_label':None}
        labels.append(row)
        if row['document_seed']:seeds.append({'source_session':row['source_session'],'source_video_sha256':key,'split_group':key,
            'seed':row['document_seed'],'presentation_window_human_sec':row['presentation_window_sec'],'label_source':'human_video_review_and_box',
            'automatic_object_classification':False})
    out=ROOT/'local'/('identity-dataset-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'));out.mkdir()
    for name,rows in [('video-observations.jsonl',labels),('document-seeds.jsonl',seeds)]:
        (out/name).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
    counts={kind:sum(r['physical_document_observation']==kind for r in labels) for kind in ('presentation_seen','already_present','not_observed','unclear')}
    manifest={'schema_version':'identity-observation-dataset/1','unique_video_groups':len(groups),'counts':counts,'human_object_seeds':len(seeds),
              'review_entries':sum(len(x['review_history']) for x in groups.values()),'duplicates_not_separate_training_examples':True,
              'bank_identity_verification_labels_available':False,'identity_failure_labels_created':False,'model_trained':False,'training_dataset_sufficient':False}
    write_json(out/'manifest.local.json',manifest);write_json(ROOT/'local/identity-dataset-current.local.json',{'dataset':str(out),**manifest})
    print('IDENTITY_DATASET_READY:',out);print(json.dumps(manifest))

if __name__=='__main__':main()
