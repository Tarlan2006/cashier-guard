"""Record mask feedback without promoting geometry to confirmed cash actions."""
import argparse,datetime,hashlib,json
from pathlib import Path
from run_ollama_trial import ROOT,write_json
from scene_mvp.cash_tracking_review import validate


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--tracking',type=Path,required=True);parser.add_argument('--review',type=Path,required=True);args=parser.parse_args();out=args.tracking.resolve()
    if not out.is_relative_to((ROOT/'local').resolve()):parser.error('Local tracking run required')
    pp=out/'mask-review-protocol.local.json';protocol=json.loads(pp.read_text());protocol['review_protocol_sha256']=sha(pp);raw=args.review.read_bytes();review=json.loads(raw)
    try:validate(review,protocol)
    except ValueError as error:parser.error(str(error))
    if json.loads((out/'status.json').read_text()).get('status')!='completed':parser.error('Completed tracking required')
    if sha(out/'protocol.local.json')!=protocol['tracking_protocol_sha256']:parser.error('Tracking protocol changed')
    for source in protocol['cases']:
        path=Path(source['result_file']).resolve()
        if not path.is_relative_to(out) or sha(path)!=source['result_sha256']:parser.error('Reviewed result changed')
    (out/'human-mask-review.original.local.json').write_bytes(raw)
    accepted={**review,'accepted_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'review_sha256':hashlib.sha256(raw).hexdigest(),'all_native_frames_verified':False,
        'automatic_machine_use_established':False,'automatic_storage_established':False,'approved_for_rule_engine':False}
    write_json(out/'human-mask-review.accepted.local.json',accepted)
    pointer=ROOT/'local/cash-process-tracking-current.local.json';current=json.loads(pointer.read_text())
    if Path(current['trial']).resolve()==out:write_json(pointer,{**current,'status':'human_cash_mask_review_recorded',
        'human_masks':{c['case_id']:c['human_mask_review'] for c in review['cases']}})
    print('CASH_TRACKING_MASK_REVIEW_IMPORTED:',out,flush=True)


if __name__=='__main__':main()
