import copy,unittest
from scene_mvp.money_contacts import candidates

def row(t,cashier,client,cash=True):
    return {'timestamp_sec':t,'cash_observed':cash,'hand_proximity':{'cashier':cashier,'client':client},'identity_collision':False}
def sample():
    return [row(0,'far','near'),row(.5,'far','far'),row(1,'unknown','unknown',False),row(1.5,'near','unknown'),row(2,'near','unknown')]

class ContextTests(unittest.TestCase):
    def test_partial_contact_sequence_keeps_cash_gap_and_no_established_direction(self):
        e=candidates(sample())[0];self.assertEqual(e['direction'],'client_to_cashier');self.assertEqual(e['missing_cash_times_sec'],[1]);self.assertFalse(e['cash_identity_continuity_established']);self.assertFalse(e['direction_established']);self.assertFalse(e['approved_for_rule_engine']);self.assertFalse(e['missing_samples_interpolated']);self.assertFalse(e['other_hand_observed_at_end'])
    def test_swapping_roles_inverts_hypothesis(self):
        rows=sample()
        for r in rows:r['hand_proximity']={'cashier':r['hand_proximity']['client'],'client':r['hand_proximity']['cashier']}
        self.assertEqual(candidates(rows)[0]['direction'],'cashier_to_client')
    def test_more_than_one_lost_cash_sample_rejected(self):
        rows=sample();rows[1]=row(.5,'unknown','unknown',False);self.assertFalse(candidates(rows))
    def test_identity_collision_rejected(self):
        rows=sample();rows[1]['identity_collision']=True;self.assertFalse(candidates(rows))
    def test_unknown_initial_other_hand_does_not_establish_exclusive_start(self):
        rows=sample();rows[0]['hand_proximity']['cashier']='unknown';self.assertFalse(candidates(rows))
    def test_no_stable_after_contact_no_candidate(self):
        self.assertFalse(candidates(sample()[:-1]))
    def test_joint_contact_alone_has_no_direction(self):
        self.assertFalse(candidates([row(t,'near','near') for t in (0,.5,1)]))
    def test_time_gap_rejected(self):
        rows=sample()
        for r in rows[2:]:r['timestamp_sec']+=1
        self.assertFalse(candidates(rows))

if __name__=='__main__':unittest.main()
