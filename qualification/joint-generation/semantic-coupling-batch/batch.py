"""Batched implementation of the already qualified opt-in coupling law.

Binding is checked once per batch. No new semantics, target, decoder or training
objective. The original scalar API and default independent service stay unchanged.
"""
import math
import numpy as np
from control import Command
from coupling import CouplingProfile


def apply_batch(profile,text,image,commands,*,observed_model_sha256):
    if type(profile) is not CouplingProfile or observed_model_sha256!=profile.transport.base.model_sha256:
        raise ValueError('exact bound coupling profile/model required')
    p,q=np.asarray(text),np.asarray(image)
    if (p.ndim!=2 or p.shape!=q.shape or p.shape[1]!=12 or not 1<=len(p)<=65536
            or p.dtype.kind not in 'if' or q.dtype.kind not in 'if'):
        raise ValueError('bounded numeric [N,12] policies required')
    p,q=np.asarray(p,dtype=np.float64),np.asarray(q,dtype=np.float64);n=len(p)
    if type(commands) is not tuple or len(commands)!=n or any(type(c) is not Command for c in commands):
        raise ValueError('immutable explicit command batch required')
    for policy in (p,q):
        if not np.isfinite(policy).all() or np.any(policy<0) or np.any(np.abs(policy.sum(1)-1)>1e-10):
            raise ValueError('finite normalized policy rows required')
    row=np.broadcast_to(np.arange(n)[:,None],p.shape);a,b=np.zeros_like(p),np.zeros_like(q)
    ts,ims=profile.transport.base.text_semantics,profile.transport.base.image_semantics
    for source,destination,semantics in ((p,a,ts),(q,b,ims)):
        mapping=np.asarray([profile.transport.destinations(semantics,c) for c in commands],dtype=np.int64)
        np.add.at(destination,(row,mapping),source)
    inverse={s:j for j,s in enumerate(ims)};matching=np.asarray([inverse[s] for s in ts])
    diagonal=np.minimum(a,b[:,matching]);left=a-diagonal;right=b.copy();right[:,matching]-=diagonal
    mass_t=np.asarray([math.fsum(x.tolist()) for x in left]);mass_i=np.asarray([math.fsum(x.tolist()) for x in right])
    joint=np.zeros((n,12,12));active=(mass_t>0)&(mass_i>0)
    np.divide(left[:,:,None]*right[:,None,:],mass_t[:,None,None],out=joint,where=active[:,None,None])
    joint[:,np.arange(12),matching]+=diagonal
    if np.any(np.abs(joint.sum(2)-a)>1e-12) or np.any(np.abs(joint.sum(1)-b)>1e-12):
        raise ValueError('incompatible raw masses; no repair')
    total=np.asarray([math.fsum(x.ravel().tolist()) for x in joint])
    if (np.any(total<=0) or np.any(np.abs(joint.sum(2)/total[:,None]-a)>1e-12)
            or np.any(np.abs(joint.sum(1)/total[:,None]-b)>1e-12)):
        raise ValueError('CDF-normalized law does not preserve marginals; no repair')
    return dict(text=a,image=b,joint=joint,cdf_total=total,profile_key=profile.key,
                commands=tuple(c.values for c in commands),implementation='validated-batch-v1')
