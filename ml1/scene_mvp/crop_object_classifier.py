"""Small supervised crop head on frozen local visual features."""
import numpy as np
from scipy.optimize import minimize
from scipy.special import softmax,logsumexp

SPEC={'version':'human-object-crop-classifier/1','classes':['banknotes','card','other'],'regularization':.01,
      'minimum_top_score':.55,'minimum_top_margin':.10,'score_is_calibrated_probability':False,
      'input_is_already_localized_crop':True,'identity_document_semantics_supported':False,'automatic_violation_verdict':False}


def weights(rows):
    present={r['object_kind'] for r in rows}
    if present!=set(SPEC['classes']):raise ValueError('All target classes must occur in training')
    result=[]
    for row in rows:
        same_class=[r for r in rows if r['object_kind']==row['object_kind']]
        videos={r['video_sha256'] for r in same_class};same_video=[r for r in same_class if r['video_sha256']==row['video_sha256']]
        frames={r['image_sha256'] for r in same_video};views=sum(r['image_sha256']==row['image_sha256'] for r in same_video)
        result.append(1/(len(present)*len(videos)*len(frames)*views))
    values=np.asarray(result,float);return values/values.sum()


def fit(x,rows):
    x=np.asarray(x,float)
    if x.ndim!=2 or len(x)!=len(rows) or not np.isfinite(x).all():raise ValueError('Finite matching training features required')
    k=len(SPEC['classes']);y=np.array([SPEC['classes'].index(r['object_kind']) for r in rows]);sample_weight=weights(rows)
    mean=x.mean(axis=0);z=x-mean;dimension=x.shape[1]
    def objective(theta):
        w=theta[:dimension*k].reshape(dimension,k);bias=theta[dimension*k:];logits=z@w+bias
        loss=np.dot(sample_weight,logsumexp(logits,axis=1)-logits[np.arange(len(y)),y])+.5*SPEC['regularization']*np.sum(w*w)
        residual=softmax(logits,axis=1);residual[np.arange(len(y)),y]-=1;residual*=sample_weight[:,None]
        return float(loss),np.r_[(z.T@residual+SPEC['regularization']*w).ravel(),residual.sum(axis=0)]
    result=minimize(objective,np.zeros((dimension+1)*k),jac=True,method='L-BFGS-B',options={'maxiter':300,'ftol':1e-10})
    if not result.success:raise RuntimeError('Crop classifier fit failed: '+str(result.message))
    return {'mean':mean,'weight':result.x[:dimension*k].reshape(dimension,k),'bias':result.x[dimension*k:]}


def predict(model,x):
    x=np.asarray(x,float)
    if not np.isfinite(x).all():raise ValueError('Finite features required')
    values=softmax((x-model['mean'])@model['weight']+model['bias'],axis=1);result=[]
    for row in values:
        order=np.argsort(row)[::-1];top=int(order[0]);margin=float(row[top]-row[order[1]])
        result.append({'top_class':SPEC['classes'][top],'decision':SPEC['classes'][top] if row[top]>=SPEC['minimum_top_score'] and margin>=SPEC['minimum_top_margin'] else 'unclear',
                       'top_score_uncalibrated':float(row[top]),'margin_uncalibrated':margin,'scores_uncalibrated':row.tolist()})
    return result
