import unittest
from build_transfer_review import gate_owners

class OwnerTests(unittest.TestCase):
    def test_missing_owner_preserves_raw_and_blocks_relation(self):
        rows=[{'timestamp_sec':1.,'relation':'client_near'}]
        frames=[{'timestamp_sec':1.,'persons':[{'id':1,'observed':True,'confidence':.9}]}]
        out=gate_owners(rows,frames,{'cashier_ids':[1],'client_ids':[4]})
        self.assertEqual(out[0]['relation'],'unknown');self.assertEqual(out[0]['proximity_relation'],'client_near')
        self.assertEqual(rows[0]['relation'],'client_near')
    def test_reflection_is_not_owner(self):
        frames=[{'timestamp_sec':1.,'persons':[{'id':1,'observed':True,'confidence':.9},{'id':4,'observed':True,'confidence':.9,'is_reflection':True}]}]
        out=gate_owners([{'timestamp_sec':1.,'relation':'client_near'}],frames,{'cashier_ids':[1],'client_ids':[4]})
        self.assertEqual(out[0]['relation'],'unknown')
    def test_both_observed_preserve_relation(self):
        frames=[{'timestamp_sec':1.,'persons':[{'id':k,'observed':True,'confidence':.9} for k in (1,4)]}]
        out=gate_owners([{'timestamp_sec':1.,'relation':'client_near'}],frames,{'cashier_ids':[1],'client_ids':[4]})
        self.assertEqual(out[0]['relation'],'client_near')

if __name__=='__main__':unittest.main()
