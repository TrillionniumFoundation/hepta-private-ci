"""Bounded discrete nonlinear fully coupled FBSDE laboratory, DENY_ALL.

Registered binary increments (NOT a continuous-time Brownian FBSDE theorem):
X_{k+1} = X_k + a*h*Y_k + sigma*sqrt(h)*epsilon_{k+1}
Y_k = (E_k[Y_{k+1}] + h*beta*tanh(X_k))/(1+h*lam)
Y_T = tanh(X_T); epsilon in {-1,+1}, equally likely.

Forward state depends on the backward utility; the whole 2^K tree is coupled.
Contraction profile q=a*T*(1+beta*T)<0.95 is an intentionally conservative
admission limit used ONLY for the registered discrete map. Roundoff not enclosed.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from time import process_time_ns, perf_counter_ns

class Unsupported(ValueError):
    pass


def ensure(b, why):
    if not b:
        raise Unsupported(why)


@dataclass(frozen=True)
class Profile:
    steps: int = 4
    horizon: float = .8
    a: float = .35
    beta: float = .4
    lam: float = .2
    sigma: float = .3
    x0: float = .6

    def validate(self):
        ensure(type(self.steps) is int and 1 <= self.steps <= 9, "steps")
        for field in ('horizon', 'a', 'beta', 'lam', 'sigma', 'x0'):
            v=getattr(self,field)
            ensure(type(v) in (int,float) and math.isfinite(v), "nonfinite "+field)
        ensure(0 < self.horizon <= 2 and all(0 <= getattr(self,f) <= 4 for f in ('a','beta','lam','sigma'))
               and abs(self.x0) <= 2, "operating range")
        ensure(self.q < .95, "global discrete contraction margin not supported")
        return self

    @property
    def h(self):
        return self.horizon/self.steps

    @property
    def q(self):
        return self.a*self.horizon*(1+self.beta*self.horizon)


def check_vector(p, values):
    ensure(type(values) in (list,tuple) and len(values)==2**p.steps-1 and
           all(type(v) in (int,float) and math.isfinite(v) for v in values), "complete bounded Y tree")


def transport(p, y):
    p.validate(); check_vector(p,y)
    n=len(y)
    states=[0.0]*(2*n+1)
    states[0]=float(p.x0)
    noise=p.sigma*math.sqrt(p.h)
    for k,v in enumerate(y):
        mid=states[k]+p.a*p.h*v
        states[2*k+1],states[2*k+2]=mid-noise,mid+noise
    ensure(all(math.isfinite(z) for z in states), "forward overflow")
    return states


def mapping(p,y,*,reset_depth=None):
    """The optional interior terminal reset is a WRONG-control map."""
    states=transport(p,y)
    n=len(y)
    v=[0.0]*n+[math.tanh(x) for x in states[n:]]
    for idx in range(n-1,-1,-1):
        depth=(idx+1).bit_length()-1
        if reset_depth is not None and depth==reset_depth:
            v[idx]=math.tanh(states[idx])
        else:
            v[idx]=((v[2*idx+1]+v[2*idx+2])/2+
                    p.h*p.beta*math.tanh(states[idx]))/(1+p.lam*p.h)
    return v[:n]


def defects(p,y):
    """Re-evaluate the ORIGINAL global problem, not a self-reported local loss."""
    p.validate();check_vector(p,y)
    states=transport(p,y); mapped=mapping(p,y)
    n=len(y)
    utility=list(y)+[math.tanh(x) for x in states[n:]]
    local=0.
    covariance=0.
    centered=0.
    zs=[]
    for i in range(n):
        left,right=utility[2*i+1],utility[2*i+2]
        z=(right-left)/(2*math.sqrt(p.h))
        zs.append(z)
        # Sigma=E[(sqrt(h) epsilon)^2 | F_k]=h.
        # B=E[(Ychild-E[Ychild])sqrt(h)epsilon | F_k].
        b=(right-left)*math.sqrt(p.h)/2
        covariance=max(covariance,abs(z*p.h-b))
        f=p.lam*y[i]-p.beta*math.tanh(states[i])
        for sign,child in ((-1,left),(1,right)):
            local=max(local,abs(child-y[i]-p.h*f-z*math.sqrt(p.h)*sign))
        centered=max(centered,abs((left+right)/2-(y[i]+p.h*f)))
    residual=max(abs(a-b) for a,b in zip(y,mapped))
    return dict(full_fixed_point_residual=residual,
                local_bsde_residual=local,
                conditional_drift_residual=centered,
                z_sigma_equals_b_residual=covariance,
                terminal_residual=max(abs(u-math.tanh(x)) for u,x in zip(utility[n:],states[n:])),
                conditional_driver_variance=p.h,
                nominal_Y_error_bound=residual/(1-p.q),
                nominal_X_error_bound=p.a*p.horizon*residual/(1-p.q),
                float_roundoff_rigorously_enclosed=False,
                continuous_time_error_certified=False)


def solve(p,*,tol=1e-9,max_calls=512,reset_depth=None):
    p.validate()
    ensure(type(tol) in (int,float) and 1e-12 <= tol <= 1e-3 and
           type(max_calls) is int and 1 <= max_calls <= 512, "bounded solver")
    if reset_depth is not None:
        ensure(type(reset_depth) is int and 1<=reset_depth<p.steps, "reset range")
    n=2**p.steps-1
    y=[0.0]*n
    cpu=process_time_ns();wall=perf_counter_ns()
    for calls in range(1,max_calls+1):
        target=mapping(p,y,reset_depth=reset_depth)
        residual=max(abs(a-b) for a,b in zip(y,target))
        if residual/(1-p.q)<=tol:
            d=defects(p,y)
            # A wrong-reset candidate is never certified from the altered map.
            return dict(y=y,x=transport(p,y),calls=calls,
                        cpu_ns=process_time_ns()-cpu,wall_ns=perf_counter_ns()-wall,
                        reset_control=reset_depth is not None,
                        accepted_global_discrete=(reset_depth is None and d['nominal_Y_error_bound']<=tol and
                            d['local_bsde_residual']<=tol*2 and d['z_sigma_equals_b_residual']<=tol),
                        profile=p.__dict__,defects=d,
                        production_accepted=False,authority='DENY_ALL')
        y=target
    raise Unsupported('iteration exhausted, not solved')


def direct_uncontrolled(p):
    """Cheap exact backward recursion for the a=0 special case (one map call)."""
    p.validate()
    ensure(p.a==0, 'cheap baseline requires no coupling')
    n=2**p.steps-1
    y=[0.0]*n
    cpu=process_time_ns();wall=perf_counter_ns()
    result=mapping(p,y)
    d=defects(p,result)
    ensure(d['full_fixed_point_residual']<1e-12, 'uncontrolled map not exact')
    return dict(y=result,calls=1,cpu_ns=process_time_ns()-cpu,
                wall_ns=perf_counter_ns()-wall,defects=d,
                production_accepted=False,authority='DENY_ALL')
