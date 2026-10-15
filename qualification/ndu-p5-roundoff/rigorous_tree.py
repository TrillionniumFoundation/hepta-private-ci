"""Research-only, exact-integer outward interval oracle for one registered binary tree.

This module does not call the production/nominal map. All coefficients are treated
as EXACT IEEE-754 binary64 inputs (Fraction.from_float). The discrete law is
X(child)=X(parent)+a*(T/steps)*Y(parent)+eps*sigma*sqrt(T/steps)
Y(parent)=(mean(Ychildren)+(T/steps)*beta*tanh(Xparent))/(1+(T/steps)*lam).

Every arithmetic operation in this reference is enclosed by floor/ceil on an
integer grid. The exp/tanh enclosure uses a positive Taylor polynomial and a
proved geometric upper bound on the remainder. It is NOT a continuous-time FBSDE
or model-source/safety/production certificate. An audit of the implementation is
still required before claiming formal machine verification.
"""
from __future__ import annotations
from dataclasses import dataclass
from fractions import Fraction
from math import isqrt, isfinite
from functools import lru_cache

SHIFT=112
SCALE=1<<SHIFT
MAX_EXP_ARG=32*SCALE
SERIES_TERMS=96

class Unqualified(ValueError):
    pass

def ceildiv(a,b):
    if b<=0: raise Unqualified('positive divisor required')
    return -((-a)//b)

@dataclass(frozen=True)
class I:
    lo:int
    hi:int
    def __post_init__(self):
        if type(self.lo) is not int or type(self.hi) is not int or self.lo>self.hi:
            raise Unqualified('invalid interval')

def interval_fraction(f):
    f=Fraction(f)
    return I((f.numerator*SCALE)//f.denominator,ceildiv(f.numerator*SCALE,f.denominator))

def f64(v):
    if type(v) not in (int,float) or not isfinite(v):
        raise Unqualified('finite IEEE754 value required')
    return Fraction.from_float(float(v))

def iv(v):
    return interval_fraction(f64(v))

def add(a,b):return I(a.lo+b.lo,a.hi+b.hi)
def neg(a):return I(-a.hi,-a.lo)
def sub(a,b):return add(a,neg(b))

def mul(a,b):
    c=(a.lo*b.lo,a.lo*b.hi,a.hi*b.lo,a.hi*b.hi)
    return I(min(c)//SCALE,ceildiv(max(c),SCALE))

def divide(a,b):
    if b.lo<=0:raise Unqualified('non-positive denominator / undefined interval')
    c=((n,d) for n in (a.lo,a.hi) for d in (b.lo,b.hi))
    quot=list(c)
    return I(min((n*SCALE)//d for n,d in quot),max(ceildiv(n*SCALE,d) for n,d in quot))

def half(a):return I(a.lo//2,ceildiv(a.hi,2))

def sqrt_fraction(f):
    f=Fraction(f)
    if f<=0:raise Unqualified('positive duration needed')
    scaled_num=f.numerator*SCALE*SCALE
    scaled_den=f.denominator
    lo=isqrt(scaled_num//scaled_den)
    hi=lo if lo*lo*scaled_den==scaled_num else lo+1
    return I(lo,hi)

@lru_cache(maxsize=131072)
def _positive_tanh_point(t):
    """Enclose tanh(t/SCALE), t >= 0, using exp(2t) positive Taylor series.

    E_N= sum_{k=0}^N s^k/k!, s=2t/SCALE>=0.
    E_N <= exp(s) <= E_N+term_{N+1}/(1-s/(N+2)) for N+2>s.
    All recurrence and remainder operations are rounded outward in integers.
    tanh(x)=(exp(2x)-1)/(exp(2x)+1) monotonically increases with exp.
    """
    if t<0 or 2*t>MAX_EXP_ARG:raise Unqualified('tanh argument outside certified bound')
    if t==0:return I(0,0)
    arg=2*t
    term=I(SCALE,SCALE)
    total=term
    for k in range(1,SERIES_TERMS+1):
        term=I((term.lo*arg)//(k*SCALE),ceildiv(term.hi*arg,k*SCALE))
        total=add(total,term)
    # Positive series tail, ratio for k >= N+2 bounded by arg/(N+2).
    nxt=ceildiv(term.hi*arg,(SERIES_TERMS+1)*SCALE)
    denominator=(SERIES_TERMS+2)*SCALE-arg
    if denominator<=0:raise Unqualified('Taylor tail ratio not contractive')
    tail=ceildiv(nxt*(SERIES_TERMS+2)*SCALE,denominator)
    high=total.hi+tail
    low=total.lo
    if low<SCALE:raise Unqualified('invalid exp enclosure')
    return I(((low-SCALE)*SCALE)//(low+SCALE),
             ceildiv((high-SCALE)*SCALE,high+SCALE))

def tanh_point(t):
    return _positive_tanh_point(t) if t>=0 else neg(_positive_tanh_point(-t))

def tanh_interval(a):
    # Strict monotonicity lets us evaluate only the endpoints.
    return I(tanh_point(a.lo).lo,tanh_point(a.hi).hi)


def exact_q(row,option):
    a=f64(option['a']);T=f64(row['horizon']);beta=f64(row['beta'])
    return a*T*(1+beta*T)


def global_map_bounds(row,option,y):
    """Independent breadth-first state and backward payoff operator enclosure."""
    if type(row) is not dict or type(option) is not dict:
        raise Unqualified('unbound source')
    steps=row['steps']
    if type(steps) is not int or not 1<=steps<=9 or type(y) not in (list,tuple) or len(y)!=(1<<steps)-1:
        raise Unqualified('incomplete public information tree')
    for field in ('x0','horizon','sigma','beta','lam'):
        f64(row[field])
    for field in ('a','cost'):
        f64(option[field])
    if not 0<=float(option['a'])<=4 or not 0<=float(row['beta'])<=4 or not 0<=float(row['lam'])<=4 or not 0<=float(row['sigma'])<=4 or abs(float(row['x0']))>2 or not 0<float(row['horizon'])<=2:
        raise Unqualified('unsupported operating region')
    q=exact_q(row,option)
    if not 0<=q<Fraction(95,100):
        raise Unqualified('global contraction not admitted')
    h=f64(row['horizon'])/steps
    ph=interval_fraction(h)
    coeff=mul(iv(option['a']),ph)
    nois=mul(iv(row['sigma']),sqrt_fraction(h))
    b=mul(ph,iv(row['beta']))
    denom=add(I(SCALE,SCALE),mul(ph,iv(row['lam'])))
    yy=[iv(t) for t in y]
    n=len(yy)
    xx=[I(0,0)]*(2*n+1)
    xx[0]=iv(row['x0'])
    for i in range(n):
        mid=add(xx[i],mul(coeff,yy[i]))
        xx[2*i+1]=sub(mid,nois)
        xx[2*i+2]=add(mid,nois)
    backward=[None]*n+[tanh_interval(x) for x in xx[n:]]
    for i in reversed(range(n)):
        mean=half(add(backward[2*i+1],backward[2*i+2]))
        drift=mul(b,tanh_interval(xx[i]))
        backward[i]=divide(add(mean,drift),denom)
    return backward[:n],q


def action_bounds(row,option,y):
    m,q=global_map_bounds(row,option,y)
    yiv=[iv(t) for t in y]
    residual=max(max(abs(sub(x,z).lo),abs(sub(x,z).hi)) for x,z in zip(yiv,m))
    # Conservative contraction: a*T*(1+beta*T). Use exact rational q.
    dq=Fraction(1,1)-q
    if dq<=0:raise Unqualified('zero contraction margin')
    # The residual is already in scaled integer ticks; round radius upwards.
    radius=ceildiv(residual*dq.denominator,dq.numerator)
    center=sub(yiv[0],iv(option['cost']))
    return {'action_id':option['action_id'],
            'lower_ticks':center.lo-radius,'upper_ticks':center.hi+radius,
            'radius_ticks':radius,'residual_ticks':residual,
            'q_exact_numerator':q.numerator,'q_exact_denominator':q.denominator}


def resolve(entries):
    all_entries=[{'action_id':'abstain','lower_ticks':0,'upper_ticks':0}]+entries
    winner=max(all_entries,key=lambda x:x['lower_ticks'])
    runner_up=max(x['upper_ticks'] for x in all_entries if x['action_id']!=winner['action_id'])
    return (winner['action_id'],winner['lower_ticks']-runner_up) if winner['lower_ticks']>runner_up else (None,winner['lower_ticks']-runner_up)
