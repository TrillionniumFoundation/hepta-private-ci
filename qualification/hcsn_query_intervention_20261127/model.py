"""FP32 conditional first-spike messages. Model time 0.25 per observed 2-ms bin."""
import numpy as np
from scipy.optimize import minimize
from scipy.signal import lfilter
from scipy.special import expit, logit, ndtr
from hx_reference import Parameters, StationaryFirm

HORIZONS = (1, 2, 4, 6, 8)
SUPERVISED = (1, 4, 8)
NEW = (2, 6)
FOLD = {'train': (100,12990), 'dev': (13100,15490), 'test': (15600,18990)}
GRID = np.linspace(.015, 1.30, 12)
CUTS = np.r_[0, (GRID[1:]+GRID[:-1])/2, np.inf]
DT, SIGMA, MU = .25, .23, .03355
SCALES, PENALTIES = (.35,.70,1.40), (.1,1.,10.)
EPS = 1e-7

def inputs(curr):
    """The current in bin t is part of the preprogrammed pulse provided for t."""
    x=np.asarray(curr,dtype=float)
    if x.ndim==1: x=x[:,None]
    lo,hi=FOLD['train']
    standardized=(x-x[lo:hi].mean(0))/np.maximum(x[lo:hi].std(0),1e-8)
    filters=[standardized]
    for tau in (2,6,16,40,100):
        a=np.exp(-2/tau)
        filters.append(lfilter([1-a],[1,-a],standardized,axis=0))
    # A known current waveform supplies a causal drive with both fast and slow parts.
    drive=(.50*filters[0]+.35*filters[2]+.15*filters[3]).mean(1)
    xx=np.column_stack(filters)
    z=(xx-xx[lo:hi].mean(0))/np.maximum(xx[lo:hi].std(0),1e-7)
    hazard_features=np.column_stack([z,np.tanh(z),np.minimum(z*z,36.)])
    return np.tanh(drive),hazard_features,standardized

def boundary(u, law):
    """Vectorized numerical interpolation of Eq. 12 over bounded log-intensity."""
    xs=np.linspace(-1,1,1001)
    fn=lambda t: np.log(StationaryFirm(Parameters(),np.exp(1.5*t)).boundary_closed())
    base=fn(0)
    if law=='fixed':return np.zeros_like(u)
    if law=='tangent':return (fn(1e-5)-fn(-1e-5))/(2e-5)*u
    if law!='literal':raise ValueError(law)
    values=np.array([fn(v)-base for v in xs])
    return np.interp(u,xs,values)

def kernel(start, drift):
    """Substochastic killed transition; rows integrate survival mass in bins."""
    x=np.maximum(start,0)[...,None]
    m=drift[:,None,None]
    sd=SIGMA*np.sqrt(DT)
    image=np.exp(-2*m*x/SIGMA**2)
    n1=ndtr((CUTS-x-m*DT)/sd);n2=ndtr((CUTS+x-m*DT)/sd)
    # Difference of bin masses avoids subtracting two huge CDFs for large image weights.
    q=np.diff(n1,axis=-1)-image*np.diff(n2,axis=-1)
    if q.min() < -2e-12:raise ArithmeticError(float(q.min()))
    return np.maximum(q,0)

def kernels(u, law, scale):
    b=boundary(u,law)
    shift=np.r_[0,b[:-1]-b[1:]]
    d=MU-scale*.25*u
    mat=kernel(GRID[None,:]+shift[:,None],d)
    flat=kernel(np.broadcast_to(GRID,(len(u),len(GRID))),d)
    return b,mat,flat

def reset_vector():
    reset=np.zeros(len(GRID));j=np.searchsorted(GRID,.30)
    right=(.30-GRID[j-1])/(GRID[j]-GRID[j-1])
    reset[j-1],reset[j]=1-right,right
    return reset

def trace(mat):
    """At anchor t use only population state through the end of t-1."""
    n,h,_=mat.shape;r=reset_vector();a=r.copy();f=0.
    states=np.empty((n,h+1));maxerr=0.
    for t in range(n):
        states[t,:h]=a;states[t,h]=f
        survived=a@mat[t]
        fired=a.sum()-survived.sum()
        a=survived+f*r;f=max(fired,0.)
        maxerr=max(maxerr,abs(a.sum()+f-1))
    return states,maxerr

def query(mat,states,flat=None):
    """Probability of >=1 hit. Include an initial refractory release once."""
    n=len(states)-max(HORIZONS);h=mat.shape[1];r=reset_vector()
    idx=np.arange(n);a=states[:n,:h].copy()
    out={};step_flat=None if flat is None else flat[np.maximum(idx-1,0)]
    for j in range(1,max(HORIZONS)+1):
        trans=mat[j-1:j-1+n] if step_flat is None else step_flat
        a=np.einsum('ti,tij->tj',a,trans)
        if j==1:a+=states[:n,-1,None]*r
        if j in HORIZONS:out[j]=np.clip(1-a.sum(axis=1),0,1)
    return out

def target(y, anchors, horizons):
    sums=np.vstack([np.zeros((1,y.shape[1]),dtype=np.int32),np.cumsum(y,axis=0,dtype=np.int32)])
    return np.stack([(sums[anchors+h]-sums[anchors]>0).mean(axis=1) for h in horizons],axis=1)

def design(raw, anchors, horizons):
    return np.stack([np.column_stack([logit(np.clip(raw[h][anchors],EPS,1-EPS)),np.full(len(anchors),np.log(h))]) for h in horizons],axis=1).reshape(-1,2)

def logistic(x,y,penalty):
    mean=x.mean(0);std=np.maximum(x.std(0),1e-7);z=(x-mean)/std;y=np.asarray(y).ravel()
    def obj(w):
        eta=z@w[1:]+w[0];res=expit(eta)-y
        val=np.logaddexp(0,eta).sum()-y@eta+.5*penalty*(w[1:]@w[1:])
        grad=np.r_[res.sum(),z.T@res+penalty*w[1:]]
        return val,grad
    result=minimize(obj,np.zeros(z.shape[1]+1),jac=True,method='L-BFGS-B',options={'maxiter':500,'ftol':5e-13,'gtol':1e-7})
    if not result.success:raise ArithmeticError(result.message)
    return dict(mean=mean.tolist(),std=std.tolist(),w=result.x.tolist())

def predict(fit,x):
    w=np.array(fit['w'])
    return expit((x-fit['mean'])/fit['std']@w[1:]+w[0])

def score(prob,y):
    p=np.clip(prob.astype(np.float32).astype(float),EPS,1-EPS)
    return -(y*np.log(p)+(1-y)*np.log1p(-p)),y*(1-p)**2+(1-y)*p**2

def time_anchors(fold):
    lo,hi=FOLD[fold]
    return np.arange(lo,hi)
