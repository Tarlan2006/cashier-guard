"""Rank SAM masks only after checking explicit human pixel constraints."""
import math

def choose_point_consistent(scores,checks):
    if len(scores)!=len(checks):raise ValueError('Candidate lengths differ')
    valid=[i for i,(score,row) in enumerate(zip(scores,checks)) if row and all(row) and math.isfinite(float(score))]
    return max(valid,key=lambda i:float(scores[i])) if valid else None
