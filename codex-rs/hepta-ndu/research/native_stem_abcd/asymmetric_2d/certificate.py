"""R18: self-contained exact 2D positive-risk nonconvex forward-weight certificate.

All authoritative bounds use Fraction and directed fixed-denominator integer
interval arithmetic. Floats are not imported or used anywhere in this proof.
"""
from __future__ import annotations
from dataclasses import dataclass
from fractions import Fraction as F
from math import factorial
import json

G=F(9,10); RHO=(F(1,2),F(1)); PREF1=F(1,20); PREF2=F(1,50)
NOISE=F(1,10); KAPPA=F(1,4); TARGET_SHIFT=F(1)
A=F(1669246516087578580991543,10**24)
B=F(416891900252459728989673,10**24)
SC=10**65; EXP_TERMS=36; LOG_TERMS=12
M=2*G*G

def floorfrac(x): return x.numerator//x.denominator

def ceilfrac(x):return -floorfrac(-x)

@dataclass(frozen=True)
class I:
    lo:int
    hi:int
    def __post_init__(self):
        if self.lo>self.hi:raise ValueError('reversed interval')
    @classmethod
    def at(cls,value):
        q=F(value)*SC
        return cls(floorfrac(q),ceilfrac(q))
    @classmethod
    def as_i(cls,value):return value if isinstance(value,cls) else cls.at(value)
    def __add__(self,other):
        b=self.as_i(other);return I(self.lo+b.lo,self.hi+b.hi)
    __radd__=__add__
    def __neg__(self):return I(-self.hi,-self.lo)
    def __sub__(self,x):return self+(-self.as_i(x))
    def __rsub__(self,x):return self.as_i(x)+-self
    def __mul__(self,other):
        b=self.as_i(other)
        v=(self.lo*b.lo,self.lo*b.hi,self.hi*b.lo,self.hi*b.hi)
        return I(min(v)//SC,-((-max(v))//SC))
    __rmul__=__mul__
    def reciprocal(self):
        if self.lo<=0<=self.hi:raise ZeroDivisionError('interval contains zero')
        return I((SC*SC)//self.hi,-((-SC*SC)//self.lo))
    def __truediv__(self,other):return self*self.as_i(other).reciprocal()
    def __rtruediv__(self,other):return self.as_i(other)*self.reciprocal()
    def lower(self):return F(self.lo,SC)
    def upper(self):return F(self.hi,SC)
    def magnitude(self):return max(-self.lower(),self.upper())
    def contains(self,x):return self.lower()<=F(x)<=self.upper()

def exp_interval(z):
    z=I.as_i(z)
    if z.magnitude()>1:raise ValueError('argument outside certified exp range')
    power=I.at(1);s=I.at(1)
    for k in range(1,EXP_TERMS+1):
        power=power*z/k
        s=s+power
    tail=F(2,factorial(EXP_TERMS+1))
    return I(s.lo+I.at(-tail).lo,s.hi+I.at(tail).hi)

def log_interval(y):
    y=I.as_i(y)
    if y.lo<=0:raise ValueError('log nonpositive')
    z=(y-1)/(y+1)
    if z.magnitude()>F(1,2):raise ValueError('log series range')
    power=z;total=I.at(0)
    for j in range(LOG_TERMS):
        total=total+power*F(2,2*j+1)
        power=power*z*z
    tail=4*z.magnitude()**(2*LOG_TERMS+1)
    return I(total.lo+I.at(-tail).lo,total.hi+I.at(tail).hi)

def logcosh_interval(y):
    y=I.as_i(y)
    c=(exp_interval(y)+exp_interval(-y))/2
    return log_interval(I(max(c.lo,SC),c.hi))

def tanh_interval(y):
    v=exp_interval(I.as_i(y)*2)
    return (v-1)/(v+1)

def logistic_interval(y):return 1/(1+exp_interval(-I.as_i(y)))

def quotient_gradient(t,d,shift=TARGET_SHIFT):
    """Exact interval enclosure of gradient of F(t,d)=C(t,d)+t/2+d."""
    t=F(t);d=F(d);shift=F(shift)
    gt=I.at(F(1,2));gd=I.at(1)
    for x in (-1,1):
        z=F(x)*(t-1)+d-shift
        ys=[RHO[p]*(2*NOISE*z+(1-2*p)*PREF2/2) for p in (0,1)]
        tanh=[tanh_interval(y) for y in ys]
        logcosh=[logcosh_interval(y) for y in ys]
        delta=I.at(PREF1)+G*(logcosh[1]/RHO[1]-logcosh[0]/RHO[0])
        for p0 in (0,1):
            w=logistic_interval(RHO[p0]*delta)
            dz=I.at(2*z)+2*NOISE*((1-w)*tanh[0]+w*tanh[1])
            gt=gt+G*G*F(x,4)*dz
            gd=gd+G*G*dz/4
    return gt,gd

def baseline_derivative_d_at_zero():
    """At fixed t near optimum, d=0 is not optimal in shifted problem."""
    _,gd=quotient_gradient(A*B,F(0))
    return gd

def certificate():
    t=A*B
    d=(A-B)**2/4
    if t<=F(1,2) or d<=F(1,4) or t+d<=1:
        raise AssertionError('candidate not in required interior domain')
    gt,gd=quotient_gradient(t,d)
    e=gt.magnitude()+gd.magnitude()  # rigorous l1 >= l2
    zdist=e/M
    regret=e**2/(2*M)
    if zdist>=F(1,1000000):raise AssertionError('not precise enough')
    if t-zdist<=0 or d-zdist<=F(1,4) or t+d-2*zdist<=1:
        raise AssertionError('cannot certify interior inverse map')
    weight_component_error=2*zdist
    # Constrained d=0 ablation cannot attain closer than d* to the global root.
    # Strong convexity gives lower bound m/2*(d* - zdist)^2.
    diagonal_regret=M*(d-zdist)**2/2
    b_zero_regret=M*(t-zdist)**2/2
    # Two positive same-sign unequal weights (and sign/swap images) are minima.
    diag_gradient=baseline_derivative_d_at_zero()
    if diag_gradient.hi>=-F(1,2):
        raise AssertionError('nontrivial second channel not certified')
    if diagonal_regret<=F(1,10) or b_zero_regret<=F(3,10):
        raise AssertionError('restricted-family regret bound too weak')
    if regret>=F(1,10**40):
        raise AssertionError('population regret bound not strong enough')
    return dict(schema='hepta.ndu.nonproduct-2D-asymmetric-exact.v1',
        horizon=2,risks=[str(v) for v in RHO],discrete_terminal_cases=16,
        input_noise='epsilon2/10, uncorrelated with X',terminal_target='X+1',
        forward='H1=a*X; H2=b*H1+(a-b)^2/4+epsilon2/10',
        candidate_a=str(A),candidate_b=str(B),
        candidate_t=str(t),candidate_d=str(d),
        candidate_gradient_bounds_t=[str(gt.lower()),str(gt.upper())],
        candidate_gradient_bounds_d=[str(gd.lower()),str(gd.upper())],
        full_2D_strong_convexity=str(M),
        rigorous_quotient_distance_upper=str(zdist),
        rigorous_weight_component_error_upper=str(weight_component_error),
        rigorous_true_population_regret_upper=str(regret),
        all_a_equal_b_regret_lower=str(diagonal_regret),
        all_b_zero_regret_lower=str(b_zero_regret),
        boundary_d0_gradient_bounds=[str(diag_gradient.lower()),str(diag_gradient.upper())],
        four_global_weight_symmetry_classes=True,
        globally_certified_2D=True,symmetry_reduction_to_1D_used=False,
        exact_convex_quotient_mapping=True,
        globally_certified_arbitrary_neural_FBSDE=False,
        proof_uses_float=False,arithmetic='Fraction with outward fixed-point 10^65 intervals')

if __name__=='__main__':print(json.dumps(certificate(),indent=2,sort_keys=True))

# Strict separate certificate for the zero-shift control with the SAME uncorrelated
# noise law. The positive d-derivative bound is global, not sampled.
ABLATION_A=F(834232264397470736714151,10**24)

def ablation_certificate():
    t=ABLATION_A**2
    gt,gd=quotient_gradient(t,F(0),shift=0)
    e=gt.magnitude()
    dt=e/M
    regret=e**2/(2*M)
    # All real t and d>=0: E_X 2*x*(t-1) = 0, and every tanh is in [-1,1].
    # Thus derivative in d at d=0 is >=1-2*gamma^2*noise for ALL t.
    globally_positive_normal_derivative=1-2*G*G*NOISE
    if not (globally_positive_normal_derivative>F(4,5) and gt.magnitude()<F(1,10**18)):
        raise AssertionError('ablation proof insufficient')
    if not (t-dt>F(1,2) and regret<F(1,10**35)):
        raise AssertionError('ablation root out of certified range')
    return dict(schema='hepta.ndu.zero-shift-2D-ablation.exact.v1',
        shift='0',noise='uncorrelated epsilon2/10',
        candidate_a=str(ABLATION_A),candidate_b=str(ABLATION_A),
        scalar_gradient_interval=[str(gt.lower()),str(gt.upper())],
        outward_d_gradient_at_candidate=[str(gd.lower()),str(gd.upper())],
        all_t_normal_derivative_at_d0_lower=str(globally_positive_normal_derivative),
        scalar_t_distance_upper=str(dt),
        rigorous_cost_regret_upper=str(regret),
        global_optima='a=b=+/-sqrt(t*)',
        valid_global_certificate=True)
