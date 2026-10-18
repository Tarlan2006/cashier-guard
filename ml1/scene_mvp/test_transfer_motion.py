import unittest
from run_transfer_motion import PROTOCOL
from scene_mvp.transfer_motion import infer_motion

def make_rows(states):
    return [{'timestamp_sec':i*.5,'relation':state,'reason':'role_owner_not_observed' if state=='unknown' else None,'all_masks_usable':True,'cash_motion_continuous':True,'cash_center_px':[10*i,20],'cash_diagonal_px':20} for i,state in enumerate(states)]

class MotionTests(unittest.TestCase):
    def test_direction_from_order(self):
        r=make_rows(['cashier_near']*2+['both_near']+['client_near']*2)
        self.assertEqual(infer_motion(r,PROTOCOL)[0]['direction'],'cashier_to_client')
    def test_reverse_order(self):
        r=make_rows(['client_near']*2+['both_near']+['cashier_near']*2)
        self.assertEqual(infer_motion(r,PROTOCOL)[0]['direction'],'client_to_cashier')
    def test_single_missing_id_stays_explicit(self):
        r=make_rows(['cashier_near']*2+['both_near','unknown']+['client_near']*2);e=infer_motion(r,PROTOCOL)[0]
        self.assertEqual(e['uncertain_times_sec'],[1.5]);self.assertFalse(e['missing_samples_interpolated']);self.assertFalse(e['approved_for_rule_engine'])
    def test_lost_object_cannot_bridge(self):
        r=make_rows(['cashier_near']*2+['both_near','unknown']+['client_near']*2);r[3]['reason']='missing_or_out_of_scale_mask';r[3]['all_masks_usable']=False
        self.assertFalse(infer_motion(r,PROTOCOL))
    def test_identity_collision_cannot_bridge(self):
        r=make_rows(['cashier_near']*2+['both_near','unknown']+['client_near']*2);r[3]['reason']='mask_identity_collision'
        self.assertFalse(infer_motion(r,PROTOCOL))
    def test_multiple_missing_ids_block(self):
        self.assertFalse(infer_motion(make_rows(['cashier_near']*2+['both_near','unknown','unknown']+['client_near']*2),PROTOCOL))
    def test_no_observed_contact_blocks(self):
        self.assertFalse(infer_motion(make_rows(['cashier_near']*2+['client_near']*2),PROTOCOL))
    def test_stationary_object_not_transfer(self):
        r=make_rows(['cashier_near']*2+['both_near']+['client_near']*2)
        for row in r:row['cash_center_px']=[10,20]
        self.assertFalse(infer_motion(r,PROTOCOL))
    def test_motion_jump_blocks(self):
        r=make_rows(['cashier_near']*2+['both_near']+['client_near']*2);r[2]['cash_motion_continuous']=False
        self.assertFalse(infer_motion(r,PROTOCOL))
    def test_unstable_holder_blocks(self):
        self.assertFalse(infer_motion(make_rows(['cashier_near','both_near','client_near']),PROTOCOL))
    def test_temporal_gap_blocks(self):
        r=make_rows(['cashier_near']*2+['both_near']+['client_near']*2)
        for row in r[2:]:row['timestamp_sec']+=1
        self.assertFalse(infer_motion(r,PROTOCOL))

if __name__=='__main__':unittest.main()
