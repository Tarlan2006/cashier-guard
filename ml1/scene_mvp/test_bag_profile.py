import unittest
from scene_mvp.engine import validate_profile,analyze

def profile():return {'schema_version':1,'profile_kind':'bag_scene','target_object_kind':'bag','object_type_human_confirmed':True,'confirmed':True,'source_video_sha256':'a'*64,'zones':{'cashier_zone':[.1,.1,.4,.4],'bag_zone':[.5,.5,.7,.7]},'roles':{'cashier_ids':[1],'client_ids':[]}}
class Tests(unittest.TestCase):
 def test_bag_scene_without_visitor_zone(self):self.assertEqual(analyze([],profile(),'a'*64)['status'],'partial')
 def test_object_confirmation_required(self):
  p=profile();p['object_type_human_confirmed']=False
  with self.assertRaises(ValueError):validate_profile(p)
 def test_missing_bag_region(self):
  p=profile();del p['zones']['bag_zone']
  with self.assertRaises(ValueError):validate_profile(p)
 def test_other_object_not_bag(self):
  p=profile();p['target_object_kind']='banknotes'
  with self.assertRaises(ValueError):validate_profile(p)
if __name__=='__main__':unittest.main()
