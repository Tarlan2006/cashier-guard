import unittest
from scene_mvp.experimental_visitors import attach_review

def setup(near=True):
    profile={'confirmed':True,'zones':{'service_zone':[.3,.3,.6,.6]},'stability_sec':1,'max_gap_sec':1}
    a={'id':5,'role':'client','in_service_zone':True,'bbox':[.3,.3,.5,.5]}
    b={'id':11,'role':'client','in_service_zone':False,'bbox':[.2,.3,.4,.6] if near else [.0,.0,.1,.1]}
    r={'status':'partial','signals':[],'timeline':[{'timestamp_sec':i*.5,'cashier_presence':'present','persons':[dict(a),dict(b)]} for i in range(4)]}
    return r,profile

class Tests(unittest.TestCase):
    def test_distinct_second_approach(self):
        r,p=setup();attach_review(r,p)
        self.assertEqual(r['signals'],[])
        self.assertEqual(r['experimental_signals'][0]['participant_ids'],[5,11])
        self.assertFalse(r['experimental_signals'][0]['service_started_established'])
    def test_far_second_not_counted(self):
        r,p=setup(False);self.assertFalse(attach_review(r,p)['experimental_signals'])
    def test_only_one_person(self):
        r,p=setup()
        for row in r['timeline']:row['persons']=row['persons'][:1]
        self.assertFalse(attach_review(r,p)['experimental_signals'])
    def test_no_cashier(self):
        r,p=setup()
        for row in r['timeline']:row['cashier_presence']='unknown'
        self.assertFalse(attach_review(r,p)['experimental_signals'])
    def test_unknown_role_not_client(self):
        r,p=setup()
        for row in r['timeline']:row['persons'][1]['role']='unknown'
        self.assertFalse(attach_review(r,p)['experimental_signals'])
    def test_gap_breaks_support(self):
        r,p=setup();r['timeline']=r['timeline'][:2];r['timeline'][1]['timestamp_sec']=3
        self.assertFalse(attach_review(r,p)['experimental_signals'])
    def test_short_approach_not_event(self):
        r,p=setup();r['timeline']=r['timeline'][:2]
        self.assertFalse(attach_review(r,p)['experimental_signals'])
    def test_unconfirmed_rejected(self):
        r,p=setup();p['confirmed']=False
        with self.assertRaises(ValueError):attach_review(r,p)

if __name__=='__main__':unittest.main()
