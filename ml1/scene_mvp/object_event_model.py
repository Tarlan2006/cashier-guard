"""Weak video-supervised object-left event model on saved SAM/geometry observations."""
import math
import numpy as np
from scipy.optimize import minimize
from scipy.special import expit,logsumexp
from scene_mvp.engine import valid_box,validate_profile

FEATURE_NAMES=['reference_retention_times_cashier_separation','stationary_reference_retention_times_separation','reference_retention_times_object_cashier_gap']
SPEC={'version':'object-event-mil/1','supported_kinds':['bag','documents'],'feature_names':FEATURE_NAMES,'window_samples':3,'max_sample_gap_sec':.75,'min_window_span_sec':.8,'max_window_span_sec':1.3,'minimum_joint_coverage':.5,'motion_decay':4.,'regularization':.1,'pool_temperature':5.,'decision_cutoff':.5,'nonnegative_feature_weights':True,'label_unit':'whole_video_weak_label','model_trains_segmentation':False,'score_is_calibrated_probability':False,'legal_verdict':False}

def center(b):return np.array([(b[0]+b[2])/2,(b[1]+b[3])/2],dtype=float)
def overlap(a,b):
    area=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]));union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-area
    return area/union if union>0 else 0.

def extract(observations,profile,spec=SPEC):
    validate_profile(profile)
    if not profile['confirmed'] or profile.get('target_object_kind') not in spec['supported_kinds']:raise ValueError('Confirmed bag/documents profile required; cash is deferred')
    zone=valid_box(profile['zones']['cashier_zone']);reference=valid_box(profile['zones'].get('object_zone',profile['zones'].get('bag_zone')));ids=set(profile['roles']['cashier_ids']);scale=max(1e-6,math.hypot(zone[2]-zone[0],zone[3]-zone[1]));rows=[];previous=None;joint=0;last=-1.
    for raw in observations['timeline']:
        t=raw['timestamp_sec']
        if not math.isfinite(t) or t<=last:raise ValueError('Ordered distinct finite timestamps required')
        last=t;row={'timestamp_sec':t,'feature':None,'reason':'missing_object_or_observed_cashier'};obj=raw.get('experimental_object',raw.get('experimental_bag',{}));people=[p for p in raw.get('persons',[]) if p.get('id') in ids and p.get('role')=='cashier' and p.get('role_source')=='user_confirmed_track' and p.get('observed',True) is not False and not p.get('is_reflection',False)]
        if obj.get('state')=='mask_observed' and obj.get('bbox') is not None and len(people)==1:
            b=valid_box(obj['bbox']);pb=valid_box(people[0]['bbox']);c=center(b);p=center(pb);joint+=1;distance=math.hypot(max(zone[0]-p[0],0,p[0]-zone[2]),max(zone[1]-p[1],0,p[1]-zone[3]))/scale;retention=overlap(b,reference);gap=float(np.linalg.norm(c-p)/scale)
            if previous is not None and t-previous[0]<=spec['max_sample_gap_sec']:
                speed=float(np.linalg.norm(c-previous[1])/scale/(t-previous[0]));v=retention*distance;row.update(feature=[v,v*math.exp(-spec['motion_decay']*speed),v*gap],reason=None)
            else:row['reason']='object_motion_not_yet_observed'
            previous=(t,c)
        else:previous=None
        rows.append(row)
    windows=[];n=spec['window_samples']
    for i in range(n-1,len(rows)):
        group=rows[i-n+1:i+1];span=group[-1]['timestamp_sec']-group[0]['timestamp_sec']
        if any(r['feature'] is None for r in group) or not spec['min_window_span_sec']<=span<=spec['max_window_span_sec']:continue
        if any(group[j+1]['timestamp_sec']-group[j]['timestamp_sec']>spec['max_sample_gap_sec'] for j in range(n-1)):continue
        windows.append({'start_sec':group[0]['timestamp_sec'],'end_sec':group[-1]['timestamp_sec'],'evidence_times_sec':[r['timestamp_sec'] for r in group],'feature':np.mean([r['feature'] for r in group],axis=0).tolist()})
    coverage=joint/len(rows) if rows else 0.
    return {'windows':windows,'frame_features':rows,'joint_observed_coverage':coverage,'total_frames':len(rows),'usable':bool(windows) and coverage>=spec['minimum_joint_coverage'],'unknown_frames':len(rows)-joint,'object_kind':profile['target_object_kind']}

def pooled(logits,temperature):return float((logsumexp(temperature*logits)-math.log(len(logits)))/temperature)

def fit(bags,labels,spec=SPEC):
    xs=[np.asarray(x,dtype=float) for x in bags];y=np.asarray(labels,dtype=float)
    if len(xs)!=len(y) or set(y.tolist())!={0.,1.} or any(x.ndim!=2 or not len(x) or x.shape[1]!=len(FEATURE_NAMES) or not np.isfinite(x).all() for x in xs):raise ValueError('Finite nonempty video bags from two classes required')
    mean=np.mean([x.mean(axis=0) for x in xs],axis=0);scale=np.sqrt(np.mean([np.mean((x-mean)**2,axis=0) for x in xs],axis=0));scale[scale<1e-3]=1.;zs=[(x-mean)/scale for x in xs];weights=np.where(y==1,len(y)/(2*np.count_nonzero(y==1)),len(y)/(2*np.count_nonzero(y==0)));temperature=spec['pool_temperature'];reg=spec['regularization']
    def objective(theta):
        loss=.5*reg*np.dot(theta[:-1],theta[:-1]);gradient=np.r_[reg*theta[:-1],0.]
        for z,label,sample_weight in zip(zs,y,weights):
            logits=z@theta[:-1]+theta[-1];value=pooled(logits,temperature);loss+=sample_weight*(np.logaddexp(0,value)-label*value)/len(y);soft=np.exp(temperature*logits-logsumexp(temperature*logits));residual=sample_weight*(expit(value)-label)/len(y);gradient[:-1]+=residual*(soft@z);gradient[-1]+=residual
        return float(loss),gradient
    bounds=[(0,None)]*len(FEATURE_NAMES)+[(None,None)]
    result=minimize(objective,np.zeros(len(FEATURE_NAMES)+1),jac=True,bounds=bounds,method='L-BFGS-B',options={'maxiter':500,'ftol':1e-10})
    if not result.success:raise RuntimeError('Event model did not converge: '+str(result.message))
    return {'mean':mean,'scale':scale,'weight':result.x[:-1],'bias':np.asarray(result.x[-1]),'temperature':np.asarray(temperature),'iterations':np.asarray(result.nit)}

def predict(model,features,spec=SPEC):
    if not features['usable']:return {'status':'insufficient_observations','prediction':None,'video_risk_score':None,'candidate':None,'legal_violation_label':None}
    windows=features['windows'];x=np.array([w['feature'] for w in windows],dtype=float)
    if not np.isfinite(x).all():raise ValueError('Nonfinite features')
    logits=((x-model['mean'])/model['scale'])@model['weight']+model['bias'];value=pooled(logits,float(model['temperature']));score=float(expit(value));index=int(np.argmax(logits));positive=score>=spec['decision_cutoff'];best=windows[index]
    return {'status':'experimental_prediction','prediction':'object_left_pattern' if positive else 'no_object_left_pattern_detected','video_risk_score':score,'score_is_calibrated_probability':False,'strongest_window':{k:v for k,v in best.items() if k!='feature'},'candidate':{'type':'object_left_during_cashier_departure_model_candidate','start_sec':best['start_sec'],'end_sec':best['end_sec'],'evidence_times_sec':best['evidence_times_sec'],'weak_localization_only':True,'approved_for_rule_engine':False} if positive else None,'window_scores':[float(expit(v)) for v in logits],'legal_violation_label':None,'approved_for_rule_engine':False}
