"""Research-only outward interval tanh through 2**6 argument reduction.

For u=2|x|/64 <= 1/2, a nonnegative 16-term exp Taylor sum plus
term_17/(1-u/18) encloses exp(u). Six outward interval squares enclose
exp(2|x|), giving tanh(x) through the monotone ratio (E-1)/(E+1).
All inputs are exact binary64 values represented on the inherited Q112 grid.
This is a mathematical reference for one discrete tree, not a continuous-time
FBSDE proof, a GPU guarantee, a compiler-independent formal proof, or a production API.
"""
from functools import lru_cache
from fractions import Fraction
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'ndu-p5-roundoff'))
from rigorous_tree import I,SCALE,MAX_EXP_ARG,Unqualified,add,neg,mul,divide,sub,ceildiv
from rigorous_tree import f64,iv,interval_fraction,sqrt_fraction,half

REDUCTIONS=6
TERMS=16

@lru_cache(maxsize=131072)
def _positive(t):
    if type(t) is not int or t<0 or 2*t>MAX_EXP_ARG:raise Unqualified('out of tanh bound')
    if t==0:return I(0,0)
    # 2*t/(2**REDUCTIONS) lies inside this outward-rounded interval.
    raw=2*t
    z=I(raw//(1<<REDUCTIONS),ceildiv(raw,(1<<REDUCTIONS)))
    # use positive interval argument throughout recurrence to enclose exp.
    term=I(SCALE,SCALE); total=term
    for k in range(1,TERMS+1):
        term=I(term.lo*z.lo//(k*SCALE),ceildiv(term.hi*z.hi,k*SCALE))
        total=add(total,term)
    nxt=ceildiv(term.hi*z.hi,(TERMS+1)*SCALE)
    den=(TERMS+2)*SCALE-z.hi
    if den<=0:raise Unqualified('exp remainder not contractive')
    tail=ceildiv(nxt*(TERMS+2)*SCALE,den)
    e=I(total.lo,total.hi+tail)
    for _ in range(REDUCTIONS):e=mul(e,e)
    if e.lo<SCALE:raise Unqualified('exp below one')
    return I((e.lo-SCALE)*SCALE//(e.lo+SCALE),ceildiv((e.hi-SCALE)*SCALE,e.hi+SCALE))

def tanh_point(t):return _positive(t) if t>=0 else neg(_positive(-t))
def tanh_interval(x):return I(tanh_point(x.lo).lo,tanh_point(x.hi).hi)


def fast_action_bounds(row, option, y):
    steps = row['steps']
    if type(steps) is not int or not 1<=steps<=9 or type(y) not in (tuple,list) or len(y)!=(1<<steps)-1:
        raise Unqualified('incomplete registered discrete tree')
    for field in ('x0','horizon','sigma','beta','lam'):f64(row[field])
    for field in ('a','cost'):f64(option[field])
    if not 0<=float(option['a'])<=4 or not 0<=float(row['beta'])<=4 or not 0<=float(row['lam'])<=4 or not 0<=float(row['sigma'])<=4 or abs(float(row['x0']))>2 or not 0<float(row['horizon'])<=2:
        raise Unqualified('unsupported operating region')
    q=f64(option['a'])*f64(row['horizon'])*(1+f64(row['beta'])*f64(row['horizon']))
    if not 0<=q<Fraction(95,100):raise Unqualified('global contraction not admitted')
    h=f64(row['horizon'])/steps
    ph=interval_fraction(h)
    coeff=mul(iv(option['a']),ph)
    nois=mul(iv(row['sigma']),sqrt_fraction(h))
    b=mul(ph,iv(row['beta']))
    den=add(I(SCALE,SCALE),mul(ph,iv(row['lam'])))
    yy=[iv(t) for t in y];n=len(yy)
    xx=[I(0,0)]*(2*n+1);xx[0]=iv(row['x0'])
    for i in range(n):
        mid=add(xx[i],mul(coeff,yy[i]))
        xx[2*i+1]=sub(mid,nois);xx[2*i+2]=add(mid,nois)
    backwards=[None]*n+[tanh_interval(x) for x in xx[n:]]
    for i in reversed(range(n)):
        mean=half(add(backwards[2*i+1],backwards[2*i+2]))
        backwards[i]=divide(add(mean,mul(b,tanh_interval(xx[i]))),den)
    yiv=[iv(t) for t in y]
    residual=max(max(abs(sub(v,z).lo),abs(sub(v,z).hi)) for v,z in zip(yiv,backwards[:n]))
    rem=1-q
    radius=ceildiv(residual*rem.denominator,rem.numerator)
    center=sub(yiv[0],iv(option['cost']))
    return dict(action_id=option['action_id'],lower_ticks=center.lo-radius,
                upper_ticks=center.hi+radius,radius_ticks=radius,
                residual_ticks=residual,q_exact_numerator=q.numerator,q_exact_denominator=q.denominator)
