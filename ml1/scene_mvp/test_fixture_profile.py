import unittest
from scene_mvp.engine import validate_profile,analyze

def profile():return {'schema_version':1,'profile_kind':'fixture_only','fixture_kind':'cash_storage_cabinet','confirmed':True,'source_video_sha256':'a'*64,'zones':{'safe_zone':[.1,.1,.9,.9]},'roles':{}}
class Tests(unittest.TestCase):
 def test_confirmed_fixture(self):self.assertEqual(validate_profile(profile())['fixture_kind'],'cash_storage_cabinet')
 def test_missing_safe_zone(self):
  p=profile();p['zones']={}
  with self.assertRaises(ValueError):validate_profile(p)
 def test_wrong_kind(self):
  p=profile();p['fixture_kind']='entrance_door'
  with self.assertRaises(ValueError):validate_profile(p)
 def test_not_a_scene_profile(self):
  with self.assertRaises(ValueError):analyze([],profile(),'a'*64)
if __name__=='__main__':unittest.main()
