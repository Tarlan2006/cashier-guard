import unittest
from scene_mvp.engine import validate_profile,analyze
from scene_mvp.bag_events import attach_review

def profile(kind='cash'):
 return {'schema_version':1,'profile_kind':'object_scene','target_object_kind':kind,'object_type_human_confirmed':True,'object_anchor_sec':0,
         'confirmed':True,'source_video_sha256':'a'*64,'zones':{'cashier_zone':[.1,.1,.4,.4],'object_zone':[.5,.5,.7,.7]},'roles':{'cashier_ids':[1],'client_ids':[]}}

class Tests(unittest.TestCase):
 def test_supported_human_types(self):
  for kind in ['bag','cash','documents']:self.assertEqual(analyze([],profile(kind),'a'*64)['status'],'partial')
 def test_bad_inputs_rejected(self):
  for field,value in [('object_anchor_sec',None),('object_anchor_sec',float('nan')),('object_type_human_confirmed',False),('target_object_kind','card'),('roles',{'cashier_ids':[]})]:
   p=profile();p[field]=value
   with self.assertRaises(ValueError):validate_profile(p)
 def test_object_region_required(self):
  p=profile();del p['zones']['object_zone']
  with self.assertRaises(ValueError):validate_profile(p)
 def test_human_types_do_not_become_automatic_classification(self):
  for kind in ['cash','documents']:
   r={'timeline':[{'timestamp_sec':i*.5,'cashier_presence':'away_observed','departure_supported':True,'cashier_ids':[1]} for i in range(5)]}
   o={i*.5:{'state':'mask_observed','bbox':[.5,.5,.7,.7]} for i in range(5)}
   s=attach_review(r,o,profile(kind))['experimental_signals'][0]
   self.assertEqual(s['human_target_kind'],kind);self.assertFalse(s['approved_for_rule_engine']);self.assertFalse(s['legal_violation_established'])
 def test_unknown_cashier_does_not_trigger(self):
  r={'timeline':[{'timestamp_sec':i*.5,'cashier_presence':'unknown','departure_supported':False,'cashier_ids':[]} for i in range(5)]}
  o={i*.5:{'state':'mask_observed','bbox':[.5,.5,.7,.7]} for i in range(5)}
  self.assertFalse(attach_review(r,o,profile())['experimental_signals'])

if __name__=='__main__':unittest.main()
