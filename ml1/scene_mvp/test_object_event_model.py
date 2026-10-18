import copy,unittest
import numpy as np
from scene_mvp.object_event_model import extract,fit,predict

def fixture(outside=True):
    profile={'schema_version':1,'profile_kind':'object_scene','target_object_kind':'bag','object_type_human_confirmed':True,'object_anchor_sec':0,'source_video_sha256':'a'*64,'confirmed':True,'zones':{'cashier_zone':[.4,.4,.6,.6],'object_zone':[.45,.45,.55,.55]},'roles':{'cashier_ids':[1],'client_ids':[]}}
    box=[.1,.1,.2,.2] if outside else [.45,.45,.55,.55]
    rows=[{'timestamp_sec':i*.5,'persons':[{'id':1,'role':'cashier','role_source':'user_confirmed_track','bbox':box}],'experimental_object':{'state':'mask_observed','bbox':[.45,.45,.55,.55]}} for i in range(8)]
    return {'timeline':rows,'signals':[{'type':'untrusted_prediction'}]},profile

class EventModelTests(unittest.TestCase):
    def test_nonempty_physical_features_for_visible_separation(self):
        o,p=fixture();r=extract(o,p);self.assertTrue(r['usable']);self.assertGreater(r['windows'][0]['feature'][0],0)
    def test_inside_zone_has_no_separation_feature(self):
        o,p=fixture(False);r=extract(o,p);self.assertTrue(r['usable']);self.assertTrue(np.allclose([w['feature'] for w in r['windows']],0))
    def test_missing_cashier_not_inferred_away(self):
        o,p=fixture()
        for row in o['timeline']:row['persons']=[];row['cashier_presence']='away_observed'
        self.assertFalse(extract(o,p)['usable'])
    def test_missing_object_not_inferred_removed_or_negative(self):
        o,p=fixture()
        for row in o['timeline']:row['experimental_object']={'state':'unknown','bbox':None}
        r=extract(o,p);self.assertFalse(r['usable']);self.assertEqual(r['windows'],[])
    def test_cash_rejected(self):
        o,p=fixture();p['target_object_kind']='cash'
        with self.assertRaises(ValueError):extract(o,p)
    def test_rule_predictions_do_not_enter_features(self):
        o,p=fixture();r=extract(o,p);changed=copy.deepcopy(o);changed['signals']=[{'label':'positive','start_sec':123}]
        for row in changed['timeline']:row.update(departure_supported=False,cashier_presence='unknown');row['experimental_object'].update(near_reference_region=False,stationary_between_samples=False)
        self.assertEqual(r['windows'],extract(changed,p)['windows'])
    def test_gap_not_bridged(self):
        o,p=fixture();o['timeline']=o['timeline'][:3]
        for i,row in enumerate(o['timeline']):row['timestamp_sec']=i*2
        self.assertFalse(extract(o,p)['usable'])
    def test_small_cpu_model_learns_on_video_labels(self):
        positive,p=fixture();negative,_=fixture(False);a=extract(positive,p);b=extract(negative,p);model=fit([[w['feature'] for w in a['windows']],[w['feature'] for w in b['windows']]],[1,0]);pa=predict(model,a);pb=predict(model,b)
        self.assertGreater(pa['video_risk_score'],pb['video_risk_score']);self.assertIsNone(pa['legal_violation_label']);self.assertTrue(pa['candidate']['weak_localization_only']);self.assertTrue(np.all(model['weight']>=0))
    def test_both_label_classes_required(self):
        with self.assertRaises(ValueError):fit([np.zeros((2,3)),np.zeros((3,3))],[0,0])

if __name__=='__main__':unittest.main()
