"""Experimental scene distances. No camera calibration is inferred as fact.

A table/anchor quadrilateral is only a plane hypothesis: raised objects and
occluded feet do not establish four corresponding points on a physical floor.
The production roles use the original geometry unless explicitly injected.
"""

from __future__ import annotations
from dataclasses import dataclass
import cv2
import numpy as np
from .scene_geometry import center, desk_box, distance_to_box


def footpoint(box) -> np.ndarray:
    b = np.asarray(box, float)
    return np.array([(b[0] + b[2]) / 2, b[3]])


def corners(box) -> np.ndarray:
    x1, y1, x2, y2 = box
    return np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], float)


def ordered_quad(points) -> np.ndarray:
    points = np.asarray(points, np.float32)
    if points.shape != (4, 2) or not np.isfinite(points).all():
        raise ValueError("Four finite image points required")
    hull = cv2.convexHull(points).reshape(-1, 2)
    if len(hull) != 4 or abs(cv2.contourArea(hull)) < 1e-5:
        raise ValueError("Degenerate plane hypothesis")
    hull = hull[np.argsort(np.arctan2(hull[:, 1]-hull[:, 1].mean(),
                                    hull[:, 0]-hull[:, 0].mean()))]
    return np.roll(hull, -int(np.argmin(hull.sum(axis=1))), axis=0)


def polygon_distance(point, polygon) -> float:
    """Euclidean distance to a closed filled convex polygon, 2D or 3D edges."""
    p, q = np.asarray(point, float), np.asarray(polygon, float)
    if len(p) == 2 and cv2.pointPolygonTest(q.astype(np.float32), tuple(p), False) >= 0:
        return 0.0
    a, b = q, np.roll(q, -1, axis=0)
    delta = b-a
    t = np.clip(((p-a)*delta).sum(axis=1) / np.maximum((delta*delta).sum(axis=1), 1e-12), 0, 1)
    return float(np.linalg.norm(p-a-t[:, None]*delta, axis=1).min())


@dataclass
class PlaneHypothesis:
    quad: np.ndarray
    source: str
    calibrated_floor: bool = False


def auto_workzone(image: np.ndarray, facts: dict) -> PlaneHypothesis | None:
    """Four automatic table/anchor-derived points, explicitly not floor labels."""
    table = desk_box(facts)
    if table is None:
        return None
    h, w = image.shape[:2]
    dims = np.array([w, h], float)
    box = np.asarray(table, float)
    pad = 0.15*(box[2:]-box[:2])
    lo, hi = np.maximum(0, box[:2]-pad), np.minimum(1, box[2:]+pad)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    white = cv2.inRange(hsv, (0, 0, 135), (180, 85, 255))
    roi = np.zeros((h, w), np.uint8)
    x1, y1 = np.floor(lo*dims).astype(int)
    x2, y2 = np.ceil(hi*dims).astype(int)
    roi[y1:y2, x1:x2] = white[y1:y2, x1:x2]
    size = max(3, int(round(min(h, w)*0.01)) | 1)
    roi = cv2.morphologyEx(roi, cv2.MORPH_CLOSE, np.ones((size, size), np.uint8))
    contours, _ = cv2.findContours(roi, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    anchors = [center(f['bbox'])*dims for f in facts.get('fixtures', [])
               if f['class'] in {'counter_machine', 'laptop'}]
    candidates = []
    edge_mask = cv2.Canny(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),60,160)
    edge_mask[:y1] = 0
    edge_mask[y2:] = 0
    edge_mask[:,:x1] = 0
    edge_mask[:,x2:] = 0
    edge_contours,_ = cv2.findContours(edge_mask,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    for contour in [*contours,*edge_contours]:
        area = cv2.contourArea(contour)/(w*h)
        if not 0.03 <= area <= 0.65:
            continue
        hull = cv2.convexHull(contour)
        polygon = cv2.approxPolyDP(hull, 0.025*cv2.arcLength(hull, True), True)
        quad = polygon.reshape(-1, 2) if len(polygon) == 4 else cv2.boxPoints(cv2.minAreaRect(hull))
        # A workzone must contain every desk anchor, not just one nearby patch.
        if anchors and not all(cv2.pointPolygonTest(quad.astype(np.float32), tuple(p), False) >= 0 for p in anchors):
            continue
        candidates.append((area, quad/dims))
    if candidates:
        quad = ordered_quad(max(candidates, key=lambda p: p[0])[1])
        source = 'automatic_table_edge_or_light_contour_not_floor_calibration'
    else:
        quad = ordered_quad(corners(table))
        source = 'anchor_table_bbox_affine_fallback_not_floor_calibration'
    # A scene-relative workzone proposal; its vertices are not surveyed floor
    # points. Expansion is the same for every scene and is not metric evidence.
    quad = quad.mean(axis=0) + 1.5*(quad-quad.mean(axis=0))
    return PlaneHypothesis(ordered_quad(quad), source)


class ImageDistance:
    name = 'baseline_center_diagonal'
    units = 'frame_diagonal'
    calibrated_floor = False

    def __init__(self, width: int, height: int, *, use_feet: bool = False):
        dims = np.array([width, height], float)
        self.scale = dims/np.linalg.norm(dims)
        self.use_feet = use_feet
        if use_feet:
            self.name = 'footpoint_diagonal_ablation'

    def threshold(self, frame_diagonal_value: float) -> float:
        return frame_diagonal_value

    def anchor_distance(self, person_box, anchor_box) -> float:
        person = footpoint(person_box) if self.use_feet else center(person_box)
        anchor = footpoint(anchor_box) if self.use_feet else center(anchor_box)
        return float(np.linalg.norm((person-anchor)*self.scale))

    def table_distance(self, person_box, table_box) -> float:
        point = footpoint(person_box) if self.use_feet else center(person_box)
        return distance_to_box(point, table_box, self.scale)


class PlanarDistance(ImageDistance):
    name = 'A_automatic_plane_proxy'
    units = 'hypothetical_workzone_diagonal'

    def __init__(self, width: int, height: int, hypothesis: PlaneHypothesis):
        super().__init__(width, height, use_feet=True)
        self.name = 'A_automatic_plane_proxy'
        self.hypothesis = hypothesis
        quad = ordered_quad(hypothesis.quad)
        self.matrix = cv2.getPerspectiveTransform(quad, np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32))
        if not np.isfinite(self.matrix).all() or np.linalg.cond(self.matrix) > 1e8:
            raise ValueError('Ill-conditioned plane homography')
        self.reference = max(np.linalg.norm((a-b)*self.scale) for a in quad for b in quad)

    def threshold(self, frame_diagonal_value: float) -> float:
        # Convert an existing image-distance prior into workzone-diagonal units.
        # This supplies a common unsupervised scale, not a measured floor size.
        return frame_diagonal_value/max(self.reference, 1e-6)

    def project(self, points) -> np.ndarray:
        p = np.c_[np.asarray(points, float).reshape(-1, 2), np.ones(len(points))] @ self.matrix.T
        if np.any(np.abs(p[:, 2]) < 1e-5) or not np.isfinite(p).all():
            raise ValueError('Point lies near a projective horizon')
        result = p[:, :2]/p[:, 2:]/np.sqrt(2)
        if np.max(np.abs(result)) > 100:
            raise ValueError('Unstable plane extrapolation')
        return result

    def anchor_distance(self, person_box, anchor_box) -> float:
        p = self.project([footpoint(person_box), footpoint(anchor_box)])
        return float(np.linalg.norm(p[0]-p[1]))

    def table_distance(self, person_box, table_box) -> float:
        p = self.project(np.r_[[footpoint(person_box)], corners(table_box)])
        return polygon_distance(p[0], p[1:])


class RelativeDepthDistance(ImageDistance):
    name = 'B_relative_depth_proxy'
    units = 'relative_depth_workzone_diagonal'

    def __init__(self, width: int, height: int, depth: np.ndarray, hypothesis: PlaneHypothesis):
        super().__init__(width, height, use_feet=True)
        self.name = 'B_relative_depth_proxy'
        self.depth = np.asarray(depth, float)
        if self.depth.shape != (height, width) or not np.isfinite(self.depth).all():
            raise ValueError('Invalid relative depth map')
        self.low, high = np.quantile(self.depth, [.02, .98])
        self.spread = high-self.low
        if self.spread <= 1e-6:
            raise ValueError('Relative depth has no usable contrast')
        self.diagonal = np.hypot(width, height)
        q = self.project(hypothesis.quad, normalize=False)
        self.normalizer = max(np.linalg.norm(a-b) for a in q for b in q)
        self.reference = max(np.linalg.norm((a-b)*self.scale) for a in hypothesis.quad for b in hypothesis.quad)

    def threshold(self, frame_diagonal_value: float) -> float:
        return frame_diagonal_value/max(self.reference, 1e-6)

    def project(self, points, *, normalize=True) -> np.ndarray:
        h, w = self.depth.shape
        result = []
        for p in np.asarray(points, float):
            x, y = np.clip(np.rint(p*[w-1, h-1]), [0, 0], [w-1, h-1]).astype(int)
            patch = self.depth[max(0,y-2):min(h,y+3), max(0,x-2):min(w,x+3)]
            inverse = np.clip((float(np.median(patch))-self.low)/self.spread, 0, 1)
            # Monocular inverse depth is affine-ambiguous. This is a fixed
            # relative-depth embedding, not metric camera back-projection.
            z = 1/(0.1+inverse)
            xy = (p-0.5)*np.array([w,h])/self.diagonal*z
            result.append(np.r_[xy,z])
        result = np.asarray(result)
        return result/self.normalizer if normalize else result

    def anchor_distance(self, person_box, anchor_box) -> float:
        p = self.project([footpoint(person_box), footpoint(anchor_box)])
        return float(np.linalg.norm(p[0]-p[1]))

    def table_distance(self, person_box, table_box) -> float:
        point = footpoint(person_box)
        if cv2.pointPolygonTest(corners(table_box).astype(np.float32), tuple(point), False) >= 0:
            return 0.0
        p = self.project(np.r_[[point], corners(table_box)])
        return polygon_distance(p[0],p[1:])


def annotate_proximity(facts: dict, metric: ImageDistance) -> dict:
    table = desk_box(facts)
    machines = [f['bbox'] for f in facts.get('fixtures', []) if f['class']=='counter_machine']
    for frame in facts['frames']:
        for person in frame['persons']:
            valid = person.get('counted', False) and not person.get('is_reflection', False)
            person['near_table'] = bool(valid and table is not None and metric.table_distance(person['bbox'],table) <= metric.threshold(.08))
            person['near_machine'] = bool(valid and machines and min(metric.anchor_distance(person['bbox'],m) for m in machines) <= metric.threshold(.12))
    return facts
