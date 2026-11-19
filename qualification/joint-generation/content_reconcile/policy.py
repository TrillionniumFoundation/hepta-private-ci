"""One fixed diagonal-support reconciler and its exact finite joint law."""

import numpy as np


TAUS=("zero","log2","infinity")


def _check(p,q,tau):
    p,q=np.asarray(p,dtype=np.float64),np.asarray(q,dtype=np.float64)
    if (tau not in TAUS or p.ndim!=2 or p.shape!=q.shape or p.shape[1]!=12 or not 1<=len(p)<=65536
            or not np.isfinite(p).all() or not np.isfinite(q).all() or np.any(p<0) or np.any(q<0)
            or not np.allclose(p.sum(1),1,rtol=0,atol=1e-10) or not np.allclose(q.sum(1),1,rtol=0,atol=1e-10)):
        raise ValueError("matching finite twelve-way policies and fixed threshold required")
    return p,q


def _charge(ledger,stage,name,**work):
    if ledger is not None: ledger.charge_kernel(stage,name,**work)


def _exact(p,q,t,i,multiplier):
    a,b=float(p[t]).as_integer_ratio(),float(q[t]).as_integer_ratio()
    c,d=float(p[i]).as_integer_ratio(),float(q[i]).as_integer_ratio()
    left=a[0]*b[0]*c[1]*d[1]
    right=c[0]*d[0]*a[1]*b[1]
    bits=sum(value.bit_length() for ratio in (a,b,c,d) for value in ratio)
    if left>multiplier*right: return 1,7,1,bits
    return (2 if right>multiplier*left else 0),8,2,bits


def _compare(p,q,t,i,dt,di,tau,ledger,stage):
    multiplier=1 if tau=="zero" else 2
    cells=t.size
    # Both double products are rounded. Only decisions outside a conservative
    # roundoff band are accepted; boundary/underflow cases use exact float ratios.
    a,b=dt,multiplier*di
    c,d=di,multiplier*dt
    first,second=a>b,c>d
    uncertain=((np.abs(a-b)<=8*np.finfo(float).eps*np.maximum(a,b))
               |(np.abs(c-d)<=8*np.finfo(float).eps*np.maximum(c,d)))&(t!=i)
    uncertain|=((dt<np.finfo(float).tiny)|(di<np.finfo(float).tiny))&(t!=i)
    action=np.where(t==i,0,np.where(first,1,np.where(second,2,0))).astype(np.int8)
    _charge(ledger,stage,"support_comparison",scalar_ops=12*cells,compare_ops=11*cells)
    indices=np.argwhere(uncertain)
    scalar_ops,compare_ops,bits=0,0,0
    for row,column in indices:
        value,scalars,compares,operand_bits=_exact(p[row],q[row],int(t[row,column]),int(i[row,column]),multiplier)
        action[row,column]=value
        scalar_ops+=scalars
        compare_ops+=compares
        bits+=operand_bits
    _charge(ledger,stage,"exact_boundary_fallback",scalar_ops=scalar_ops,compare_ops=compare_ops)
    if ledger is not None:
        ledger.record(stage,exact_support_comparisons=len(indices),exact_ratio_operand_bits=bits,support_comparison_cells=cells)
    return action


def repair(p,q,pairs,tau,ledger=None,stage="repair"):
    p,q=_check(p,q,tau)
    pairs=np.asarray(pairs)
    if pairs.shape!=(len(p),2) or pairs.dtype.kind not in "iu" or np.any(pairs<0) or np.any(pairs>=12):
        raise ValueError("one bounded original code pair per request required")
    if tau=="infinity": return pairs.copy(),np.zeros(len(p),dtype=np.int8)
    rows=np.arange(len(p))
    t,i=pairs[:,0],pairs[:,1]
    dt=p[rows,t]*q[rows,t]
    di=p[rows,i]*q[rows,i]
    _charge(ledger,stage,"two_support_products",scalar_ops=2*len(p))
    actions=_compare(p,q,t[:,None],i[:,None],dt[:,None],di[:,None],tau,ledger,stage)[:,0]
    result=np.column_stack((np.where(actions==2,i,t),np.where(actions==1,t,i)))
    _charge(ledger,stage,"repair_pair",compare_ops=2*len(p))
    return result,actions


def compile_joint(p,q,tau,ledger=None,stage="compile_Q"):
    p,q=_check(p,q,tau)
    n=len(p)
    original=p[:,:,None]*q[:,None,:]
    _charge(ledger,stage,"original_product",scalar_ops=144*n)
    if tau=="infinity":
        destination=np.broadcast_to(np.arange(144),(n,144))
        return original,original,destination,np.zeros((n,144),dtype=np.int8)
    diagonal=p*q
    _charge(ledger,stage,"diagonal_support",scalar_ops=12*n)
    t=np.broadcast_to(np.repeat(np.arange(12),12),(n,144))
    i=np.broadcast_to(np.tile(np.arange(12),12),(n,144))
    dt=np.repeat(diagonal,12,axis=1)
    di=np.tile(diagonal,(1,12))
    actions=_compare(p,q,t,i,dt,di,tau,ledger,stage)
    a=np.where(actions==2,i,t)
    b=np.where(actions==1,t,i)
    destination=12*a+b
    indices=144*np.arange(n)[:,None]+destination
    joint=np.bincount(indices.ravel(),weights=original.ravel(),minlength=n*144).reshape(n,12,12)
    _charge(ledger,stage,"pushforward_scatter",scalar_ops=4*144*n+n,compare_ops=2*144*n)
    return joint,original,destination,actions


def sample_original(p,q,rng,ledger,stage):
    draws=rng.random((len(p),2))
    pairs=np.minimum(np.column_stack(((np.cumsum(p,axis=1)<draws[:,0,None]).sum(1),
                                     (np.cumsum(q,axis=1)<draws[:,1,None]).sum(1))),11)
    _charge(ledger,stage,"sample_original",scalar_ops=46*len(p),compare_ops=26*len(p))
    return pairs


def sample_joint(joint,rng,ledger,stage):
    flat=joint.reshape(len(joint),144)
    draws=rng.random(len(joint))
    ids=np.minimum((np.cumsum(flat,axis=1)<draws[:,None]).sum(1),143)
    _charge(ledger,stage,"sample_joint144",scalar_ops=287*len(joint),compare_ops=145*len(joint),div_ops=2*len(joint))
    return np.column_stack((ids//12,ids%12))


def greedy(p,q,tau,ledger=None,stage="greedy"):
    original=np.column_stack((p.argmax(1),q.argmax(1)))
    _charge(ledger,stage,"original_head_argmax",compare_ops=22*len(p))
    repaired,action=repair(p,q,original,tau,ledger,stage)
    return original,repaired,action
