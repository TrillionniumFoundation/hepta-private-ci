"""Exact rational research oracle: NOT a production stochastic FBSDE solver."""
from fractions import Fraction as Q
from dataclasses import dataclass
from functools import lru_cache

@dataclass(frozen=True)
class Certificate:
    status: str
    initial_y: Q | None
    interface_jumps: tuple
    terminal_residual: Q | None
    globally_solved: bool

def _q(x):
    if isinstance(x, bool):
        raise ValueError("boolean is not rational")
    return Q(x)

def global_boundary(x0, g, segments):
    """dX=Ydt, dY=0, X0=x0, YT=g XT; regular-field admission only."""
    x0,g=_q(x0),_q(g)
    hs=tuple(map(_q,segments))
    if not hs or any(h<=0 for h in hs):
        raise ValueError("positive durations required")
    T=sum(hs,Q(0))
    factor=1-g*T
    if factor==0:
        return Certificate("non_unique" if g*x0==0 else "no_solution",None,(),None,False)
    y=g*x0/factor
    x=x0
    for h in hs:
        x+=h*y
    residual=y-g*x
    regular=g<=0 or g*T<1
    return Certificate("unique_regular" if regular else "nonregular_unique",
                       y,tuple(Q(0) for _ in hs[1:]),residual,regular and residual==0)

def wrong_reset(x0,g,segments):
    """Invalid local-terminal resets: never promote even with zero residual."""
    x,g=_q(x0),_q(g)
    hs=tuple(map(_q,segments))
    if not hs or any(h<=0 for h in hs):
        raise ValueError("positive durations required")
    ys=[]
    rs=[]
    for h in hs:
        if 1-g*h==0:
            raise ValueError("local pole")
        y=g*x/(1-g*h)
        x+=h*y
        ys.append(y)
        rs.append(y-g*x)
    return dict(slopes=tuple(ys),local_terminal_residuals=tuple(rs),
                interface_jumps=tuple(b-a for a,b in zip(ys,ys[1:])),
                terminal_residual=rs[-1],globally_solved=False)

def belief_tree(prior,cost):
    """Exact two-Bernoulli public-history decision tree, with stop/submit/observe."""
    p=tuple(map(_q,prior))
    c=tuple(map(_q,cost))
    if len(p)!=2 or len(c)!=2 or any(not 0<=v<=1 for v in p) or any(v<0 for v in c):
        raise ValueError("unsupported probability or cost")
    @lru_cache(None)
    def solve(s):
        pp=(p[0] if s[0] is None else Q(s[0]))*(p[1] if s[1] is None else Q(s[1]))
        choices=[("stop",Q(0)),("true",2*pp-1),("false",1-2*pp)]
        for i in range(2):
            if s[i] is None:
                a=list(s);b=list(s);a[i]=0;b[i]=1
                choices.append((f"observe_{i}",(1-p[i])*solve(tuple(a))[0]+p[i]*solve(tuple(b))[0]-c[i]))
        action,value=max(choices,key=lambda kv:kv[1])
        return value,action
    value,action=solve((None,None))
    return dict(value=value,action=action,states=solve.cache_info().currsize)
