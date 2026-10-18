"""Create one local replay page for checking both cash masks after tracking finishes."""
import argparse,base64,hashlib,json
from pathlib import Path
from run_ollama_trial import ROOT,write_json


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--tracking',type=Path,required=True);args=parser.parse_args();out=args.tracking.resolve()
    if not out.is_relative_to((ROOT/'local').resolve()):parser.error('Local tracking result required')
    if json.loads((out/'status.json').read_text()).get('status')!='completed':parser.error('Tracking is not completed')
    tracking=json.loads((out/'protocol.local.json').read_text());source=Path(tracking['source_trial']).resolve()
    if not source.is_relative_to((ROOT/'local').resolve()) or sha(source/'human-review.accepted.local.json')!=tracking['source_review_sha256']:parser.error('Source review changed')
    human=json.loads((source/'human-review.accepted.local.json').read_text());source_by_id={r['case_id']:r for r in human['cases']}
    summary=json.loads((out/'summary.local.json').read_text());cases=[];protocol_cases=[]
    for definition in summary['cases']:
        result_path=Path(definition['result_file']).resolve()
        if not result_path.is_relative_to(out):parser.error('Result outside run')
        result=json.loads(result_path.read_text());name=definition['case_id'];human_case=source_by_id[name]
        if result['source_video_sha256']!=human_case['source_video_sha256']:parser.error('Case source mismatch')
        frames=[]
        for row in result['timeline']:
            overlay=Path(row['overlay_file']).resolve()
            if not overlay.is_relative_to(out):parser.error('Overlay outside run')
            frames.append({'time':row['timestamp_sec'],'state':row['state'],'image':'data:image/jpeg;base64,'+base64.b64encode(overlay.read_bytes()).decode(),
                'machine_overlap':row['machine_overlap_fraction'],'safe_overlap':row['safe_overlap_fraction']})
        statement_path=out/(name+'-human-mask-statement.accepted.local.json');statement=None
        if statement_path.exists():
            statement=json.loads(statement_path.read_text())
            if statement['source_video_sha256']!=result['source_video_sha256'] or statement['result_sha256']!=sha(result_path):parser.error('Human mask statement source mismatch')
        cases.append({'case_id':name,'source_video_sha256':result['source_video_sha256'],'result_sha256':sha(result_path),
            'known_human_mask_statement':statement,
            'frames':frames,'anchor_sec':human_case['cash_anchor_sec'],'candidates':result['candidates'],
            'human_action_times':{k:human_case.get(k) for k in ['counter_use_observation','counter_use_window_sec','cash_storage_observation','cash_storage_time_sec','storage_closure_time_sec']}})
        protocol_cases.append({'case_id':name,'source_video_sha256':result['source_video_sha256'],'result_sha256':sha(result_path),
            'result_file':str(result_path),'sample_times_sec':[r['timestamp_sec'] for r in result['timeline']]})
    protocol={'schema_version':'cash-tracking-mask-review-plan/1','tracking_session':out.name,'tracking_protocol_sha256':sha(out/'protocol.local.json'),
        'cases':protocol_cases,'mask_review_scope':'selected_samples_not_all_native_frames','geometry_is_not_action_confirmation':True}
    write_json(out/'mask-review-protocol.local.json',protocol)
    payload={'tracking_session':out.name,'review_protocol_sha256':sha(out/'mask-review-protocol.local.json'),'cases':cases}
    template=(ROOT/'scene_mvp/cash_tracking_review.html').read_text()
    (out/'mask-review.html').write_text(template.replace('__PAYLOAD__',json.dumps(payload,ensure_ascii=False).replace('<','\\u003c')),encoding='utf-8')
    write_json(ROOT/'local/cash-process-tracking-current.local.json',{'trial':str(out),'report':str(out/'mask-review.html'),'status':'needs_cash_mask_review',
        'summary':summary,'automatic_machine_or_storage_detection_established':False})
    print('CASH_TRACKING_MASK_REVIEW_READY:',out/'mask-review.html',flush=True)


if __name__=='__main__':main()
