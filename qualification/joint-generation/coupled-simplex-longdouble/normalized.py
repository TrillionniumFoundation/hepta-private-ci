"""Explicit normalized-longdouble coupled profile; old/default modes unchanged.

Each policy is explicitly normalized in genuinely extended precision BEFORE semantic
transport. Rounded binary64 risk costs are retained. Loss derivatives are analytic
normalized-logweight derivatives of this new smooth reference graph, evaluated in
extended precision; not derivatives of every rounded instruction or at min kinks.
No residual denominator, domain threshold or positive tie is silently repaired.
"""
from dataclasses import dataclass
import hashlib,json,math
import numpy as np
from control import _canonical,Command
from coupling import CouplingProfile,COUPLING_MODE
from aligned import _maps,push_policies
from utility import _probabilities
from coupled_gradient import NumericalDomainError,RESIDUAL_FLOOR,RELATIVE_BALANCE_TOL

MODE='coupled-simplex-longdouble-v1'
SCHEMA='rgb-coupled-simplex-longdouble-profile-v1'
LOSS_SCHEMA='rgb-coupled-simplex-longdouble-loss-v1'

def precision():
    info=np.finfo(np.longdouble)
    if info.eps>=np.finfo(np.float64).eps:raise NumericalDomainError('genuine extended precision required; no fallback')
    return dict(mantissa_bits=int(info.nmant),maximum_exponent=int(info.maxexp))

@dataclass(frozen=True)
class NormalizedCouplingProfile:
    coupling: CouplingProfile
    mode: str
    def __post_init__(self):
        if type(self.coupling) is not CouplingProfile or self.mode!=MODE:raise ValueError('explicit new numeric profile required')
        precision()
    @property
    def transport(self):return self.coupling.transport
    def metadata(self):
        return dict(schema=SCHEMA,mode=self.mode,precision=precision(),coupling_profile=json.loads(self.coupling.dumps()))
    @property
    def key(self):return hashlib.sha256(_canonical(self.metadata()).encode()).hexdigest()
    def dumps(self):return _canonical(dict(profile=self.metadata(),profile_key=self.key))
    @classmethod
    def loads(cls,payload,*,expected_model_sha256,expected_mode):
        if type(payload) is not str or len(payload.encode())>65536:raise ValueError('bounded numeric profile document')
        def unique(pairs):
            result={}
            for k,v in pairs:
                if k in result:raise ValueError('duplicate field')
                result[k]=v
            return result
        obj=json.loads(payload,object_pairs_hook=unique)
        if type(obj) is not dict or set(obj)!={'profile','profile_key'}:raise ValueError('exact numeric envelope')
        p=obj['profile']
        if (type(p) is not dict or set(p)!={'schema','mode','precision','coupling_profile'} or p['schema']!=SCHEMA
                or expected_mode!=MODE or p['mode']!=expected_mode or p['precision']!=precision()):
            raise ValueError('explicit numeric mode/schema/precision mismatch')
        base=CouplingProfile.loads(_canonical(p['coupling_profile']),expected_model_sha256=expected_model_sha256,expected_mode=COUPLING_MODE)
        result=cls(base,expected_mode)
        if obj['profile_key']!=result.key:raise ValueError('altered numeric identity')
        return result


def _law(p,q,ft,fi,ts,ims):
    precision();p,q=(np.asarray(x,dtype=np.float64) for x in (p,q))
    if p.ndim!=2 or p.shape!=q.shape or p.shape[1]!=12 or not 1<=len(p)<=65536:raise ValueError('bounded twelve-class policies')
    _probabilities(p,1);_probabilities(q,1)
    if np.any(p<=0) or np.any(q<=0):raise NumericalDomainError('strictly positive raw policies; no underflow repair')
    n=len(p);ft,fi=_maps(ft,n),_maps(fi,n);ts,ims=np.asarray(ts),np.asarray(ims)
    if (ts.shape!=(12,) or ims.shape!=(12,) or ts.dtype.kind not in 'iu' or ims.dtype.kind not in 'iu'
            or set(ts.tolist())!=set(range(12)) or set(ims.tolist())!=set(range(12))):raise ValueError('bijective observed semantics')
    ld=np.longdouble;pp=p.astype(ld);qq=q.astype(ld);pp/=pp.sum(1,keepdims=True,dtype=ld);qq/=qq.sum(1,keepdims=True,dtype=ld)
    a,original_b=push_policies(pp,qq,ft,fi);matching=np.argsort(ims)[ts];b=original_b[:,matching]
    diagonal=np.minimum(a,b);left=a-diagonal;right=b-diagonal;ra=left.sum(1,dtype=ld);rb=right.sum(1,dtype=ld)
    joint=np.zeros((n,12,12),dtype=ld);active=(ra>0)&(rb>0)
    np.divide(left[:,:,None]*right[:,None,:],ra[:,None,None],out=joint,where=active[:,None,None])
    joint[:,np.arange(12),np.arange(12)]+=diagonal
    total=joint.sum((1,2),dtype=ld)
    if (np.any(total<=0) or not np.isfinite(joint).all() or np.any(joint<0)
            or np.any(np.abs(joint.sum(2)-a)>1e-12) or np.any(np.abs(joint.sum(1)-b)>1e-12)
            or np.any(np.abs(joint.sum(2)/total[:,None]-a)>1e-12)
            or np.any(np.abs(joint.sum(1)/total[:,None]-b)>1e-12)):
        raise NumericalDomainError('raw or CDF marginal check failed')
    return pp,qq,ft,fi,matching,a,b,left,right,ra,rb,joint,total


def apply_batch(profile,p,q,commands,*,observed_model_sha256):
    if type(profile) is not NormalizedCouplingProfile or observed_model_sha256!=profile.transport.base.model_sha256:
        raise ValueError('exact new numeric profile and bound model required')
    if type(commands) is not tuple or len(commands)!=len(p) or any(type(c) is not Command for c in commands):
        raise ValueError('immutable explicit command batch')
    ts,ims=profile.transport.base.text_semantics,profile.transport.base.image_semantics
    ft=np.asarray([profile.transport.destinations(ts,c) for c in commands],dtype=np.int64)
    fi=np.asarray([profile.transport.destinations(ims,c) for c in commands],dtype=np.int64)
    pp,qq,ft,fi,matching,a,b,left,right,ra,rb,joint,total=_law(p,q,ft,fi,ts,ims)
    table=np.empty_like(joint,dtype=np.float64);table[:,:,matching]=(joint/total[:,None,None]).astype(float)
    output_b=np.empty_like(b);output_b[:,matching]=b
    cdf=np.asarray([math.fsum(x.ravel().tolist()) for x in table])
    if (np.any(np.abs(table.sum(2)/cdf[:,None]-a)>1e-12)
            or np.any(np.abs(table.sum(1)/cdf[:,None]-output_b)>1e-12)):
        raise NumericalDomainError('returned binary64 CDF marginal check failed')
    return dict(text=a.astype(float),image=output_b.astype(float),joint=table,cdf_total=cdf,
                profile_key=profile.key,commands=tuple(c.values for c in commands),implementation=MODE)


def value_and_grad(p,q,rewards,ft,fi,ts,ims,rho,*,mode):
    if mode!=MODE or float(rho) not in (0.,1.5):raise ValueError('explicit new loss profile and fixed risk')
    rho=float(rho);ld=np.longdouble
    pp,qq,ft,fi,matching,a,b,left,right,ra,rb,joint,total=_law(p,q,ft,fi,ts,ims);n=len(pp)
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
    hp=np.take_along_axis(da,ft[active],1);hq=np.take_along_axis(original_db,fi[active],1)
    gp[active]=pp[active]*(hp-(pp[active]*hp).sum(1,keepdims=True,dtype=ld))/n
    gq[active]=qq[active]*(hq-(qq[active]*hq).sum(1,keepdims=True,dtype=ld))/n
    if not all(np.isfinite(x).all() for x in (values,gp,gq)):raise NumericalDomainError('nonfinite result')
    diagnostic['minimum_active_residual']=float(np.minimum(ma,mb).min());diagnostic['maximum_relative_balance_error']=float(balance.max())
    return values,gp,gq,diagnostic
