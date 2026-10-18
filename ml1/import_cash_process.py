"""Accept human cash/machine/safe regions with exact source binding."""
import argparse,datetime,hashlib,json
from pathlib import Path
from run_ollama_trial import ROOT,write_json
from scene_mvp.cash_process import validate_case,human_sequence


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--trial',type=Path,required=True);parser.add_argument('--review',type=Path,required=True);args=parser.parse_args()
    trial=args.trial.resolve()
    if not trial.is_relative_to((ROOT/'local').resolve()):parser.error('Local review required')
    pp=trial/'protocol.local.json';protocol=json.loads(pp.read_text());raw=args.review.read_bytes();review=json.loads(raw)
    if review.get('schema_version')!='cash-process-review/1' or review.get('review_session')!=protocol['review_session'] or review.get('protocol_sha256')!=sha(pp):parser.error('Wrong review/protocol')
    if review.get('confirmed') is not True or review.get('automatic_legal_verdict') is not False:parser.error('Confirmed visual review without legal verdict required')
    expected={c['case_id']:c for c in protocol['cases']};cases=review.get('cases',[])
    if len(cases)!=len(expected) or {c['case_id'] for c in cases}!=set(expected):parser.error('Exactly one review per source case required')
    for case in cases:
        bound=expected[case['case_id']]
        try:validate_case(case,bound)
        except ValueError as error:parser.error(str(error))
        source=Path(bound['source_session']).resolve()
        if not source.is_relative_to(trial):parser.error('Source outside bound review')
        session=json.loads((source/'session.local.json').read_text())
        if session['source_video_sha256']!=bound['source_video_sha256'] or sha(Path(session['source_video']))!=bound['source_video_sha256']:parser.error('Original video changed')
        for name,digest in bound['frame_sha256'].items():
            path=(source/name).resolve()
            if not path.is_relative_to(source) or sha(path)!=digest:parser.error('Source frame changed')
    accepted={**review,'accepted_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'review_sha256':hashlib.sha256(raw).hexdigest(),
        'cash_type_source':'human_seed_not_automatic_recognition','object_mask_reviewed':False,'approved_for_rule_engine':False}
    (trial/'human-review.original.local.json').write_bytes(raw);write_json(trial/'human-review.accepted.local.json',accepted)
    write_json(ROOT/'local/cash-process-current.local.json',{'trial':str(trial),'report':str(trial/'review.html'),'status':'human_regions_ready_for_tracking','accepted_review':str(trial/'human-review.accepted.local.json')})
    sequences={}
    for file in sorted((ROOT/'local').glob('cash-process-*/human-review.accepted.local.json')):
        source=json.loads(file.read_text())
        if source.get('confirmed') is not True:continue
        for case in source['cases']:
            key=(case['source_video_sha256'],case['cash_anchor_sec'])
            sequences[key]={'source_video_sha256':case['source_video_sha256'],'case_id':case['case_id'],
                'cash_seed_time_sec':case['cash_anchor_sec'],'human_review_sha256':source['review_sha256'],
                'result':human_sequence(case),'automatic_action_recognition_established':False}
    write_json(ROOT/'outputs/forte_cash_process_sequences.json',{'schema_version':'cash-process-human-sequences/1',
        'policy_source':'explicit_user_count_and_storage_workflow_request','cases':list(sequences.values()),'legal_verdicts':0})
    print('CASH_PROCESS_IMPORTED:',trial,flush=True)
    from build_unified_review import main as build_unified
    build_unified()


if __name__=='__main__':main()
