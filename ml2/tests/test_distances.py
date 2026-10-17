"""Known projective geometry, invalid calibration and unchanged default roles."""
from copy import deepcopy
import unittest
import cv2
import numpy as np

from backend.pipeline.perception.distances import (
    ImageDistance, PlanarDistance, RelativeDepthDistance, PlaneHypothesis,
    annotate_proximity, auto_workzone, corners, footpoint, ordered_quad,
)
from backend.pipeline.perception.roles_v2 import assign_temporal_roles


def scene():
    return dict(video=dict(width=400,height=600,duration_sec=12),sample_interval_sec=.5,
        fixtures=[{'class':'counter_machine','bbox':[.2,.35,.3,.45]},
                  {'class':'laptop','bbox':[.55,.35,.65,.45]}],
        frames=[dict(timestamp_sec=i*.5,actual_timestamp_sec=i*.5,objects=[],persons=[
            dict(id=1,bbox=[.45,.4,.6,.8],confidence=.9,counted=True,track_confirmed=True,is_reflection=False,uncertain=False),
            *([dict(id=2,bbox=[.25,.2,.4,.5],confidence=.9,counted=True,track_confirmed=True,is_reflection=False,uncertain=False)] if i>=4 else [])]) for i in range(24)])


class DistanceTests(unittest.TestCase):
    def test_known_homography_recovers_plane_distance(self):
        quad=np.array([[.2,.2],[.8,.25],[.95,.85],[.05,.9]],np.float32)
        model=PlanarDistance(400,600,PlaneHypothesis(quad,'synthetic_correspondences'))
        image_from_world=cv2.getPerspectiveTransform(np.array([[0,0],[1,0],[1,1],[0,1]],np.float32),quad)
        world=np.array([[[.2,.3],[.8,.7]]],np.float32)
        image=cv2.perspectiveTransform(world,image_from_world)[0]
        reconstructed=model.project(image)
        np.testing.assert_allclose(reconstructed,world[0]/np.sqrt(2),atol=1e-6)
        self.assertAlmostEqual(np.linalg.norm(reconstructed[0]-reconstructed[1]),np.hypot(.6,.4)/np.sqrt(2),places=6)

    def test_degenerate_four_points_rejected(self):
        with self.assertRaisesRegex(ValueError,'Degenerate'):
            ordered_quad([[0,0],[.1,.1],[.2,.2],[.3,.3]])

    def test_automatic_table_proposal_never_claims_floor_calibration(self):
        hypothesis=auto_workzone(np.zeros((600,400,3),np.uint8),scene())
        self.assertIsNotNone(hypothesis)
        self.assertFalse(hypothesis.calibrated_floor)
        self.assertIn('fallback',hypothesis.source)
        empty=scene();empty['fixtures']=[]
        self.assertIsNone(auto_workzone(np.zeros((600,400,3),np.uint8),empty))

    def test_relative_depth_rejects_flat_nan_and_wrong_shape(self):
        hypothesis=PlaneHypothesis(corners([.1,.1,.9,.9]),'synthetic')
        for depth in [np.ones((60,40)),np.full((60,40),np.nan),np.ones((40,60))]:
            with self.assertRaises(ValueError):RelativeDepthDistance(40,60,depth,hypothesis)

    def test_depth_distance_is_affine_gauge_invariant_not_metric(self):
        depth=np.linspace(.2,9,60*40).reshape(60,40)
        h=PlaneHypothesis(corners([.1,.1,.9,.9]),'synthetic')
        first=RelativeDepthDistance(40,60,depth,h)
        second=RelativeDepthDistance(40,60,3*depth+7,h)
        a,b=[.2,.3,.3,.6],[.6,.4,.7,.5]
        self.assertAlmostEqual(first.anchor_distance(a,b),second.anchor_distance(a,b),places=8)
        self.assertFalse(first.calibrated_floor)

    def test_mirrored_depth_preserves_pair_distance(self):
        depth=np.linspace(.2,9,60*40).reshape(60,40)
        h=PlaneHypothesis(corners([.1,.1,.9,.9]),'synthetic')
        first=RelativeDepthDistance(40,60,depth,h)
        second=RelativeDepthDistance(40,60,depth[:,::-1],h)
        a,b=[.2,.3,.3,.6],[.6,.4,.7,.5]
        flip=lambda v:[1-v[2],v[1],1-v[0],v[3]]
        self.assertAlmostEqual(first.anchor_distance(a,b),second.anchor_distance(flip(a),flip(b)),places=6)

    def test_bbox_bottom_midpoint_is_not_rotation_equivariant(self):
        box=[.2,.2,.4,.8]
        matrix=cv2.getRotationMatrix2D((.5,.5),20,1)
        warped=np.c_[corners(box),np.ones(4)]@matrix.T
        rotated_box=np.r_[warped.min(axis=0),warped.max(axis=0)]
        actual=np.r_[footpoint(box),1]@matrix.T
        self.assertGreater(np.linalg.norm(actual-footpoint(rotated_box)),.05)

    def test_explicit_baseline_matches_unmodified_production_roles(self):
        default=assign_temporal_roles(scene())
        explicit=assign_temporal_roles(scene(),distance_model=ImageDistance(400,600))
        for a,b in zip(default['frames'],explicit['frames']):
            for p,q in zip(a['persons'],b['persons']):
                for key in ['role','cashier_prob','client_prob','near_table']:
                    self.assertEqual(p[key],q[key])

    def test_reflections_and_unconfirmed_tracks_not_near_objects(self):
        facts=scene()
        person=facts['frames'][0]['persons'][0]
        person['bbox']=[.2,.35,.3,.45];person['is_reflection']=True
        annotate_proximity(facts,ImageDistance(400,600))
        self.assertFalse(person['near_machine'])
        self.assertFalse(person['near_table'])


if __name__=='__main__':unittest.main()
