import unittest
import numpy as np
from scene_mvp.door_model import feature,fit,score,classify,metrics
class DoorTests(unittest.TestCase):
 def test_empty_crop_rejected(self):
  with self.assertRaises(ValueError):feature(np.empty((0,0,3),dtype=np.uint8))
 def test_hog_blank_and_orientation(self):
  blank=np.zeros((64,64),dtype=np.uint8);vertical=blank.copy();vertical[:,32:]=255;horizontal=blank.copy();horizontal[32:,:]=255
  a=feature(vertical);b=feature(horizontal)
  self.assertEqual(a.shape,(1764,));self.assertTrue(np.isfinite(a).all());self.assertGreater(np.linalg.norm(a-b),1);self.assertEqual(float(np.linalg.norm(feature(blank))),0)
 def test_fit_simple_separable_data(self):
  x=np.array([[-3,-1],[-2,-1],[-1,-2],[1,2],[2,1],[3,1]],float);m=fit(x,[0,0,0,1,1,1]);self.assertEqual(classify(score(m,[[-2,-2],[2,2]])),['closed','open'])
 def test_missing_class_rejected(self):
  with self.assertRaises(ValueError):fit([[1,2],[3,4]],[1,1])
 def test_uncertain_band(self):self.assertEqual(classify([.1,.5,.9]),['closed','unknown','open'])
 def test_unknown_not_counted_as_correct(self):
  m=metrics(['open','closed'],['unknown','closed']);self.assertEqual(m['correct'],1);self.assertEqual(m['coverage'],.5);self.assertEqual(m['unclear_open_frames'],1);self.assertEqual(m['balanced_accuracy'],.5)
 def test_false_positive_separate_from_miss(self):
  m=metrics(['open','closed'],['closed','open']);self.assertEqual(m['false_open_frames'],1);self.assertEqual(m['missed_open_frames'],1)
if __name__=='__main__':unittest.main()
