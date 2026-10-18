"""Import only source-bound human document observations, never automatic ID failures."""
import argparse,copy,datetime,hashlib,json
from pathlib import Path
from run_ollama_trial import ROOT,write_json
from scene_mvp.identity_observations import validate_identity_review

def main():
    p=argparse.ArgumentParser();p.add_argument('--review',type=Path,required=True);p.add_argument('--session',type=Path,required=True);p.add_argument('--clarifications',type=Path);args=p.parse_args()
    folder=args.session.resolve()
    if not folder.is_relative_to((ROOT/'local').resolve()):p.error('Local review folder required')
    protocol_path=folder/'protocol.local.json';protocol=json.loads(protocol_path.read_text());protocol_sha=hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    frames={}
    for c in protocol['cases']:
        source=(ROOT/'local'/c['session_id']).resolve()
        if not source.is_relative_to((ROOT/'local').resolve()):p.error('Local source required')
        session=json.loads((source/'session.local.json').read_text())
        if session['source_video_sha256']!=c['sha256'] or hashlib.sha256(Path(session['source_video']).read_bytes()).hexdigest()!=c['sha256']:p.error('Source video changed')
        frames[c['session_id']]=session['frames']
    raw=args.review.read_bytes();original=json.loads(raw);review=copy.deepcopy(original);review_sha=hashlib.sha256(raw).hexdigest();clarifications=[]
    if args.clarifications:
        clarification=json.loads(args.clarifications.read_text())
        if clarification.get('original_review_sha256')!=review_sha:p.error('Clarification review binding mismatch')
        for change in clarification.get('changes',[]):
            matches=[c for c in review['cases'] if c['source_session']==change['source_session'] and c['source_video_sha256']==change['source_video_sha256']]
            if len(matches)!=1 or change.get('source')!='direct_user_reply_in_chat' or change.get('field')!='physical_document_observation':p.error('Invalid human clarification')
            case=matches[0]
            if case[change['field']]!=change['from']:p.error('Clarification old value mismatch')
            case[change['field']]=change['to'];clarifications.append(change)
    labels=validate_identity_review(review,protocol,protocol_sha,frames)
    catalog_path=ROOT/'outputs/forte_scenarios_from_pdf.json'
    if catalog_path.exists():
        catalog=json.loads(catalog_path.read_text())
        for label in labels:
            refs=[r for r in catalog['records'] if r['video_sha256']==label['source_video_sha256']]
            label.update(scenario_reference_ids=[r['video_id'] for r in refs],scenario_source_pdf_sha256=catalog['source_pdf_sha256'])
            if any(r['video_id']=='X-1' for r in refs):
                label['original_protocol_operation_context']=label['operation_context']
                label['operation_context']='cash_handling_with_partial_return_operation_type_not_established'
                label['operation_context_source']='user_designated_pdf_annotation'
    (folder/'human-review.original.local.json').write_bytes(raw)
    write_json(folder/'human-review.accepted.local.json',{**review,'accepted_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'review_sha256':review_sha,'human_clarifications':clarifications,'original_export_preserved':True,'accepted_observations':labels})
    (folder/'identity-observations.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in labels),encoding='utf-8')
    summary={'videos':len(labels),'human_presentation_seen':sum(x['physical_document_observation']=='presentation_seen' for x in labels),
             'document_already_present_only':sum(x['physical_document_observation']=='already_present' for x in labels),
             'presentation_not_observed_in_clip':sum(x['physical_document_observation']=='not_observed' for x in labels),
             'identity_failures_automatically_established':0,'legal_violation_labels_created':0,'training_dataset_sufficient':False}
    write_json(folder/'summary.local.json',summary);print('IDENTITY_REVIEW_IMPORTED:',folder);print(json.dumps(summary))

if __name__=='__main__':main()
