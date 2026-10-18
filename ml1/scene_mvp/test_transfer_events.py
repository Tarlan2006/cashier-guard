import unittest
from scene_mvp.transfer_events import infer

def rows(states):
 return [{'timestamp_sec':i*.5,'relation':s,'cash_center_px':[10+10*i,20],'cash_diagonal_px':20} for i,s in enumerate(states)]
class Tests(unittest.TestCase):
 def test_forward_hypothesis(self):self.assertEqual(infer(rows(['cashier_near']*2+['both_near']+['client_near']*2))[0]['direction'],'cashier_to_client')
 def test_reverse_hypothesis(self):self.assertEqual(infer(rows(['client_near']*2+['both_near']+['cashier_near']*2))[0]['direction'],'client_to_cashier')
 def test_unknown_cannot_bridge_transfer(self):self.assertFalse(infer(rows(['cashier_near']*2+['unknown']+['client_near']*2)))
 def test_stationary_object_does_not_imply_transfer(self):
  r=rows(['cashier_near']*2+['client_near']*2)
  for x in r:x['cash_center_px']=[10,20]
  self.assertFalse(infer(r))
 def test_unstable_contact_insufficient(self):self.assertFalse(infer(rows(['cashier_near','client_near'])))
 def test_gap_cannot_bridge_transfer(self):
  r=rows(['cashier_near']*2+['client_near']*2);r[2]['timestamp_sec']=4;r[3]['timestamp_sec']=4.5;self.assertFalse(infer(r))
if __name__=='__main__':unittest.main()
