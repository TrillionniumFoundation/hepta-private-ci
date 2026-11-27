"""Opt-in post-transport inverse-temperature calibration, never a default change.

Only NLL fitting consumes labels. Serving consumes raw policies, commands and a
model-bound pair of positive inverse temperatures. It calibrates the actual prior
CDF marginals, then forms maximal semantic coupling. Exact positive powers preserve
support/ranking; numerical support or argmax changes reject, never silently fallback.
No claim to preserve original marginal probabilities or joint correctness follows.
"""
from dataclasses import dataclass
import hashlib,json,math
import numpy as np
from control import _canonical
from normalized import NormalizedCouplingProfile,MODE as BASE_MODE,precision,apply_batch as base_apply

MODE='post-transport-positive-inverse-temperature-v1'
SCHEMA='rgb-post-transport-temperature-profile-v1'
LOWER=1/8
UPPER=8.
STEPS=24
EVALUATIONS=28


def _inputs(probability,labels=None):
    precision();p=np.asarray(probability,dtype=np.longdouble)
    if (p.ndim!=2 or p.shape[1]!=12 or not 1<=len(p)<=65536 or not np.isfinite(p).all()
            or np.any(p<0) or np.any(np.abs(p.sum(1)-1)>1e-10)):raise ValueError('bounded normalized finite semantic marginals')
    support=p>0
    if np.any(~support.any(1)):raise ValueError('nonempty support')
    logs=np.zeros_like(p);np.log(p,out=logs,where=support)
    maximum=np.max(np.where(support,logs,-np.inf),axis=1,keepdims=True)
    y=None
    if labels is not None:
        y=np.asarray(labels)
        if y.shape!=(len(p),) or y.dtype.kind not in 'iu' or np.any(y<0) or np.any(y>=12) or np.any(~support[np.arange(len(p)),y]):
            raise ValueError('fixed supported target indices')
    return p,support,logs,maximum,y


def _temperature(value):
    if type(value) not in (int,float) or not math.isfinite(value) or not LOWER<=value<=UPPER:raise ValueError('explicit positive bounded inverse temperature')
    return float(value)


def _power(prepared,tau):
    tau=_temperature(tau);p,support,logs,maximum,y=prepared
    e=np.zeros_like(p);np.exp(np.longdouble(tau)*(logs-maximum),out=e,where=support)
    total=e.sum(1,keepdims=True);q=e/total
    if not np.isfinite(q).all() or np.any((q>0)!=support):raise ValueError('power support unresolved; no fallback')
    return q,total


def _stats(prepared,inverse_temperature):
    p,support,logs,maximum,y=prepared;q,z=_power(prepared,inverse_temperature)
    centered=logs-maximum
    nll=np.log(z[:,0])-np.longdouble(inverse_temperature)*centered[np.arange(len(p)),y]
    mean=np.sum(q*centered,axis=1)
    gradient=mean-centered[np.arange(len(p)),y]
    hessian=np.sum(q*(centered-mean[:,None])**2,axis=1)
    return dict(nll=float(nll.mean()),gradient=float(gradient.mean()),hessian=float(hessian.mean()))


def nll_stats(probability,labels,inverse_temperature):
    return _stats(_inputs(probability,labels),inverse_temperature)


def fit_inverse_temperature(probability,labels):
    """Fixed convex NLL root search on FIT input only; all28 evaluations charged.

The prospective [1/8,8] interval is an engineering calibration bound,not tuned from
validation. Every call evaluates baseline,bothends,24bisection steps andchosenpoint,
even for a boundary or flat optimum. No validation-based choice or model updates.
"""
    prepared=_inputs(probability,labels);p,support,logs,maximum,y=prepared
    calls=0
    def stats(tau):
        nonlocal calls;calls+=1
        return _stats(prepared,tau)
    baseline=stats(1.);left=stats(LOWER);right=stats(UPPER);lo,hi=LOWER,UPPER
    flat=bool(np.all(np.max(np.where(support,p,-np.inf),1)==np.min(np.where(support,p,np.inf),1)))
    for _ in range(STEPS):
        mid=(lo+hi)/2;value=stats(mid)
        if value['gradient']<0:lo=mid
        else:hi=mid
    if flat:tau,status=1.,'flat_identity'
    elif left['gradient']>=0:tau,status=LOWER,'lower_boundary'
    elif right['gradient']<=0:tau,status=UPPER,'upper_boundary'
    else:tau,status=(lo+hi)/2,'interior_bisection'
    chosen=stats(tau)
    if calls!=EVALUATIONS or chosen['nll']>baseline['nll']+1e-10:raise ValueError('fixed FIT convex optimization check failed')
    return dict(inverse_temperature=tau,status=status,evaluations=calls,rows=len(p),baseline=baseline,chosen=chosen,interval=[LOWER,UPPER],bisection_steps=STEPS)


@dataclass(frozen=True)
class TemperatureProfile:
    base: NormalizedCouplingProfile
    text_inverse_temperature: float
    image_inverse_temperature: float
    mode: str
    def __post_init__(self):
        if type(self.base) is not NormalizedCouplingProfile or self.mode!=MODE:raise ValueError('explicit bound temperature profile')
        _temperature(self.text_inverse_temperature);_temperature(self.image_inverse_temperature)
    def metadata(self):
        return dict(schema=SCHEMA,mode=self.mode,base_profile=json.loads(self.base.dumps()),
                    text_inverse_temperature=float(self.text_inverse_temperature).hex(),image_inverse_temperature=float(self.image_inverse_temperature).hex(),interval=[LOWER,UPPER])
    @property
    def key(self):return hashlib.sha256(_canonical(self.metadata()).encode()).hexdigest()
    def dumps(self):return _canonical(dict(profile=self.metadata(),profile_key=self.key))
    @classmethod
    def loads(cls,payload,*,expected_model_sha256,expected_mode):
        if type(payload) is not str or len(payload.encode())>131072:raise ValueError('bounded explicit temperature document')
        def unique(pairs):
            out={}
            for k,v in pairs:
                if k in out:raise ValueError('duplicate field')
                out[k]=v
            return out
        obj=json.loads(payload,object_pairs_hook=unique)
        if type(obj) is not dict or set(obj)!={'profile','profile_key'}:raise ValueError('exact temperature envelope')
        p=obj['profile']
        if (type(p) is not dict or set(p)!={'schema','mode','base_profile','text_inverse_temperature','image_inverse_temperature','interval'}
                or p['schema']!=SCHEMA or expected_mode!=MODE or p['mode']!=expected_mode or p['interval']!=[LOWER,UPPER]
                or type(p['text_inverse_temperature']) is not str or type(p['image_inverse_temperature']) is not str):raise ValueError('explicit temperature schema/mode')
        base=NormalizedCouplingProfile.loads(_canonical(p['base_profile']),expected_model_sha256=expected_model_sha256,expected_mode=BASE_MODE)
        result=cls(base,float.fromhex(p['text_inverse_temperature']),float.fromhex(p['image_inverse_temperature']),expected_mode)
        if obj['profile_key']!=result.key:raise ValueError('altered temperature identity')
        return result


def calibrate_marginals(profile,text,image):
    if type(profile) is not TemperatureProfile:raise ValueError('explicit profile')
    a,_=_power(_inputs(text),profile.text_inverse_temperature);b,_=_power(_inputs(image),profile.image_inverse_temperature)
    return a,b


def apply_batch(profile,p,q,commands,*,observed_model_sha256):
    if type(profile) is not TemperatureProfile:raise ValueError('explicit calibrated profile, not old envelope')
    base=base_apply(profile.base,p,q,commands,observed_model_sha256=observed_model_sha256)
    base_joint=base['joint']/base['cdf_total'][:,None,None]
    original_a=base_joint.sum(2);original_b=base_joint.sum(1)
    a,b=calibrate_marginals(profile,original_a,original_b)
    ts=profile.base.transport.base.text_semantics;ims=profile.base.transport.base.image_semantics;matching=np.argsort(ims)[np.asarray(ts)]
    aligned_b=b[:,matching];diag=np.minimum(a,aligned_b);left=a-diag;right=aligned_b-diag
    ra=left.sum(1);rb=right.sum(1);active=(ra>0)&(rb>0)
    joint=np.zeros((len(a),12,12),dtype=np.longdouble)
    np.divide(left[:,:,None]*right[:,None,:],ra[:,None,None],out=joint,where=active[:,None,None])
    joint[:,np.arange(12),np.arange(12)]+=diag;total=joint.sum((1,2))
    if (np.any(total<=0) or np.any(np.abs(joint.sum(2)-a)>1e-12) or np.any(np.abs(joint.sum(1)-aligned_b)>1e-12)):
        raise ValueError('calibrated raw coupling marginals; no repair')
    table=np.empty_like(joint,dtype=float);table[:,:,matching]=(joint/total[:,None,None]).astype(float)
    cdf=np.asarray([math.fsum(x.ravel().tolist()) for x in table]);actual=table/cdf[:,None,None]
    final_a=actual.sum(2);final_b=actual.sum(1)
    if (not np.isfinite(actual).all() or np.any(actual<0) or np.any(np.abs(final_a-a)>1e-12) or np.any(np.abs(final_b-b)>1e-12)
            or not np.array_equal(final_a>0,original_a>0) or not np.array_equal(final_b>0,original_b>0)
            or not np.array_equal(final_a.argmax(1),original_a.argmax(1)) or not np.array_equal(final_b.argmax(1),original_b.argmax(1))):
        raise ValueError('calibrated CDF support/argmax/marginal guard; no fallback')
    return dict(text=final_a,image=final_b,joint=table,cdf_total=cdf,profile_key=profile.key,commands=base['commands'],implementation=MODE)
