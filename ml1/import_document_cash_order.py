"""Accept native-video cash/counter time labels without reading personal document data."""
import argparse,datetime,hashlib,json
from pathlib import Path
from run_ollama_trial import ROOT,write_json
from scene_mvp.document_procedure import window


def apply_timing_clarification(accepted,clarification,original_sha):
    if clarification.get('original_review_sha256')!=original_sha or clarification.get('source_video_sha256')!=accepted['source_video_sha256']:
        raise ValueError('Clarification must bind to the original review and video')
    evidence=clarification.get('evidence',{})
    if evidence.get('kind')!='explicit_user_chat_reply' or not isinstance(evidence.get('answer'),str) or not evidence['answer'].strip() or clarification.get('human_relative_order')!='document_then_banknotes':
        raise ValueError('Explicit human relative-order clarification required')
    if clarification.get('document_transfer_at_marked_start_sec')!=accepted['cash_handover_window_sec'][0]:
        raise ValueError('Wrong marked interval start')
    return {**accepted,'cash_window_scope':'combined_document_and_cash','human_relative_order':'document_then_banknotes',
        'precise_cash_handover_start_sec':None,'human_timing_clarification':clarification,
        'original_marked_window_preserved':True,'relative_order_source':'explicit_user_chat_reply'}


def validate(review,protocol,protocol_sha):
    if review.get('schema_version') not in {'document-cash-order-review/1','document-cash-order-review/2'} or review.get('review_session')!=protocol['review_session']:
        raise ValueError('Wrong order review/session')
    if review.get('protocol_sha256')!=protocol_sha or any(review.get(k)!=protocol[k] for k in ['source_session','source_video_sha256']):raise ValueError('Wrong source/protocol')
    if review.get('confirmed') is not True or review.get('review_scope')!='human_native_video_event_windows' or review.get('frame_accurate_boundaries') is not False:
        raise ValueError('Confirmed human approximate windows required')
    if review.get('automatic_legal_verdict') is not False or review.get('identity_verification_established') is not False:raise ValueError('No legal or identity verdict')
    spans=[window(review.get('cash_handover_window_sec'))]
    if review.get('human_direction') not in ['client_to_cashier','cashier_to_client','unclear']:raise ValueError('Unknown handover direction')
    if review.get('same_operation') not in ['yes','no','unclear']:raise ValueError('Operation binding required')
    counter=review.get('counter_use_observation')
    if counter not in ['observed','not_observed','unclear']:raise ValueError('Counter observation required')
    if counter=='observed':spans.append(window(review.get('counter_use_window_sec')))
    elif review.get('counter_use_window_sec') is not None:raise ValueError('Counter interval without observed use')
    if review.get('manual_count_observation') not in ['observed','not_observed','unknown']:raise ValueError('Unknown manual-count observation')
    if any(a>=b or b>protocol['duration_sec'] for a,b in spans):raise ValueError('Window outside source video')
    for field in ['cash_storage_after_count_observation','cash_storage_closed_after_placement_observation']:
        if review.get(field,'unknown') not in {'observed','not_observed','unclear','unknown'}:raise ValueError('Unknown storage observation')
    if review.get('storage_stage_coverage','unknown') not in {'complete','incomplete','unclear','unknown'}:raise ValueError('Unknown storage scope')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--trial',type=Path,required=True);parser.add_argument('--review',type=Path,required=True)
    parser.add_argument('--clarification',type=Path);args=parser.parse_args()
    trial=args.trial.resolve()
    if not trial.is_relative_to((ROOT/'local').resolve()):parser.error('Local order review required')
    raw=args.review.read_bytes();review=json.loads(raw);pp=trial/'protocol.local.json';protocol=json.loads(pp.read_text())
    try:validate(review,protocol,hashlib.sha256(pp.read_bytes()).hexdigest())
    except ValueError as error:parser.error(str(error))
    if hashlib.sha256(Path(protocol['source_video']).read_bytes()).hexdigest()!=protocol['source_video_sha256']:parser.error('Original video changed')
    accepted={**review,'review_sha256':hashlib.sha256(raw).hexdigest(),'accepted_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'approved_for_rule_engine':False,'legal_violation_label':None,'cash_count_accuracy_established':False}
    if args.clarification:
        clarification_raw=args.clarification.read_bytes()
        try:accepted=apply_timing_clarification(accepted,json.loads(clarification_raw),accepted['review_sha256'])
        except ValueError as error:parser.error(str(error))
        (trial/'human-timing-clarification.original.local.json').write_bytes(clarification_raw)
    (trial/'human-order-review.original.local.json').write_bytes(raw)
    write_json(trial/'human-order-review.accepted.local.json',accepted)
    pointer=ROOT/'local/document-cash-order-current.local.json';current=json.loads(pointer.read_text())
    if Path(current['trial']).resolve()==trial:write_json(pointer,{**current,'status':'human_order_review_recorded'})
    print('DOCUMENT_CASH_COUNTER_ORDER_IMPORTED:',trial)
    from build_document_procedure import build_and_save
    build_and_save()


if __name__=='__main__':main()
