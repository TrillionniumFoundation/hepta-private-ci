"""Explicit opt-in least upward class-credit consistency repair, not default reward.

Original class utility: .3*ct+.3*ci+.3*ct*ci-.35*disagreement.
A solitary correct output with a wrong other output has class utility -.05,
below consistent-both-wrong utility0. Add exactly .35-.3 for XOR correctness.
This is the least pointwise upward class-only correction under correcting either
output without making the other less correct. Pixel utility stays unchanged;
no monotonicity is promised if changing an image worsens pixel quality.
All original rewards and acceptance metrics must remain separately available.
"""
import numpy as np
MODE='least-upward-class-credit-consistency-v1'
SCHEMA='rgb-class-credit-consistency-reward-v1'

def repair_rewards(original,labels,text_semantics,image_semantics,*,mode):
    if mode!=MODE:raise ValueError('explicit reward-repair opt-in required')
    r=np.asarray(original,dtype=float);y=np.asarray(labels);ts=np.asarray(text_semantics);ims=np.asarray(image_semantics)
    if (r.ndim!=3 or r.shape!=(len(y),12,12) or y.dtype.kind not in 'iu' or y.ndim!=1
            or np.any(y<0) or np.any(y>=12) or not np.isfinite(r).all() or np.any(r<-.35) or np.any(r>1)):
        raise ValueError('fixed bounded original RGB reward and labels')
    if (ts.shape!=(12,) or ims.shape!=(12,) or ts.dtype.kind not in 'iu' or ims.dtype.kind not in 'iu'
            or set(ts.tolist())!=set(range(12)) or set(ims.tolist())!=set(range(12))):raise ValueError('bijective decoded semantics')
    ct=ts[None,:,None]==y[:,None,None];ci=ims[None,None,:]==y[:,None,None]
    # Validate the original fixed class-credit profile up to its image-only [0,.1]
    # quality component. No arbitrary original objective may claim this identity.
    class_part=.3*ct+.3*ci+.3*(ct&ci)-.35*(ts[None,:,None]!=ims[None,None,:])
    quality=r-class_part
    if (np.any(quality< -1e-12) or np.any(quality>.1+1e-12)
            or np.any(np.abs(quality-quality[:,:1,:])>1e-12)):
        raise ValueError('original fixed class-credit plus image-only quality required')
    return r+(.35-.3)*(ct^ci)
