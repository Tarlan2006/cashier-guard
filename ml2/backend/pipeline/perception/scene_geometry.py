"""Scene-relative desk/workplace hypotheses; no video IDs or pixel polygons."""

import numpy as np


def center(box, scale=None):
    b = np.asarray(box, float)
    point = (b[:2] + b[2:]) / 2
    return point if scale is None else point * scale


def desk_box(facts: dict) -> list[float] | None:
    anchors = [
        np.asarray(o["bbox"], float)
        for o in facts.get("fixtures", [])
        if o["class"] in {"counter_machine", "laptop"}
    ]
    tables = []
    for frame in facts["frames"]:
        for obj in frame.get("objects", []):
            if obj.get("coco_class", obj["class"]) in {"diningtable", "dining table"}:
                b = np.asarray(obj["bbox"], float)
                area = float(np.prod(b[2:] - b[:2]))
                if 0.08 <= area <= 0.65 and any(
                    np.all(center(a) >= b[:2]) and np.all(center(a) <= b[2:])
                    for a in anchors
                ):
                    tables.append(b)
    if tables:
        return np.median(tables, axis=0).round(6).tolist()
    if not anchors:
        return None
    b = np.r_[
        np.min([a[:2] for a in anchors], axis=0),
        np.max([a[2:] for a in anchors], axis=0),
    ]
    padding = np.maximum((b[2:] - b[:2]) * 0.25, [0.06, 0.06])
    return (
        np.r_[np.maximum(0, b[:2] - padding), np.minimum(1, b[2:] + padding)]
        .round(6)
        .tolist()
    )


def distance_to_box(point, box, scale) -> float:
    b = np.asarray(box, float)
    delta = np.maximum(np.maximum(b[:2] - point, point - b[2:]), 0) * scale
    return float(np.linalg.norm(delta))
