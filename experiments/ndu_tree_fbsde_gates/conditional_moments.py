"""Exact finite conditional martingale-regression oracle for P4 shadow evidence.

Center increments and next utilities. Solve Z Sigma=B for the REGISTERED
finite event law. Full-rank covariance does NOT guarantee a complete martingale
representation: an orthogonal residual must be reported separately.
"""
from __future__ import annotations
from dataclasses import dataclass
from fractions import Fraction as Q
from stitch_audit import rational


@dataclass(frozen=True)
class MomentCertificate:
    covariance: tuple[tuple[Q,...],...]
    utility_covariance: tuple[Q,...]
    z: tuple[Q,...]
    conditional_utility: Q
    conditional_increment_mean: tuple[Q,...]
    covariance_regression_residual: tuple[Q,...]
    martingale_representation_residual: tuple[Q,...]
    martingale_complete: bool
    distinct_driver_dimension: int
    full_rank: bool
    stochastic_fbsde_global_qualified: bool=False


def _linear(A,b):
    """Exact Gauss-Jordan with pivot checks, no floating pseudoinverse."""
    n=len(b)
    m=[list(row)+[v] for row,v in zip(A,b)]
    for k in range(n):
        pivot=next((i for i in range(k,n) if m[i][k]!=0),None)
        if pivot is None:
            raise ValueError("singular covariance: Z is not identifiable")
        m[k],m[pivot]=m[pivot],m[k]
        factor=m[k][k]
        m[k]=[v/factor for v in m[k]]
        for i in range(n):
            if i==k:continue
            scale=m[i][k]
            m[i]=[left-scale*right for left,right in zip(m[i],m[k])]
    return tuple(row[-1] for row in m)


def calculate(probabilities, increments, next_utilities):
    """Audit a conditional law at one *public* history, never train on labels."""
    if not isinstance(probabilities,(list,tuple)) or not isinstance(increments,(list,tuple)) or not isinstance(next_utilities,(list,tuple)):
        raise ValueError("bounded complete discrete support required")
    n=len(probabilities)
    if not 2<=n<=32 or len(increments)!=n or len(next_utilities)!=n:
        raise ValueError("conditional law coverage mismatch")
    p=tuple(rational(x) for x in probabilities)
    if any(x<=0 for x in p) or sum(p)!=1:
        raise ValueError("all conditional support probabilities must be positive and normalized")
    if not isinstance(increments[0],(list,tuple)):
        raise ValueError("driver vectors required")
    d=len(increments[0])
    if not 1<=d<=4:
        raise ValueError("bounded driver dimension 1..4")
    if any(not isinstance(row,(list,tuple)) or len(row)!=d for row in increments):
        raise ValueError("driver dimension drift")
    drivers=tuple(tuple(rational(y) for y in row) for row in increments)
    u=tuple(rational(y) for y in next_utilities)
    um=sum((pp*v for pp,v in zip(p,u)),Q(0))
    mu=tuple(sum((pp*m[i] for pp,m in zip(p,drivers)),Q(0)) for i in range(d))
    mc=tuple(tuple(m[i]-mu[i] for i in range(d)) for m in drivers)
    uc=tuple(y-um for y in u)
    sigma=tuple(tuple(sum((pp*m[i]*m[j] for pp,m in zip(p,mc)),Q(0))
                     for j in range(d)) for i in range(d))
    b=tuple(sum((pp*uu*m[i] for pp,uu,m in zip(p,uc,mc)),Q(0)) for i in range(d))
    z=_linear(sigma,b)
    zr=tuple(sum((z[j]*sigma[j][i] for j in range(d)),Q(0))-b[i] for i in range(d))
    orth=tuple(uu-sum((z[i]*m[i] for i in range(d)),Q(0)) for uu,m in zip(uc,mc))
    return MomentCertificate(sigma,b,z,um,mu,zr,orth,
                             all(v==0 for v in orth),d,True)
