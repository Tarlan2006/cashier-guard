import unittest
from scene_mvp.bag_events import attach_review

def fixture():
    p={'target_object_kind':'bag','object_type_human_confirmed':True,'zones':{'bag_zone':[.5,.5,.7,.7]},'stability_sec':1,'max_gap_sec':1}
    r={'signals':[],'timeline':[{'timestamp_sec':i*.5,'cashier_presence':'away_observed','departure_supported':True,'cashier_ids':[1]} for i in range(5)]}
    o={i*.5:{'state':'mask_observed','bbox':[.5,.5,.7,.7]} for i in range(5)}
    return r,o,p
class Tests(unittest.TestCase):
    def test_observed_departure_with_object(self):
        r,o,p=fixture();self.assertEqual(len(attach_review(r,o,p)['experimental_signals']),1)
    def test_missing_cashier_not_absence(self):
        r,o,p=fixture()
        for x in r['timeline']:x['cashier_presence']='unknown'
        self.assertFalse(attach_review(r,o,p)['experimental_signals'])
    def test_missing_object_unknown(self):
        r,o,p=fixture();self.assertFalse(attach_review(r,{},p)['experimental_signals'])
    def test_no_departure_support(self):
        r,o,p=fixture()
        for x in r['timeline']:x['departure_supported']=False
        self.assertFalse(attach_review(r,o,p)['experimental_signals'])
    def test_moving_object_not_left(self):
        r,o,p=fixture()
        for i,x in enumerate(o.values()):x['bbox']=[.1*i,.5,.1*i+.2,.7]
        self.assertFalse(attach_review(r,o,p)['experimental_signals'])
    def test_reference_required(self):
        r,o,p=fixture();p['object_type_human_confirmed']=False
        with self.assertRaises(ValueError):attach_review(r,o,p)
if __name__=='__main__':unittest.main()
