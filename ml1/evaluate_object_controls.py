"""Summarize frozen local controls without treating missing tracks/masks as success."""
import argparse,datetime,hashlib,json
from pathlib import Path
from run_ollama_trial import ROOT,write_json

def summarize(result):
 timeline=result['timeline'];candidates=result.get('experimental_signals',[])
 away=[r for r in timeline if r['cashier_presence']=='away_observed' and r['departure_supported']]
 known=[r for r in away if r.get('experimental_object',{}).get('state')=='mask_observed']
 if candidates:status='candidate_requires_review'
 elif not away:status='inconclusive_no_observed_departure'
 elif not known:status='inconclusive_object_lost_during_departure'
 else:status='no_candidate_with_partial_observed_coverage'
 return {'status':status,'candidate_count':len(candidates),'candidate_intervals':[{'start_sec':c['start_sec'],'end_sec':c['end_sec']} for c in candidates],
         'total_frames':len(timeline),'observed_departure_frames':len(away),'mask_observed_during_departure_frames':len(known),
         'mask_unknown_during_departure_frames':len(away)-len(known),'cashier_unknown_frames':sum(r['cashier_presence']=='unknown' for r in timeline),
         'mask_identity_confirmed_on_this_clip':False,'approved_for_rule_engine':False,'accuracy_established':False}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',type=Path,required=True);p.add_argument('--reports',nargs='+',type=Path,required=True);args=p.parse_args()
 plan=json.loads(args.plan.read_text());expected={c['source_session']:c for c in plan['cases']};cases=[];seen=set()
 for folder in args.reports:
  folder=folder.resolve()
  if not folder.is_relative_to((ROOT/'local').resolve()):p.error('Local report required')
  if json.loads((folder/'status.json').read_text())['status']!='completed':p.error('Completed report required')
  profile=json.loads((folder/'calibration.local.json').read_text());runtime=json.loads((folder/'runtime.local.json').read_text());session=profile['source_session']
  if session not in expected or session in seen:p.error('Unexpected or duplicate control')
  seen.add(session);case=expected[session]
  if profile['source_video_sha256']!=case['source_video_sha256'] or profile['target_object_kind']!=case['target_kind']:p.error('Control binding mismatch')
  if runtime['weights_sha256']!=plan['model_weights_sha256'] or runtime['source_revision']!=plan['source_revision']:p.error('Model changed')
  result=json.loads((folder/'observations.local.json').read_text());cases.append(dict(summarize(result),source_session=session,source_name=case['source_name'],report_folder=folder.name,human_target_kind=case['target_kind']))
 if seen!=set(expected):p.error('All planned controls required')
 output={'schema_version':1,'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'plan_sha256':hashlib.sha256(args.plan.read_bytes()).hexdigest(),'cases':cases,'approved_for_rule_engine':False,'human_event_labels_used_in_inference':False,'general_accuracy_established':False}
 target=args.plan.parent/'control-results.local.json';write_json(target,output);print('CONTROL_RESULTS_READY:',target)
 for c in cases:print(json.dumps(c,ensure_ascii=False))

if __name__=='__main__':main()
