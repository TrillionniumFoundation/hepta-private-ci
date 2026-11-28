"""Proper next-spike interval likelihoods with cell-shared parameters and end-of-pulse censoring."""
from dataclasses import dataclass
import math
import numpy as np
from scipy.special import gammaincc, gammaln, log_ndtr


MULTI=('ig2','ig4','ig8')
CONTROLS=('ig1','gamma','lognormal','exponential')
ARMS=(*MULTI,*CONTROLS)
PANELS={'stationary':(.0005,False),'no_deadtime':(0.,False),'elapsed_adaptation':(.0005,True)}


@dataclass
class RiskSet:
    rows: list
    row: np.ndarray
    cells: np.ndarray
    interval: np.ndarray
    event: np.ndarray
    current: np.ndarray
    prev: np.ndarray
    exposure: np.ndarray
    objective_weights: np.ndarray

    @classmethod
    def build(cls, rows):
        row=[];interval=[];event=[];prev=[]
        exposures=np.zeros(len(rows))
        for k,r in enumerate(rows):
            times=np.asarray(r['spikes_s'])
            if not len(times):continue
            end=float(r['duration'])
            exposure=end-times[0];exposures[k]=exposure
            elapsed=np.diff(np.r_[times,end])
            assert np.all(elapsed>0) and abs(elapsed.sum()-exposure)<1e-12
            row.extend([k]*len(times));interval.extend(elapsed)
            event.extend([True]*(len(times)-1)+[False])
            prev.extend(times/end-.5)
        row=np.asarray(row,dtype=int);cells=np.asarray([r['cell'] for r in rows])
        current=np.asarray([r['current'] for r in rows])
        eligible=sorted(set(cells[exposures>0]))
        weights=np.zeros(len(rows))
        for cell in eligible:
            present=cells==cell
            weights[present]=1/(len(eligible)*exposures[present].sum())
        return cls(rows,row,cells,np.asarray(interval),np.asarray(event,bool),np.tanh(current[row]/200),
                   np.asarray(prev),exposures,weights[row])


def log_gamma_survival(k,u):
    x=k*u
    with np.errstate(divide='ignore'):
        value=np.log(gammaincc(k,x))
    tail=~np.isfinite(value)
    if tail.any():
        z=x[tail];total=np.ones_like(z);term=total.copy()
        for i in range(1,65):
            term*= (k-i)/z
            total+=term
            if np.all(np.abs(term)<=1e-15*np.abs(total)):break
        assert np.all(total>0)
        value[tail]=(k-1)*np.log(z)-z-gammaln(k)+np.log(total)
    return value


def standardized(arm,k,u):
    """Return log density and log survival in a common dimensionless clock for positive waiting times."""
    logs=np.log(u)
    if arm.startswith('ig'):
        n=int(arm[2:])
        root=np.sqrt(k/u)
        a=log_ndtr((1-u)*root)
        b=2*k+log_ndtr(-(1+u)*root)
        # Reflection gives S = Phi(A) - exp(2k) Phi(B); expm1 avoids cancellation in the right tail.
        if np.any(b>=a):
            # At very early times A is large and b very negative. Equality can only occur
            # at flow limits beyond reliable subtraction; reject that parameter state explicitly.
            raise FloatingPointError('inverse Gaussian survival log terms have numerically crossed')
        single_sf=a+np.log(-np.expm1(b-a))
        single_pdf=.5*(np.log(k)-math.log(2*math.pi)-3*logs)-k*(u-1)**2/(2*u)
        return math.log(n)+single_pdf+(n-1)*single_sf,n*single_sf
    if arm=='gamma':
        return k*np.log(k)-gammaln(k)+(k-1)*logs-k*u,log_gamma_survival(k,u)
    if arm=='lognormal':
        sd=1/math.sqrt(k);z=(logs+sd**2/2)/sd
        return -logs-np.log(sd)-math.log(2*math.pi)/2-z*z/2,log_ndtr(-z)
    if arm=='exponential':
        return -u,-u
    raise ValueError(arm)


def contributions(data,arm,params,panel):
    dead,adapt=PANELS[panel]
    logtau=params[0]+params[1]*data.current
    if adapt:logtau=logtau+params[-1]*data.prev
    shape=1. if arm=='exponential' else math.exp(params[2])
    active=data.interval>dead
    if np.any(data.event & ~active):
        raise ValueError('observed interval is inside absolute dead time')
    answer=np.zeros(len(data.row))
    if np.any(active):
        u=(data.interval[active]-dead)*np.exp(-logtau[active])
        pdf,sf=standardized(arm,shape,u)
        answer[active]=np.where(data.event[active],pdf-logtau[active],sf)
    if not np.isfinite(answer).all():raise FloatingPointError('nonfinite interval log likelihood')
    return answer


def score(data,arm,params,panel):
    v=contributions(data,arm,params,panel)
    return -float(data.objective_weights@v)


def starts_and_bounds(arm,panel):
    adapt=PANELS[panel][1]
    common=[(-6.5,0.),(-2.,2.)]
    extra=[(-2.,2.)] if adapt else []
    if arm=='exponential':return [[math.log(.035),-.5]+([0.] if adapt else [])],common+extra
    return [[math.log(.035),-.5,k]+([0.] if adapt else []) for k in (-1.4,0.,1.6)],common+[(-3.5,5.)]+extra
