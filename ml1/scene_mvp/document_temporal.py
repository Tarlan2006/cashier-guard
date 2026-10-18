"""Geometry/appearance candidate association; object identity remains unverified."""
import math
import numpy as np
from scipy.optimize import linear_sum_assignment

SPEC={'version':'document-candidate-temporal/1','max_gap_sec':.75,'max_center_distance_in_box_diagonals':1.25,
      'max_area_ratio':2.5,'max_histogram_distance':.55,'minimum_stable_observations':3,'minimum_stable_span_sec':.8,
      'isolated_candidates_are_not_deleted':True,'track_does_not_establish_object_identity':True,
      'document_absence_decision_allowed':False}


def pair_cost(previous,current,spec=SPEC):
    a=np.asarray(previous.get('association_box_px',previous['bbox']),float);b=np.asarray(current.get('association_box_px',current['bbox']),float)
    size=a[2:]-a[:2];other=b[2:]-b[:2]
    if np.any(size<=0) or np.any(other<=0):return None
    area=float(np.prod(size));new_area=float(np.prod(other))
    ratio=max(area/new_area,new_area/area)
    distance=float(np.linalg.norm((a[:2]+a[2:]-b[:2]-b[2:])/2)/max(np.linalg.norm(size),1e-9))
    hist1=np.asarray(previous['appearance'],float);hist2=np.asarray(current['appearance'],float)
    appearance=float(np.sqrt(max(0,1-np.sum(np.sqrt(hist1*hist2)))))
    if ratio>spec['max_area_ratio'] or distance>spec['max_center_distance_in_box_diagonals'] or appearance>spec['max_histogram_distance']:return None
    return distance/spec['max_center_distance_in_box_diagonals']+appearance+.1*math.log(ratio)


def associate(rows,spec=SPEC):
    tracks=[];annotated=[];last_time=-1
    for row in rows:
        t=float(row['timestamp_sec'])
        if t<=last_time:raise ValueError('Strictly increasing timestamps required')
        last_time=t;active=[tr for tr in tracks if 0<t-tr['samples'][-1]['timestamp_sec']<=spec['max_gap_sec']]
        current=[dict(p) for p in row['proposals'] if p['selection_state']=='retained_candidate']
        assigned={}
        if active and current:
            costs=np.full((len(active),len(current)),1e6)
            for i,tr in enumerate(active):
                for j,p in enumerate(current):
                    cost=pair_cost(tr['samples'][-1],p,spec)
                    if cost is not None:costs[i,j]=cost
            ii,jj=linear_sum_assignment(costs)
            assigned={int(j):active[int(i)] for i,j in zip(ii,jj) if costs[i,j]<1e6}
        links=[]
        for j,p in enumerate(current):
            tr=assigned.get(j)
            if tr is None:
                tr={'track_id':len(tracks)+1,'samples':[]};tracks.append(tr)
            sample={**p,'timestamp_sec':t,'track_id':tr['track_id'],'object_identity_established':False}
            tr['samples'].append(sample)
            links.append({'proposal_index':p['proposal_index'],'track_id':tr['track_id']})
        annotated.append({'timestamp_sec':t,'candidate_tracks':links})
    for tr in tracks:
        samples=tr['samples'];span=samples[-1]['timestamp_sec']-samples[0]['timestamp_sec']
        tr.update(start_sec=samples[0]['timestamp_sec'],end_sec=samples[-1]['timestamp_sec'],observations=len(samples),
                  priority='repeated_candidate' if len(samples)>=spec['minimum_stable_observations'] and span>=spec['minimum_stable_span_sec'] else 'short_candidate_needs_review',
                  object_identity_established=False,document_type_verified=False)
    return {'tracks':tracks,'timeline':annotated,'absence_detection_validated':False}
