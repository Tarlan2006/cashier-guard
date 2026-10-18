"""Apply fixed causal confirmation to an existing development result, no inference."""
import argparse,datetime,json
from pathlib import Path
from run_ollama_trial import ROOT
from scene_mvp.door_sequence_report import write_report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--result',type=Path,required=True)
    args=p.parse_args()
    source=args.result.resolve()
    if not source.is_relative_to((ROOT/'local').resolve()):p.error('Local result required')
    rows=json.loads((source/'predictions.local.json').read_text())['predictions']
    # Legacy evaluator omitted human-unknown timestamps; never bridge those gaps.
    profile=json.loads((source/'calibration.local.json').read_text())
    if any(r['state']=='unknown' for r in profile['door_frame_labels']):
        p.error('Legacy result omits unclear frames; regenerate full inference before temporal evaluation')
    out=ROOT/'local'/('door-temporal-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'))
    out.mkdir()
    summary=write_report(rows,out,independent=False,source=str(source))
    print('DOOR_TEMPORAL_REPORT_READY:',out/'temporal-report.html')
    print(json.dumps(summary,ensure_ascii=False))

if __name__=='__main__':main()
