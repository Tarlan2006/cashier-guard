from pathlib import Path
import tempfile
import unittest
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from backend.pipeline.zone_linear import LinearZoneModel


class Encoder:
    feature = None

    def encode_crop(self, crop):
        return self.feature


class LinearHeadTests(unittest.TestCase):
    def test_numeric_artifact_matches_independent_sklearn_probabilities(self):
        rng = np.random.default_rng(42)
        x = rng.normal(size=(40, 8))
        y = (x[:, 0] > 0.1).astype(int)
        pipeline = make_pipeline(
            StandardScaler(), LogisticRegression(C=0.1, random_state=42)
        )
        pipeline.fit(x, y)
        with tempfile.TemporaryDirectory() as directory:
            np.savez(
                Path(directory) / "table_linear.npz",
                mean=pipeline[0].mean_,
                scale=pipeline[0].scale_,
                coef=pipeline[1].coef_,
                intercept=pipeline[1].intercept_,
                classes=pipeline[1].classes_,
            )
            encoder = Encoder()
            model = LinearZoneModel(encoder, directory)
            for feature in rng.normal(size=(5, 8)):
                encoder.feature = feature
                probability = model.classify(None, "table")["scores"]["items"]
                self.assertAlmostEqual(
                    probability, pipeline.predict_proba(feature[None])[0, 1], places=12
                )

    def test_missing_head_is_unknown_without_zero_shot_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            model = LinearZoneModel(Encoder(), directory)
            self.assertEqual(model.classify(None, "safe")["state"], "unknown")
