"""New fixed-temperature smooth loss graph; no old/default serving modification.

Strictly positive normalized raw policies -> fixed command transport -> positive
power on fixed structural support -> maximal coupling/CDF-normalized utility.
No derivative through rounded instructions or refitted FIT temperatures.
"""
from dataclasses import dataclass
import hashlib,json,math
import numpy as np
from control import Command,_canonical
from calibration import TemperatureProfile,MODE as TEMPERATURE_MODE
from normalized import precision,NumericalDomainError,RESIDUAL_FLOOR,RELATIVE_BALANCE_TOL
from aligned import push_policies,_maps
from utility import _probabilities
MODE='fixed-temperature-support-coupling-smooth-v1'
LOSS_SCHEMA='rgb-fixed-temperature-support-coupling-loss-v1'

@dataclass(frozen=True)
class FixedTemperatureLossProfile:
    temperature:TemperatureProfile
    mode:str
    def __post_init__(self):
        if type(self.temperature) is not TemperatureProfile or self.mode!=MODE:raise ValueError('explicit fixed-temperature loss profile')
        precision()
    def metadata(self):return dict(schema=LOSS_SCHEMA,mode=self.mode,temperature=json.loads(self.temperature.dumps()),precision=precision(),rho=[0.,1.5],structural_support='exact fixed destination image; zeros never filled',residual_floor=float(RESIDUAL_FLOOR),relative_balance=float(RELATIVE_BALANCE_TOL))
    @property
    def key(self):return hashlib.sha256(_canonical(self.metadata()).encode()).hexdigest()
    def dumps(self):return _canonical(dict(loss=self.metadata(),loss_key=self.key))
    @classmethod
    def loads(cls,payload,*,expected_model_sha256,expected_mode):
        if type(payload) is not str or len(payload.encode())>131072:raise ValueError('bounded loss document')
        def unique(pairs):
            out={}
            for k,v in pairs:
                if k in out:raise ValueError('duplicate field')
                out[k]=v
            return out
        obj=json.loads(payload,object_pairs_hook=unique)
        if type(obj) is not dict or set(obj)!={'loss','loss_key'} or expected_mode!=MODE:raise ValueError('explicit new loss envelope/mode')
        metadata=obj['loss']
        if type(metadata) is not dict or 'temperature' not in metadata:raise ValueError('exact lossmetadata')
        temperature=TemperatureProfile.loads(_canonical(metadata['temperature']),expected_model_sha256=expected_model_sha256,expected_mode=TEMPERATURE_MODE)
        result=cls(temperature,MODE)
        if _canonical(metadata)!=_canonical(result.metadata()) or obj['loss_key']!=result.key:raise ValueError('loss schema/profile/precision changed')
        return result

def _power(a,tau):
    support=a>0
    if tau==1.:return a.copy()
    logs=np.zeros_like(a);np.log(a,out=logs,where=support)
    maximum=np.max(np.where(support,logs,-np.inf),axis=1,keepdims=True)
    e=np.zeros_like(a);np.exp(np.longdouble(tau)*(logs-maximum),out=e,where=support)
    result=e/e.sum(1,keepdims=True,dtype=np.longdouble)
    if not np.isfinite(result).all() or not np.array_equal(result>0,support):raise NumericalDomainError('power structural support unresolved; no epsilon')
    return result

def _law(profile,p,q,commands,observed_model_sha256,fixed_maps=None):
    if type(profile) is not FixedTemperatureLossProfile:raise ValueError('new loss profile, not old serving')
    temperature=profile.temperature;transport=temperature.base.transport
    if observed_model_sha256!=transport.base.model_sha256:raise ValueError('bound model required')
    precision();p,q=(np.asarray(x,dtype=np.float64) for x in (p,q))
    if p.ndim!=2 or p.shape!=q.shape or p.shape[1]!=12 or not 1<=len(p)<=65536:raise ValueError('matching bounded12class policies')
    _probabilities(p,1);_probabilities(q,1)
    if np.any(p<=0) or np.any(q<=0):raise NumericalDomainError('strict positive RAW policies; no repair')
    ts,ims=transport.base.text_semantics,transport.base.image_semantics
    if fixed_maps is None:
        if type(commands) is not tuple or len(commands)!=len(p) or any(type(c) is not Command for c in commands):raise ValueError('explicit immutable legal commands')
        ft=np.asarray([transport.destinations(ts,c) for c in commands],dtype=np.int64);fi=np.asarray([transport.destinations(ims,c) for c in commands],dtype=np.int64)
    else:
        if commands is not None or type(fixed_maps) is not tuple or len(fixed_maps)!=2:raise ValueError('explicit fixed maps separate from commands')
        ft,fi=(_maps(value,len(p)) for value in fixed_maps)
    pp=p.astype(np.longdouble);qq=q.astype(np.longdouble);pp/=pp.sum(1,keepdims=True,dtype=np.longdouble);qq/=qq.sum(1,keepdims=True,dtype=np.longdouble)
    before_a,before_b=push_policies(pp,qq,ft,fi)
    a=_power(before_a,temperature.text_inverse_temperature);original_b=_power(before_b,temperature.image_inverse_temperature)
    matching=np.argsort(ims)[np.asarray(ts)];b=original_b[:,matching]
    diagonal=np.minimum(a,b);left=a-diagonal;right=b-diagonal;ra=left.sum(1,dtype=np.longdouble);rb=right.sum(1,dtype=np.longdouble)
    joint=np.zeros((len(p),12,12),dtype=np.longdouble);active=(ra>0)&(rb>0)
    np.divide(left[:,:,None]*right[:,None,:],ra[:,None,None],out=joint,where=active[:,None,None]);joint[:,np.arange(12),np.arange(12)]+=diagonal;total=joint.sum((1,2),dtype=np.longdouble)
    if (np.any(total<=0) or not np.isfinite(joint).all() or np.any(joint<0) or np.any(np.abs(joint.sum(2)-a)>1e-12) or np.any(np.abs(joint.sum(1)-b)>1e-12)
            or np.any(np.abs(joint.sum(2)/total[:,None]-a)>1e-12) or np.any(np.abs(joint.sum(1)/total[:,None]-b)>1e-12)):raise NumericalDomainError('raw/CDF marginal check failed')
    table=np.empty_like(joint,dtype=np.float64);table[:,:,matching]=(joint/total[:,None,None]).astype(float);cdf=np.asarray([math.fsum(x.ravel().tolist()) for x in table]);actual=table/cdf[:,None,None];actual_a=actual.sum(2);actual_b=actual.sum(1)
    if (not np.isfinite(actual).all() or np.any(actual<0) or np.any(np.abs(actual_a-a)>1e-12) or np.any(np.abs(actual_b-original_b)>1e-12)
            or not np.array_equal(actual_a>0,before_a>0) or not np.array_equal(actual_b>0,before_b>0)
            or not np.array_equal(actual_a.argmax(1),before_a.argmax(1)) or not np.array_equal(actual_b.argmax(1),before_b.argmax(1))):raise NumericalDomainError('actual CDF support/argmax/marginal guard')
    return pp,qq,ft,fi,matching,before_a,before_b,a,b,left,right,ra,rb,joint,total

def value_and_grad(profile,p,q,rewards,commands,rho,*,observed_model_sha256,fixed_maps=None):
    if type(rho) not in (int,float) or rho not in (0.,1.5):raise ValueError('fixed risk0/1.5')
    rho=float(rho);ld=np.longdouble
    pp,qq,ft,fi,matching,before_a,before_b,a,b,left,right,ra,rb,joint,total=_law(profile,p,q,commands,observed_model_sha256,fixed_maps);n=len(pp)
    reward=np.asarray(rewards,dtype=float)
    if reward.shape!=(n,12,12) or not np.isfinite(reward).all() or np.any(reward<-.35) or np.any(reward>1):raise ValueError('fixed bounded RGB reward')
    constant=np.all(ft==ft[:,:1],1)&np.all(fi==fi[:,:1],1);active=np.flatnonzero(~constant)
    values=np.empty(n);gp=np.zeros((n,12));gq=np.zeros((n,12));indices=np.flatnonzero(constant)
    values[indices]=reward[indices,ft[indices,0],fi[indices,0]]
    diagnostic=dict(constant_composition_rows=int(constant.sum()),smooth_rows=len(active),minimum_active_residual=None,maximum_relative_balance_error=0.)
    if not len(active):return values,gp,gq,diagnostic
    aa,bb=a[active],b[active];ma,mb=ra[active],rb[active]
    if np.any((aa==bb)&(aa>0)):raise NumericalDomainError('positive exact min tie: no classical derivative selected')
    if np.any(np.minimum(ma,mb)<=RESIDUAL_FLOOR):raise NumericalDomainError('nonconstant residual outside fixed resolved domain; no floor substitution')
    balance=np.abs(ma-mb)/np.maximum(ma,mb)
    if np.any(balance>RELATIVE_BALANCE_TOL):raise NumericalDomainError('relative residual mass imbalance; no denominator repair')
    alpha=left[active]/ma[:,None];beta=right[active]/ma[:,None]
    if (not np.isfinite(alpha).all() or not np.isfinite(beta).all() or np.any(alpha<0) or np.any(beta<0)
            or np.any(np.abs(alpha.sum(1)-1)>RELATIVE_BALANCE_TOL)
            or np.any(np.abs(beta.sum(1)-1)>RELATIVE_BALANCE_TOL/(1-RELATIVE_BALANCE_TOL))):raise NumericalDomainError('unresolved normalized residuals')
    r=reward[active][:,:,matching];h=(r if rho==0 else np.exp(-rho*r)).astype(ld)
    weighted=(joint[active]*h).sum((1,2),dtype=ld);tot=total[active]
    hb=np.sum(h*beta[:,None,:],axis=2,dtype=ld);scalar=(alpha*hb).sum(1,dtype=ld)
    u=hb-scalar[:,None];v=np.sum(alpha[:,:,None]*h,axis=1,dtype=ld);d=np.diagonal(h,axis1=1,axis2=2);t=(aa<bb).astype(ld)
    fp=u+t*(d-u-v);fq=v+(1-t)*(d-u-v)
    if rho==0:
        values[active]=weighted/tot;da=-fp/tot[:,None];db=-fq/tot[:,None]+(weighted/tot**2)[:,None]
    else:
        if np.any(weighted<=0):raise NumericalDomainError('nonpositive entropic normalizer')
        values[active]=-np.log(weighted/tot)/ld(rho)
        da=fp/(ld(rho)*weighted[:,None]);db=fq/(ld(rho)*weighted[:,None])-1/(ld(rho)*tot[:,None])
    original_db=np.empty_like(db);original_db[:,matching]=db
    # h is derivative w.r.t. logweights of calibrated marginals (before1/n).
    htext=aa*(da-(aa*da).sum(1,keepdims=True,dtype=ld))
    original_b=np.empty_like(bb);original_b[:,matching]=bb
    himage=original_b*(original_db-(original_b*original_db).sum(1,keepdims=True,dtype=ld))
    # p_i/a_f(i) <=1 and positive: no division at structural-zero destinations.
    for raw,before,maps,h,tau,destination in ((pp,before_a,ft,htext,profile.temperature.text_inverse_temperature,gp),(qq,before_b,fi,himage,profile.temperature.image_inverse_temperature,gq)):
        denominator=np.take_along_axis(before[active],maps[active],1)
        if np.any(denominator<=0):raise NumericalDomainError('raw positive preimage has empty support')
        chain=ld(tau)*(raw[active]/denominator)*np.take_along_axis(h,maps[active],1)
        destination[active]=(chain-raw[active]*chain.sum(1,keepdims=True,dtype=ld))/n
    if not all(np.isfinite(x).all() for x in (values,gp,gq)):raise NumericalDomainError('nonfinite result')
    diagnostic['minimum_active_residual']=float(np.minimum(ma,mb).min());diagnostic['maximum_relative_balance_error']=float(balance.max())
    return values,gp,gq,diagnostic
