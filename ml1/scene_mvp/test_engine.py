import copy,unittest
from scene_mvp.engine import analyze,validate_profile
SHA='a'*64
PROFILE={'schema_version':1,'source_video_sha256':SHA,'confirmed':True,'zones':{'cashier_zone':[.5,.5,1,1],'service_zone':[0,0,.49,.49]},'roles':{'cashier_ids':[1],'client_ids':[2,3]},'stability_sec':1,'max_gap_sec':1}
def person(i,box,**kwargs):return dict(id=i,bbox=box,track_confirmed=True,counted=True,confidence=.9,**kwargs)
def row(t,*people):return {'timestamp_sec':t,'persons':list(people)}
INSIDE=person(1,[.6,.6,.8,.8]);OUTSIDE=person(1,[.6,.2,.8,.4]);CLIENT=person(2,[.05,.05,.15,.15]);CLIENT2=person(3,[.3,.1,.4,.2])
class EngineTests(unittest.TestCase):
 def test_lost_track_unknown_not_departure(self):
  r=analyze([row(0,INSIDE),row(.5),row(1),row(1.5)],PROFILE,SHA)
  self.assertEqual(r['signals'],[]);self.assertEqual(r['timeline'][-1]['cashier_presence'],'unknown')
 def test_observed_departure(self):
  r=analyze([row(0,INSIDE),row(.5,OUTSIDE),row(1,OUTSIDE),row(1.5,OUTSIDE)],PROFILE,SHA)
  self.assertEqual([s['type'] for s in r['signals']],['workplace_departure']);self.assertFalse(r['signals'][0]['legal_violation_established'])
 def test_starting_outside_not_departure(self):
  self.assertEqual(analyze([row(0,OUTSIDE),row(.5,OUTSIDE),row(1,OUTSIDE)],PROFILE,SHA)['signals'],[])
 def test_long_track_gap_breaks_departure(self):
  self.assertEqual(analyze([row(0,INSIDE),row(3,OUTSIDE),row(3.5,OUTSIDE),row(4,OUTSIDE)],PROFILE,SHA)['signals'],[])
 def test_short_gap_no_event(self):
  self.assertEqual(analyze([row(0,INSIDE),row(.5,OUTSIDE),row(1,INSIDE)],PROFILE,SHA)['signals'],[])
 def test_two_visible_clients(self):
  r=analyze([row(t,INSIDE,CLIENT,CLIENT2) for t in [0,.5,1]],PROFILE,SHA)
  self.assertEqual([s['type'] for s in r['signals']],['multiple_visitors_in_service_zone'])
 def test_reflection_excluded(self):
  ref=dict(CLIENT2,is_reflection=True)
  self.assertEqual(analyze([row(t,INSIDE,CLIENT,ref) for t in [0,.5,1]],PROFILE,SHA)['signals'],[])
 def test_duplicate_box_not_second_visitor(self):
  dup=dict(CLIENT,id=3)
  self.assertEqual(analyze([row(t,INSIDE,CLIENT,dup) for t in [0,.5,1]],PROFILE,SHA)['signals'],[])
 def test_ignore_mask(self):
  p=copy.deepcopy(PROFILE);p['zones']['ignore_zone']=[[.25,0,.49,.3]]
  self.assertEqual(analyze([row(t,INSIDE,CLIENT,CLIENT2) for t in [0,.5,1]],p,SHA)['signals'],[])
 def test_unconfirmed_calibration_no_signals(self):
  p=copy.deepcopy(PROFILE);p['confirmed']=False
  self.assertEqual(analyze([],p,SHA)['status'],'needs_calibration')
 def test_wrong_video_rejected(self):
  with self.assertRaises(ValueError):analyze([],PROFILE,'b'*64)
 def test_unknown_door_not_open(self):
  r=analyze([row(0,INSIDE),row(.5,OUTSIDE),row(1,OUTSIDE),row(1.5,OUTSIDE)],PROFILE,SHA)
  self.assertNotIn('door_open_while_cashier_away',[s['type'] for s in r['signals']])
 def test_human_door_state(self):
  frames=[row(0,INSIDE),row(.5,OUTSIDE),row(1,OUTSIDE),row(1.5,OUTSIDE)];states={t:{'state':'open','source':'human_frame_label'} for t in [.5,1,1.5]}
  r=analyze(frames,PROFILE,SHA,states)
  self.assertIn('door_open_while_cashier_away',[s['type'] for s in r['signals']])
 def test_door_inference_cannot_masquerade_as_label(self):
  with self.assertRaises(ValueError):analyze([row(0,INSIDE)],PROFILE,SHA,{0:{'state':'open','source':'unvalidated_model'}})
 def test_empty_draft_does_not_enable_events(self):
  p=copy.deepcopy(PROFILE);p['confirmed']=False;p['zones']={}
  self.assertEqual(analyze([],p,SHA)['status'],'needs_calibration')
 def test_established_candidate_role_does_not_flip_on_movement(self):
  p=copy.deepcopy(PROFILE);p['roles']={}
  move=person(1,[.1,.1,.2,.2])
  frames=[row(0,INSIDE),row(.5,INSIDE),row(1,INSIDE),row(1.5,move),row(2,move),row(2.5,move)]
  r=analyze(frames,p,SHA)
  self.assertEqual(r['timeline'][-1]['persons'][0]['role'],'cashier_candidate')
  self.assertIn('workplace_departure',[s['type'] for s in r['signals']])
 def test_unconfirmed_person_not_a_second_visitor(self):
  tentative=dict(CLIENT2,id=8,track_confirmed=False)
  self.assertEqual(analyze([row(t,INSIDE,CLIENT,tentative) for t in [0,.5,1]],PROFILE,SHA)['signals'],[])
 def test_unknown_interval_breaks_sustained_departure(self):
  frames=[row(0,INSIDE),row(.5,OUTSIDE),row(1),row(1.5,OUTSIDE)]
  self.assertEqual(analyze(frames,PROFILE,SHA)['signals'],[])
 def test_boundary_jitter_not_departure(self):
  near=person(1,[.6,.395,.8,.595])
  r=analyze([row(0,INSIDE),row(.5,near),row(1,near),row(1.5,near)],PROFILE,SHA)
  self.assertEqual(r['signals'],[])
  self.assertEqual(r['timeline'][-1]['cashier_presence'],'present')
 def test_reentry_at_zone_edge_ends_departure(self):
  edge=person(1,[.6,.401,.8,.601])
  frames=[row(0,INSIDE),row(.5,OUTSIDE),row(1,OUTSIDE),row(1.5,OUTSIDE),row(2,edge)]
  r=analyze(frames,PROFILE,SHA)
  self.assertEqual(r['signals'][0]['end_sec'],1.5)
  self.assertEqual(r['timeline'][-1]['cashier_presence'],'present')
 def test_human_review_can_confirm_initial_tentative_track(self):
  reviewed=dict(INSIDE,track_confirmed=False,counted=False)
  r=analyze([row(0,reviewed),row(.5,OUTSIDE),row(1,OUTSIDE),row(1.5,OUTSIDE)],PROFILE,SHA)
  self.assertIn('workplace_departure',[s['type'] for s in r['signals']])
  self.assertEqual(r['timeline'][0]['persons'][0]['track_confirmation_source'],'human_reviewed_video_track')
 def test_manual_role_does_not_override_reflection(self):
  reviewed=dict(INSIDE,track_confirmed=False,counted=False,is_reflection=True)
  self.assertEqual(analyze([row(0,reviewed)],PROFILE,SHA)['timeline'][0]['cashier_presence'],'unknown')
 def test_manual_role_does_not_override_weak_detection(self):
  reviewed=dict(INSIDE,track_confirmed=False,counted=False,confidence=.1)
  self.assertEqual(analyze([row(0,reviewed)],PROFILE,SHA)['timeline'][0]['cashier_presence'],'unknown')
 def test_predicted_only_box_is_not_observed_even_for_reviewed_track(self):
  predicted=dict(INSIDE,observed=False)
  self.assertEqual(analyze([row(0,predicted)],PROFILE,SHA)['timeline'][0]['cashier_presence'],'unknown')
 def test_door_only_profile_valid_without_workplace_zones(self):
  p=copy.deepcopy(PROFILE);p['profile_kind']='door_only';p['zones']={'door_zone':[0,0,.2,.4]};validate_profile(p)
 def test_door_only_cannot_run_workplace_rules(self):
  p=copy.deepcopy(PROFILE);p['profile_kind']='door_only';p['zones']={'door_zone':[0,0,.2,.4]}
  with self.assertRaises(ValueError):analyze([],p,SHA)
 def test_threshold_is_positive(self):
  p=copy.deepcopy(PROFILE);p['stability_sec']=0
  with self.assertRaises(ValueError):validate_profile(p)
if __name__=='__main__':unittest.main()
