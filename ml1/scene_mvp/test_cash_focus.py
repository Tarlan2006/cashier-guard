import unittest
from scene_mvp.cash_focus import focus_bounds,local_box


class FocusTests(unittest.TestCase):
    def test_seed_transform_preserves_original_pixel_position(self):
        zones={'cash_seed':[.4,.4,.45,.42],'machine_zone':[.1,.35,.25,.48],'safe_zone':[.4,.3,.65,.45]}
        roi=focus_bounds(zones,464,848);b=local_box(zones['cash_seed'],roi,464,848)
        self.assertAlmostEqual(b[0]+roi[0],.4*464)
        self.assertAlmostEqual(b[1]+roi[1],.4*848)
        self.assertLess(roi[3]-roi[1],848)
    def test_crop_clamps_to_frame(self):
        zones={k:[0,0,1,1] for k in ['cash_seed','machine_zone','safe_zone']}
        self.assertEqual(focus_bounds(zones,464,848),[0,0,464,848])
    def test_incompatible_seed_is_not_clipped_or_shifted(self):
        with self.assertRaises(ValueError):local_box([.1,.1,.2,.2],[100,100,200,200],464,848)


if __name__=='__main__':unittest.main()
