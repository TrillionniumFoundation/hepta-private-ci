"""Exact original A/N utility on a transported serving law via reward pullback.

For deterministic semantic maps f,g, R'(i,j)=R(f(i),g(j)). The expectation of
exp(-rho R') under original p*q equals that under transported marginals. Thus
the original tested utility gradient can be reused, without an STE or division
by a possibly zero transported output probability. Decoder maps are fixed.
"""
import numpy as np
from utility import joint_value_and_grad


def _maps(value, n):
    value=np.asarray(value)
    if value.shape!=(n,12) or value.dtype.kind not in 'iu' or np.any(value<0) or np.any(value>=12):
        raise ValueError('fixed row-wise twelve-class destination map required')
    return value


def push_policies(p,q,ft,fi):
    p,q=np.asarray(p),np.asarray(q)
    if p.ndim!=2 or p.shape!=q.shape or p.shape[1]!=12:raise ValueError('two finite-class policies')
    ft,fi=_maps(ft,len(p)),_maps(fi,len(p))
    a,b=np.zeros_like(p),np.zeros_like(q); rows=np.broadcast_to(np.arange(len(p))[:,None],p.shape)
    np.add.at(a,(rows,ft),p);np.add.at(b,(rows,fi),q)
    return a,b


def all_terms(p,q,rewards,labels,ft,fi,text_semantics,image_semantics,rho):
    """Compute all four risk profiles and both anchors in every comparison arm.

Returns logit derivatives of negative mean utility and positive mean anchor.
The raw control intentionally reproduces the original latent-label CE anchor.
The aligned anchor supervises final decoded target semantics after transport.
"""
    p,q=np.asarray(p),np.asarray(q); n=len(p)
    if p.shape!=(n,12) or q.shape!=p.shape:raise ValueError('matching finite policies')
    ft,fi=_maps(ft,n),_maps(fi,n);y=np.asarray(labels)
    ts,ims=np.asarray(text_semantics),np.asarray(image_semantics)
    if (y.shape!=(n,) or y.dtype.kind not in 'iu' or np.any(y<0) or np.any(y>=12)
            or ts.shape!=(12,) or ims.shape!=(12,) or set(ts.tolist())!=set(range(12)) or set(ims.tolist())!=set(range(12))):
        raise ValueError('target labels and bijective observed semantics required')
    rewards=np.asarray(rewards)
    if rewards.shape!=(n,12,12):raise ValueError('fixed external reward table')
    pulled=rewards[np.arange(n)[:,None,None],ft[:,:,None],fi[:,None,:]]
    raw_a=joint_value_and_grad(p,q,rewards,0)
    raw_n=joint_value_and_grad(p,q,rewards,rho)
    aligned_a=joint_value_and_grad(p,q,pulled,0)
    aligned_n=joint_value_and_grad(p,q,pulled,rho)
    # Preserve the exact arithmetic order of the original control gradient.
    dp,dq=p.copy(),q.copy();dp[np.arange(n),y]-=1;dq[np.arange(n),y]-=1
    dp/=2*n;dq/=2*n
    text_mask=ts[ft]==y[:,None];image_mask=ims[fi]==y[:,None]
    tp=np.sum(p*text_mask,axis=1);iq=np.sum(q*image_mask,axis=1)
    if np.any(tp<=0) or np.any(iq<=0) or not np.isfinite(tp).all() or not np.isfinite(iq).all():
        raise ValueError('target has no final semantic probability; no epsilon fallback')
    at=(p-p*text_mask/tp[:,None])/(2*n)
    ai=(q-q*image_mask/iq[:,None])/(2*n)
    return dict(raw_additive=raw_a,raw_ndu=raw_n,aligned_additive=aligned_a,aligned_ndu=aligned_n,
                raw_anchor=(dp,dq),aligned_anchor=(at,ai),
                aligned_anchor_value=float(-np.mean(np.log(tp)+np.log(iq))/2))


def select_gradients(terms,mode,objective,anchor):
    if mode not in ('raw','aligned') or objective not in ('additive','ndu') or not 0<=anchor<=1:
        raise ValueError('explicit training profile and anchor required')
    _,gp,gq=terms[mode+'_'+objective];dp,dq=terms[mode+'_anchor']
    return anchor*dp+gp,anchor*dq+gq
