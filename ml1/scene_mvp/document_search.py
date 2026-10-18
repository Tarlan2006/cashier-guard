"""Camera-specific reference retrieval, not a document-type or absence detector."""
import cv2
import numpy as np

SPEC = {
    'version': 'document-reference-search/2',
    'search_roi': [.12, .36, .68, .61],
    'roi_scope': 'engineer_selected_fixed_camera_work_surface_not_per_video_object_box',
    'scales': [.8, 1., 1.25, 1.5],
    'angles_deg': [-25, 0, 25],
    'edge_weight': .3,
    'proposals_per_template': 3,
    'proposals_per_frame': 3,
    'nms_iou': .25,
    'motion_difference_scale': 25.,
    'stationary_rank_weight': .3,
    'motion_is_presentation_proof': False,
    'preview_spacing_sec': 1.,
    'score_is_probability': False,
    'object_kind_classified': False,
    'absence_decision_allowed': False,
}


def crop_box(image, box):
    if len(box) != 4 or not all(np.isfinite(box)) or not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
        raise ValueError('Invalid normalized box')
    h, w = image.shape[:2]
    x1, y1, x2, y2 = map(round, [box[0]*w, box[1]*h, box[2]*w, box[3]*h])
    result = image[y1:y2, x1:x2]
    if min(result.shape[:2]) < 3:
        raise ValueError('Reference crop too small')
    return result, (x1, y1, x2, y2)


def iou(a, b):
    inter = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1])-inter
    return inter/union if union > 0 else 0.


def templates(reference, spec=SPEC):
    if reference.std() < 3:
        raise ValueError('Reference lacks visible texture')
    result = []
    for scale in spec['scales']:
        h, w = [max(5, round(v*scale)) for v in reference.shape[:2]]
        resized = cv2.resize(reference, (w, h), interpolation=cv2.INTER_LINEAR)
        for angle in spec['angles_deg']:
            matrix = cv2.getRotationMatrix2D(((w-1)/2, (h-1)/2), angle, 1)
            color = cv2.warpAffine(resized, matrix, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
            edges = cv2.Canny(cv2.cvtColor(color, cv2.COLOR_BGR2GRAY), 40, 100)
            if edges.std() < 1:
                continue
            result.append({'color': color, 'edge': edges, 'scale': scale, 'angle': angle})
    if not result:
        raise ValueError('No textured reference templates')
    return result


def search(image, reference_templates, spec=SPEC, neighbors=()):
    surface, (rx, ry, _, _) = crop_box(image, spec['search_roi'])
    edges = cv2.Canny(cv2.cvtColor(surface, cv2.COLOR_BGR2GRAY), 40, 100)
    h, w = image.shape[:2]
    differences = [cv2.absdiff(image, neighbor).mean(axis=2) for neighbor in neighbors if neighbor is not None and neighbor.shape == image.shape]
    difference = np.maximum.reduce(differences) if differences else None
    proposals = []
    for template in reference_templates:
        th, tw = template['color'].shape[:2]
        if th >= surface.shape[0] or tw >= surface.shape[1]:
            continue
        color = cv2.matchTemplate(surface, template['color'], cv2.TM_CCOEFF_NORMED)
        edge = cv2.matchTemplate(edges, template['edge'], cv2.TM_CCOEFF_NORMED)
        weight = spec['edge_weight']
        scores = np.nan_to_num((1-weight)*color+weight*edge, nan=-1., posinf=-1., neginf=-1.)
        for _ in range(spec['proposals_per_template']):
            _, value, _, (x, y) = cv2.minMaxLoc(scores)
            if value <= -1:
                break
            box = [(rx+x)/w, (ry+y)/h, (rx+x+tw)/w, (ry+y+th)/h]
            motion = float(difference[ry+y:ry+y+th, rx+x:rx+x+tw].mean()) if difference is not None else None
            weight = spec['stationary_rank_weight']+(1-spec['stationary_rank_weight'])*min(1.,motion/spec['motion_difference_scale']) if motion is not None else 1.
            proposals.append({'bbox': box, 'reference_similarity': float(value), 'motion_difference': motion, 'rank_score': float(value)*weight,
                              'scale': template['scale'], 'angle_deg': template['angle']})
            scores[max(0, y-th//2):min(scores.shape[0], y+th//2+1), max(0, x-tw//2):min(scores.shape[1], x+tw//2+1)] = -1
    kept = []
    for proposal in sorted(proposals, key=lambda p: -p['rank_score']):
        if all(iou(proposal['bbox'], old['bbox']) < spec['nms_iou'] for old in kept):
            kept.append(proposal)
        if len(kept) >= spec['proposals_per_frame']:
            break
    return kept


def diverse_frames(rows, count=6, spacing_sec=SPEC['preview_spacing_sec']):
    chosen = []
    for row in sorted((r for r in rows if r['proposals']), key=lambda r: -r['proposals'][0].get('rank_score',r['proposals'][0]['reference_similarity'])):
        if all(abs(row['timestamp_sec']-c['timestamp_sec']) >= spacing_sec for c in chosen):
            chosen.append(row)
        if len(chosen) >= count:
            break
    return sorted(chosen, key=lambda r: r['timestamp_sec'])
