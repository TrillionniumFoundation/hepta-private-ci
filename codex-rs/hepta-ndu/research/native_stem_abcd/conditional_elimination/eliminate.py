"""R24: exact inner Bernoulli risk elimination and globally valid residual tangents.

All bounds and prune decisions are Fraction, not floating point. This file is
additive to the historical R21/R22 code; no model or objective is redefined.
"""
from __future__ import annotations
from fractions import Fraction as F
from functools import lru_cache
from math import factorial
from pathlib import Path
import sys
try:
    import centered as c
except ImportError:
    # Source-only retained dependency: user can place centered and global_interval on PYTHONPATH.
    raise
old=c.old
G=old.G
M=2*G*G
PRECISION=10**36
N_EXP=30
N_LOG=25
GRID=tuple(F(j,4) for j in range(-16,17))

def floor_to(x):
    y=x*PRECISION
    return F(y.numerator//y.denominator,PRECISION)

def ceil_to(x):
    y=-x*PRECISION
    return -F(y.numerator//y.denominator,PRECISION)

class I:
    __slots__=('lo','hi')
    def __init__(self,lo,hi=None):
        self.lo=F(lo);self.hi=F(lo if hi is None else hi)
        if self.lo>self.hi:raise ValueError('reversed interval')
    @classmethod
    def of(cls,v):return v if isinstance(v,I) else cls(v)
    def __add__(self,x):
        y=I.of(x)
        return I(floor_to(self.lo+y.lo),ceil_to(self.hi+y.hi))
    __radd__=__add__
    def __neg__(self):return I(-self.hi,-self.lo)
    def __sub__(self,x):return self+-I.of(x)
    def __rsub__(self,x):return I.of(x)+-self
    def __mul__(self,x):
        y=I.of(x);v=[self.lo*y.lo,self.lo*y.hi,self.hi*y.lo,self.hi*y.hi]
        return I(floor_to(min(v)),ceil_to(max(v)))
    __rmul__=__mul__
    def reciprocal(self):
        if self.lo<=0<=self.hi:raise ZeroDivisionError('inverse includes zero')
        return I(floor_to(F(1)/self.hi),ceil_to(F(1)/self.lo))
    def __truediv__(self,x):return self*I.of(x).reciprocal()
    def __rtruediv__(self,x):return I.of(x)*self.reciprocal()
    def pair(self):return self.lo,self.hi

@lru_cache(maxsize=30000)
def expminus_point(x):
    """Exact interval for e^(-x), x>=0; alternating series and dyadic power."""
    x=F(x)
    if x<0:raise ValueError('negative exponent reduction')
    if not x:return I(1)
    halves=0;y=x
    while y>1:
        halves+=1;y/=2
    term=F(1);s=F(1);upper=None;lower=None
    for k in range(1,N_EXP+2):
        term*=(-y)/k;s+=term
        if k==N_EXP:upper=s
        if k==N_EXP+1:lower=s
    if not 0<lower<=upper<=1:raise ArithmeticError('invalid exponential alternating enclosure')
    q=I(floor_to(lower),ceil_to(upper))
    for _ in range(halves):q=q*q
    return q

@lru_cache(maxsize=30000)
def log1p_positive_point(x):
    """0<=x<=1; exact atanh sum with positive rigorous tail."""
    x=F(x)
    if x<0 or x>1:raise ValueError('log1p positive point range')
    z=x/(x+2)
    s=F(0);power=z
    for k in range(N_LOG):
        s+=F(2)*power/F(2*k+1)
        power*=z*z
    rem=F(2)*power/(F(2*N_LOG+1)*(1-z*z))
    return I(floor_to(s),ceil_to(s+rem))

LOG2=log1p_positive_point(F(1))

@lru_cache(maxsize=30000)
def logcosh_point(x):
    x=abs(F(x))
    em=expminus_point(2*x)
    lo=log1p_positive_point(em.lo)
    hi=log1p_positive_point(em.hi)
    l=I(x)+I(lo.lo,hi.hi)-LOG2
    return I(max(F(0),l.lo),l.hi)

def logcosh_interval(x):
    x=I.of(x)
    lo=F(0) if x.lo<=0<=x.hi else min(logcosh_point(x.lo).lo,logcosh_point(x.hi).lo)
    hi=max(logcosh_point(x.lo).hi,logcosh_point(x.hi).hi)
    return I(lo,hi)

@lru_cache(maxsize=30000)
def tanh_point(x):
    x=F(x)
    if x<0:
        q=tanh_point(-x)
        return -q
    e=expminus_point(2*x)
    return (1-e)/(1+e)

def tanh_interval(x):
    x=I.of(x)
    lo=tanh_point(x.lo).lo
    hi=tanh_point(x.hi).hi
    return I(lo,hi)

def scalar_level(z,p):
    """Exact inner-epsilon2 Bernoulli CE, stage preference, derivative in z."""
    z=F(z);rho=F(1,2) if p==0 else F(1)
    arg=rho*(z/F(5)+F(1-2*p,100))
    q=I(F(p,20))+G*(I(z*z+F(1,50))+logcosh_point(arg)/rho)
    dq=G*(I(2*z)+tanh_point(arg)/5)
    return q,dq

@lru_cache(maxsize=6000)
def scalar_F(z,p0):
    """F_{p0}(z), F'_{p0}(z) at a rational anchor, entirely enclosed."""
    q0,g0=scalar_level(z,0)
    q1,g1=scalar_level(z,1)
    rho=F(1,2) if p0==0 else F(1)
    delta=q1-q0
    q=G*((q0+q1)/2+logcosh_interval(delta*rho/2)/rho)
    w=(1+tanh_interval(delta*rho/2))/2
    gradient=G*((1-w)*g0+w*g1)
    return q,gradient

def residual_interval(box,x):
    """Original R21 exact forward intervals, algebraically eliminate all leaves."""
    n=len(box)
    if n not in (2,3,4):raise ValueError('unsupported parameter count')
    a,b=box[:2]
    cc=box[2] if n>=3 else (F(0),F(0))
    d=box[3] if n>=4 else (F(0),F(0))
    v=old.add(a,old.scale(b,-1))
    h1=old.add(old.scale(a,F(x)),cc)
    res=old.add(old.mult(b,h1),old.scale(old.mult(d,old.square(h1)),F(1,4)))
    res=old.add(res,old.scale(old.square(v),F(1,4)))
    res=old.add(res,old.qr(a,old.ETA))
    res=old.add(res,old.qr(v,old.KAPPA))
    return old.plus(res,-F(x)-1)

def quadratic_min(delta_lo,delta_hi,g,m=M):
    """min_{delta in [lo,hi]} g*delta+(m/2)*delta² exactly."""
    q=max(delta_lo,min(delta_hi,-g/m))
    return g*q+m*q*q/2

@lru_cache(maxsize=100000)
def scalar_box_lower(lo,hi,p0):
    """Maximum over fixed globally valid m-strong convex tangent quadratics."""
    if lo>hi:raise ValueError('residual interval reversed')
    best=None
    for z0 in GRID:
        q,grad=scalar_F(z0,p0)
        dl=lo-z0;dh=hi-z0
        # For a fixed delta, minimization over interval gradient occurs at an endpoint.
        # Hence min_delta,gradient = min(tangent using either gradient endpoint).
        l=q.lo+min(quadratic_min(dl,dh,grad.lo),quadratic_min(dl,dh,grad.hi))
        if best is None or l>best:best=l
    return best

def conditional_lower(box):
    n=len(box)
    if any(a>b for a,b in box):raise ValueError('reversed parameter box')
    residuals=[residual_interval(box,x) for x in (-1,1)]
    value=sum((scalar_box_lower(rl,rh,p0) for rl,rh in residuals for p0 in (0,1)),F(0))/4
    regularizer=sum((old.square(b)[0] for b in box),F(0))/4
    return value+regularizer

def hybrid_lower(box):
    return max(c.hybrid_lower(box),conditional_lower(box))

if __name__=='__main__':
    import json
    for n in (2,3,4):
        b=tuple((-F(3),F(3)) for _ in range(n))
        print(json.dumps(dict(width=n,root_new=float(hybrid_lower(b)),root_old=float(c.hybrid_lower(b)))))
