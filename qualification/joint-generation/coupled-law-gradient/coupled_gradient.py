"""Exact analytic smooth-branch loss derivative for the opt-in coupled law.

Finite RGB profile only: fixed external rewards in[-.35,1],rho0 or1.5. This is NOT
the old independent-law gradient, an STE, epsilon repair, or a derivative at kinks.
Both constant transport maps give a structurally constant composition. Otherwise
positive min ties,unresolved residuals or relative mass imbalance reject the run.
Numerical domain constants are prospective engineering restrictions,not a theorem
bounding all gradient error. No guard substitutes a value into the objective.
"""
import math
import numpy as np
from aligned import _maps,push_policies
from utility import _probabilities

TRAINING_MODE='coupled-joint-law-exact-smooth-v1'
SCHEMA='rgb-coupled-law-loss-v1'
RESIDUAL_FLOOR=64*np.finfo(np.float64).eps
RELATIVE_BALANCE_TOL=math.sqrt(np.finfo(np.float64).eps)


class NumericalDomainError(ValueError):pass


def coupled_value_and_grad(p,q,rewards,ft,fi,text_semantics,image_semantics,rho,*,mode):
    if mode!=TRAINING_MODE or float(rho) not in (0.,1.5):
        raise ValueError('explicit coupled smooth loss profile and fixed A/N risk required')
    rho=float(rho);p,q=(np.asarray(x,dtype=np.float64) for x in (p,q))
    if p.ndim!=2:raise ValueError('two-dimensional raw policies required')
    n=len(p)
    if p.ndim!=2 or p.shape!=(n,12) or q.shape!=p.shape or not 1<=n<=65536:
        raise ValueError('matching bounded twelve-class raw policies required')
    _probabilities(p,1);_probabilities(q,1)
    if np.any(p<=0) or np.any(q<=0):raise NumericalDomainError('raw softmax must be strictly positive; no underflow repair')
    ft,fi=_maps(ft,n),_maps(fi,n)
    ts,ims=np.asarray(text_semantics),np.asarray(image_semantics)
    if (ts.shape!=(12,) or ims.shape!=(12,) or ts.dtype.kind not in 'iu' or ims.dtype.kind not in 'iu'
            or set(ts.tolist())!=set(range(12)) or set(ims.tolist())!=set(range(12))):
        raise ValueError('exact bijective observed semantic inventories required')
    reward=np.asarray(rewards,dtype=np.float64)
    if reward.shape!=(n,12,12) or not np.isfinite(reward).all() or np.any(reward<-.35) or np.any(reward>1):
        raise ValueError('fixed external bounded RGB reward required')
    a,original_b=push_policies(p,q,ft,fi)
    matching=np.argsort(ims)[ts];b=original_b[:,matching];rtable=reward[:,:,matching]
    constant=np.all(ft==ft[:,:1],axis=1)&np.all(fi==fi[:,:1],axis=1)
    values=np.empty(n);gp=np.zeros_like(p);gq=np.zeros_like(q)
    indices=np.flatnonzero(constant)
    if (np.any(np.abs(a[indices,ft[indices,0]]-1)>1e-12)
            or np.any(np.abs(original_b[indices,fi[indices,0]]-1)>1e-12)):
        raise NumericalDomainError('constant-law CDF marginals incompatible with raw mass')
    values[indices]=reward[indices,ft[indices,0],fi[indices,0]]
    active=np.flatnonzero(~constant)
    diagnostic={'constant_composition_rows':int(constant.sum()),'smooth_rows':len(active),
                'minimum_active_residual':None,'maximum_relative_balance_error':0.0}
    if not len(active):return values,gp,gq,diagnostic
    aa,bb=a[active],b[active]
    if np.any((aa==bb)&(aa>0)):raise NumericalDomainError('positive exact min tie: no classical derivative selected')
    diagonal=np.minimum(aa,bb);left=aa-diagonal;right=bb-diagonal
    mass_a=np.asarray([math.fsum(x.tolist()) for x in left]);mass_b=np.asarray([math.fsum(x.tolist()) for x in right])
    if np.any(np.minimum(mass_a,mass_b)<=RESIDUAL_FLOOR):
        raise NumericalDomainError('nonconstant residual outside fixed resolved domain; no floor substitution')
    balance=np.abs(mass_a-mass_b)/np.maximum(mass_a,mass_b)
    if np.any(balance>RELATIVE_BALANCE_TOL):raise NumericalDomainError('relative residual mass imbalance; no renormalization repair')
    alpha=left/mass_a[:,None];beta=right/mass_a[:,None]
    if (not np.isfinite(alpha).all() or not np.isfinite(beta).all() or np.any(alpha<0) or np.any(beta<0)
            or np.any(np.abs(alpha.sum(1)-1)>RELATIVE_BALANCE_TOL)
            or np.any(np.abs(beta.sum(1)-1)>RELATIVE_BALANCE_TOL/(1-RELATIVE_BALANCE_TOL))):
        raise NumericalDomainError('unresolved normalized residuals')
    joint=left[:,:,None]*right[:,None,:]/mass_a[:,None,None]
    joint[:,np.arange(12),np.arange(12)]+=diagonal
    total=np.asarray([math.fsum(x.ravel().tolist()) for x in joint])
    if (np.any(np.abs(joint.sum(2)-aa)>1e-12) or np.any(np.abs(joint.sum(1)-bb)>1e-12)
            or np.any(np.abs(joint.sum(2)/total[:,None]-aa)>1e-12)
            or np.any(np.abs(joint.sum(1)/total[:,None]-bb)>1e-12)):
        raise NumericalDomainError('raw or CDF-normalized marginal preservation failed')
    h=rtable[active] if rho==0 else np.exp(-rho*rtable[active])
    weighted=np.sum(joint*h,axis=(1,2))
    hb=np.einsum('nij,nj->ni',h,beta)
    scalar=np.sum(alpha*hb,axis=1)
    u=hb-scalar[:,None];v=np.einsum('ni,nij->nj',alpha,h)
    d=np.diagonal(h,axis1=1,axis2=2);t=(aa<bb).astype(float)
    # Structural zero/zero ties have no transport preimage because raw p,q>0.
    fp=u+t*(d-u-v);fq=v+(1-t)*(d-u-v)
    if rho==0:
        values[active]=weighted/total
        da=-fp/total[:,None]
        db=-fq/total[:,None]+(weighted/total**2)[:,None]
    else:
        if np.any(weighted<=0):raise NumericalDomainError('nonpositive entropic normalizer; no epsilon')
        values[active]=-np.log(weighted/total)/rho
        da=fp/(rho*weighted[:,None])
        db=fq/(rho*weighted[:,None])-1/(rho*total[:,None])
    original_db=np.empty_like(db);original_db[:,matching]=db
    pulled_a=np.take_along_axis(da,ft[active],axis=1)
    pulled_b=np.take_along_axis(original_db,fi[active],axis=1)
    gp[active]=p[active]*(pulled_a-np.sum(p[active]*pulled_a,axis=1,keepdims=True))/n
    gq[active]=q[active]*(pulled_b-np.sum(q[active]*pulled_b,axis=1,keepdims=True))/n
    if not all(np.isfinite(x).all() for x in (values,gp,gq)):raise NumericalDomainError('nonfinite exact-branch result')
    diagnostic['minimum_active_residual']=float(np.minimum(mass_a,mass_b).min())
    diagnostic['maximum_relative_balance_error']=float(balance.max())
    return values,gp,gq,diagnostic
