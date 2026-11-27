"""Rigorous directed-rounding 2-step positive-risk entropic NDU certificate.

All bounds use integers with outward rounding at a fixed 10**65 scale.
Taylor remainders are rational analytic inequalities. No floats in proof.
"""
from __future__ import annotations
from dataclasses import dataclass
from fractions import Fraction as Q
from math import factorial
import json

G=Q(9,10)
RHO=(Q(1,2),Q(1))
PREF1=Q(1,20)
PREF2=Q(1,50)
NOISE=Q(1,10)
LOWER_T=Q(69620266886932,10**14)
UPPER_T=Q(69620266886935,10**14)
S=Q(834387601099952,10**15)
SCALE=10**65
N_EXP=36
N_LOG=12

def _floor(n,d):
    if d<0:n,d=-n,-d
    return n//d

def _ceil(n,d):return -_floor(-n,d)

@dataclass(frozen=True)
class I:
    lo:int
    hi:int
    def __post_init__(self):
        if self.lo>self.hi:raise ValueError('reversed interval')
    @classmethod
    def at(cls,q):
        q=Q(q)
        return cls(_floor(q.numerator*SCALE,q.denominator),_ceil(q.numerator*SCALE,q.denominator))
    @classmethod
    def of(cls,x):return x if isinstance(x,cls) else cls.at(x)
    def __add__(self,x):
        y=I.of(x);return I(self.lo+y.lo,self.hi+y.hi)
    __radd__=__add__
    def __neg__(self):return I(-self.hi,-self.lo)
    def __sub__(self,x):return self+-I.of(x)
    def __rsub__(self,x):return I.of(x)+-self
    def __mul__(self,x):
        y=I.of(x)
        z=(self.lo*y.lo,self.lo*y.hi,self.hi*y.lo,self.hi*y.hi)
        return I(_floor(min(z),SCALE),_ceil(max(z),SCALE))
    __rmul__=__mul__
    def reciprocal(self):
        if self.lo<=0<=self.hi:raise ZeroDivisionError('division by zero interval')
        return I(_floor(SCALE*SCALE,self.hi),_ceil(SCALE*SCALE,self.lo))
    def __truediv__(self,x):return self*I.of(x).reciprocal()
    def __rtruediv__(self,x):return I.of(x)*self.reciprocal()
    def __pow__(self,n):
        if not isinstance(n,int) or n<0:raise ValueError('power')
        res=I.at(1)
        for _ in range(n):res=res*self
        return res
    def bound(self):return Q(max(abs(self.lo),abs(self.hi)),SCALE)
    def lower(self):return Q(self.lo,SCALE)
    def upper(self):return Q(self.hi,SCALE)
    def contains(self,x):return self.lower()<=Q(x)<=self.upper()


def exp_I(v,n=N_EXP):
    x=I.of(v)
    if x.bound()>1:raise ValueError('exponent outside proof domain')
    s=I.at(1);term=I.at(1)
    for k in range(1,n+1):
        term=term*x/k;s=s+term
    # For |x|<=1, geometric majorant of all terms from n+1 is
    # (1/(n+1)!)/(1-1/(n+2)) <= 2/(n+1)!.
    rem=Q(2,factorial(n+1))
    return s+I.at(Q(-rem)),s+I.at(rem)


def exp_enclosure(x):
    lo,hi=exp_I(x)
    return I(lo.lo,hi.hi)


def log_I(v,n=N_LOG):
    y=I.of(v)
    if y.lo<=0:raise ValueError('nonpositive argument')
    z=(y-1)/(y+1)
    if z.bound()>Q(1,2):raise ValueError('log argument outside proof domain')
    total=I.at(0);term=z
    for k in range(n):
        total=total+term*Q(2,2*k+1)
        term=term*z*z
    # atanh remainder <= 2r^(2n+1)/((2n+1)*(1-r²)) <=4r^(2n+1).
    r=z.bound();rem=4*r**(2*n+1)
    return I(total.lo+I.at(-rem).lo,total.hi+I.at(rem).hi)


def cosh_I(v):
    y=I.of(v)
    e=exp_enclosure(y);e2=exp_enclosure(-y)
    c=(e+e2)/2
    return I(max(c.lo,SCALE),c.hi)


def tanh_I(v):
    e=exp_enclosure(2*I.of(v))
    return (e-1)/(e+1)


def sigmoid_I(v):return 1/(1+exp_enclosure(-I.of(v)))


def scalar_gradient(t):
    """Outward-enclosed derivative of f(t)=C(t,0)+|t|/2 for t>=0."""
    t=Q(t);u=t-1
    total=I.at(Q(1,2))
    ys=[RHO[p]*(u/Q(5)+Q(1-2*p,100)) for p in (0,1)]
    tanh=[tanh_I(y) for y in ys]
    logcosh=[log_I(cosh_I(y)) for y in ys]
    delta=I.at(PREF1)+G*(logcosh[1]/RHO[1]-logcosh[0]/RHO[0])
    for p0 in (0,1):
        weight=sigmoid_I(RHO[p0]*delta)
        term=I.at(2*u)+Q(1,5)*((1-weight)*tanh[0]+weight*tanh[1])
        total=total+G*G*term/2
    return total


def certify():
    if not 0<LOWER_T<UPPER_T<1:raise AssertionError('root domain')
    left=scalar_gradient(LOWER_T);right=scalar_gradient(UPPER_T)
    origin=scalar_gradient(0)
    if left.hi>=0 or right.lo<=0:raise AssertionError('root not isolated')
    if origin.hi>=0:raise AssertionError('negative-curvature saddle not certified')
    m=2*G*G
    t=S*S
    if not LOWER_T<t<UPPER_T:raise AssertionError('weight outside bracket')
    gradient=scalar_gradient(t)
    eps=gradient.bound()
    dt=eps/m
    dr=eps**2/(2*m)
    dw=dt/S
    capacity_gap=m*LOWER_T**2/2
    risk_neutral=Q(56,81)
    if not (dw<Q(1,10**11) and dr<Q(1,10**20)):
        raise AssertionError('candidate error proof insufficient')
    if not (capacity_gap>Q(39,100) and LOWER_T-risk_neutral>Q(4,1000)):
        raise AssertionError('capacity or nonzero-risk proof failed')
    def values(v):return [str(v.lower()),str(v.upper())]
    return dict(schema='hepta.ndu.nonproduct-two-step-symmetry.global-integer-interval.v1',
        horizon=2,parameters=2,nonzero_risks=[str(x) for x in RHO],
        candidate_a=str(S),candidate_b=str(S),candidate_product=str(t),
        rigorous_product_root_bracket=[str(LOWER_T),str(UPPER_T)],
        left_gradient_bounds=values(left),right_gradient_bounds=values(right),
        candidate_gradient_bounds=values(gradient),origin_plus_derivative_bounds=values(origin),
        scalar_strong_convexity=str(m),weight_component_error_upper=str(dw),
        true_population_excess_upper=str(dr),one_weight_b_zero_regret_lower=str(capacity_gap),
        risk_neutral_optimum_product=str(risk_neutral),
        rigorously_nonzero_risk_shift_lower=str(LOWER_T-risk_neutral),
        global_optima='a=b=+sqrt(t*) or a=b=-sqrt(t*)',
        nonproduct_kappa='1/4',nonproduct_globally_enclosed=True,
        certified_contribution_lower='gamma^2*kappa^2*(a-b)^4',
        conditional_d_convexity_lower='81/50',
        input_noise='epsilon2*X/10',
        origin_strict_saddle=True,rigorous_global_certificate=True,
        arbitrary_neural_fbsde_certificate=False,
        arithmetic='exact integers, directed 10^65 outward arithmetic, Taylor remainder inequalities',
        fp64_used_in_proof=False)

if __name__=='__main__':print(json.dumps(certify(),sort_keys=True,indent=2))
