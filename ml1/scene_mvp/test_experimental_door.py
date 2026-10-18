import copy,unittest
from scene_mvp.experimental_door import attach_review

def result():
    return {'status':'partial','signals':[],'coverage':{},'timeline':[{'timestamp_sec':i*.5,'cashier_presence':'away_observed','departure_supported':True,'cashier_ids':[1],'door':{'state':'unknown','source':'not_observed'}} for i in range(5)]}
def obs(states):return {i*.5:{'state':s,'source':'experimental_door_classifier'} for i,s in enumerate(states)}

class ExperimentalTests(unittest.TestCase):
    def test_separate_from_human_and_rules(self):
        x=result();old=copy.deepcopy(x)
        attach_review(x,obs(['open']*5))
        self.assertEqual(x['signals'],old['signals'])
        self.assertEqual([r['door'] for r in x['timeline']],[r['door'] for r in old['timeline']])
        self.assertEqual(len(x['experimental_signals']),1)
        self.assertFalse(x['experimental_signals'][0]['legal_violation_established'])
    def test_unknown_breaks_episode(self):
        x=attach_review(result(),obs(['open','open','unknown','open','open']))
        self.assertFalse(x['experimental_signals'])
    def test_missing_is_unknown(self):
        x=attach_review(result(),{})
        self.assertTrue(all(r['experimental_door']['state']=='unknown' for r in x['timeline']))
    def test_no_departure_support_no_event(self):
        x=result()
        for r in x['timeline']:r['departure_supported']=False
        self.assertFalse(attach_review(x,obs(['open']*5))['experimental_signals'])
    def test_present_no_event(self):
        x=result()
        for r in x['timeline']:r['cashier_presence']='present'
        self.assertFalse(attach_review(x,obs(['open']*5))['experimental_signals'])
    def test_wrong_source_rejected(self):
        with self.assertRaises(ValueError):attach_review(result(),{0:{'state':'open','source':'human_frame_label'}})
    def test_gap_not_bridged(self):
        x=result();x['timeline'][2:]=[];x['timeline'][1]['timestamp_sec']=3.
        self.assertFalse(attach_review(x,{0:{'state':'open','source':'experimental_door_classifier'},3:{'state':'open','source':'experimental_door_classifier'}})['experimental_signals'])

if __name__=='__main__':unittest.main()
