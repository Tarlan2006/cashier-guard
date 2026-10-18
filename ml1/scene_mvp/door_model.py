"""Small CPU door-state baseline: HOG + regularized balanced logistic regression.
Scores are NOT calibrated probabilities. No inference result is a legal verdict.
"""
import numpy as np
from scipy.optimize import minimize
from scipy.special import expit
import cv2

FEATURE_SPEC={'kind':'HOG_numpy_unsigned_2x2_blocks','resize':[64,64],'block':[16,16],'stride':[8,8],'cell':[8,8],'bins':9,'regularization':.01,'score_cutoff':.65}

def feature(image_bgr):
 if image_bgr is None or image_bgr.size==0:raise ValueError('Empty door crop')
 gray=cv2.cvtColor(image_bgr,cv2.COLOR_BGR2GRAY) if image_bgr.ndim==3 else image_bgr
 gray=cv2.resize(gray,(64,64),interpolation=cv2.INTER_AREA)
 # Portable unsigned HOG; no optional OpenCV objdetect module required.
 gy,gx=np.gradient(gray.astype(np.float64));magnitude=np.hypot(gx,gy);angle=(np.arctan2(gy,gx)%np.pi)*9/np.pi
 lower=np.floor(angle).astype(int)%9;fraction=angle-np.floor(angle);yy,xx=np.indices(gray.shape);hist=np.zeros((8,8,9),dtype=np.float64)
 np.add.at(hist,(yy//8,xx//8,lower),magnitude*(1-fraction))
 np.add.at(hist,(yy//8,xx//8,(lower+1)%9),magnitude*fraction)
 blocks=[]
 for y in range(7):
  for x in range(7):
   block=hist[y:y+2,x:x+2].ravel();block=block/np.sqrt(np.dot(block,block)+1e-6);block=np.minimum(block,.2);block=block/np.sqrt(np.dot(block,block)+1e-6);blocks.append(block)
 return np.concatenate(blocks)

def fit(x,y):
 x=np.asarray(x,dtype=np.float64);y=np.asarray(y,dtype=np.float64)
 if x.ndim!=2 or len(x)!=len(y) or not np.isfinite(x).all() or set(y.tolist())!={0.,1.}:raise ValueError('Two labeled classes with finite features required')
 mean=x.mean(axis=0);scale=x.std(axis=0);scale[scale<1e-3]=1.;z=(x-mean)/scale
 sample_weight=np.where(y==1,len(y)/(2*(y==1).sum()),len(y)/(2*(y==0).sum()));reg=FEATURE_SPEC['regularization']
 def objective(theta):
  logits=z@theta[:-1]+theta[-1];loss=np.mean(sample_weight*(np.logaddexp(0,logits)-y*logits))+.5*reg*np.dot(theta[:-1],theta[:-1]);residual=sample_weight*(expit(logits)-y)/len(y)
  return loss,np.r_[z.T@residual+reg*theta[:-1],residual.sum()]
 result=minimize(objective,np.zeros(x.shape[1]+1),jac=True,method='L-BFGS-B',options={'maxiter':200,'ftol':1e-9})
 if not result.success:raise RuntimeError('Door fit failed to converge')
 return {'mean':mean,'scale':scale,'weight':result.x[:-1],'bias':np.asarray(result.x[-1]),'iterations':int(result.nit)}

def score(model,x):
 x=np.asarray(x,dtype=np.float64)
 if not np.isfinite(x).all():raise ValueError('Nonfinite features')
 return expit(((x-model['mean'])/model['scale'])@model['weight']+model['bias'])

def classify(scores):
 cutoff=FEATURE_SPEC['score_cutoff'];return ['open' if s>=cutoff else 'closed' if s<=1-cutoff else 'unknown' for s in scores]

def metrics(expected,predicted):
 if len(expected)!=len(predicted) or not len(expected):raise ValueError('Nonempty equal-length results required')
 states=['closed','open','unknown'];confusion={state:{p:sum(a==state and b==p for a,b in zip(expected,predicted)) for p in states} for state in ['closed','open']}
 recalls={state:confusion[state][state]/sum(confusion[state].values()) if sum(confusion[state].values()) else None for state in ['closed','open']}
 known=sum(p!='unknown' for p in predicted);correct=sum(a==b for a,b in zip(expected,predicted))
 return {'frames':len(expected),'correct':correct,'accuracy_with_unknown_as_unmatched':correct/len(expected),'coverage':known/len(expected),'unknown':len(expected)-known,'precision_on_answered':correct/known if known else None,'recall':recalls,'balanced_accuracy':sum(recalls.values())/2 if all(v is not None for v in recalls.values()) else None,'false_open_frames':confusion['closed']['open'],'missed_open_frames':confusion['open']['closed'],'unclear_open_frames':confusion['open']['unknown'],'always_closed_baseline':sum(s=='closed' for s in expected)/len(expected),'confusion':confusion}
