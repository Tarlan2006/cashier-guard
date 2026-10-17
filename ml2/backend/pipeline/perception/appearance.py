"""Coarse clothing color only. The top 35% of each box is never sampled."""

import cv2
import numpy as np


def clothing_histogram(image: np.ndarray, bbox: list[float]) -> list[float] | None:
    height, width = image.shape[:2]
    x1, y1, x2, y2 = np.asarray(bbox) * [width, height, width, height]
    left, right = round(x1 + 0.20 * (x2 - x1)), round(x2 - 0.20 * (x2 - x1))
    top, bottom = round(y1 + 0.35 * (y2 - y1)), round(y1 + 0.88 * (y2 - y1))
    crop = image[max(0, top) : min(height, bottom), max(0, left) : min(width, right)]
    if crop.size < 30:
        return None
    hsv = cv2.cvtColor(cv2.resize(crop, (24, 32)), cv2.COLOR_BGR2HSV)
    hs = cv2.calcHist([hsv], [0, 1], None, [8, 4], [0, 180, 0, 256]).ravel()
    value = cv2.calcHist([hsv], [2], None, [16], [0, 256]).ravel()
    value = cv2.GaussianBlur(value[:, None], (1, 3), 0.8).ravel()
    feature = np.r_[0.5 * hs / max(hs.sum(), 1), 0.5 * value / max(value.sum(), 1)]
    return feature.astype(float).round(6).tolist()


def color_distance(first, second) -> float | None:
    if first is None or second is None:
        return None
    a, b = np.asarray(first, float), np.asarray(second, float)
    if a.shape != b.shape or a.size == 0:
        return None
    a = a / max(a.sum(), 1e-9)
    b = b / max(b.sum(), 1e-9)
    return float(np.sqrt(max(0.0, 1.0 - np.sqrt(a * b).sum())))
