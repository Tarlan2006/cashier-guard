import unittest
import numpy as np
from scene_mvp.crop_object_classifier import fit,predict,weights


def row(kind,frame):return {'object_kind':kind,'video_sha256':'v'+kind,'image_sha256':frame}


class CropTests(unittest.TestCase):
    def test_three_class_fit_uses_labels_and_learns_separable_features(self):
        rows=[row('banknotes','a'),row('card','b'),row('other','c')]
        x=np.eye(3);m=fit(x,rows)
        self.assertEqual([p['top_class'] for p in predict(m,x)],['banknotes','card','other'])

    def test_duplicate_views_do_not_multiply_class_weight(self):
        rows=[row('banknotes','a'),row('card','b'),row('other','c')]
        w=weights(rows+[row('banknotes','a')]*5)
        self.assertAlmostEqual(w[0]+sum(w[3:]),1/3)

    def test_missing_class_and_nonfinite_features_rejected(self):
        with self.assertRaises(ValueError):fit(np.eye(2),[row('banknotes','a'),row('card','b')])
        with self.assertRaises(ValueError):fit([[np.nan],[1],[2]],[row('banknotes','a'),row('card','b'),row('other','c')])


if __name__=='__main__':unittest.main()
