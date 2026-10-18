"""Coordinate transforms for a human-region crop; no new pixels or object labels."""
import math
from scene_mvp.engine import valid_box


def focus_bounds(zones,width,height,padding=.04):
    boxes=[valid_box(zones[k]) for k in ['machine_zone','safe_zone','cash_seed']]
    return [max(0,math.floor((min(b[0] for b in boxes)-padding)*width)),
            max(0,math.floor((min(b[1] for b in boxes)-padding)*height)),
            min(width,math.ceil((max(b[2] for b in boxes)+padding)*width)),
            min(height,math.ceil((max(b[3] for b in boxes)+padding)*height))]


def local_box(normalized,roi,width,height):
    valid_box(normalized);x1,y1,x2,y2=roi
    result=[normalized[0]*width-x1,normalized[1]*height-y1,normalized[2]*width-x1,normalized[3]*height-y1]
    if not 0<=result[0]<result[2]<=x2-x1 or not 0<=result[1]<result[3]<=y2-y1:raise ValueError('Cash seed outside focus crop')
    return result
