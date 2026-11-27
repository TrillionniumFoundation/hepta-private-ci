"""Finite nonzero-noise nonlinear fully-coupled FBSDE, exact rational shadow study.

X_(k+1) = X_k + a*h*phi(Y_k) + sigma*m_(k+1)
(1+lam*h)*Y_k = E[Y_(k+1)|F_k] + beta*h*phi(X_k)
Y_T = g*phi(X_T),  phi(x)=x/(1+x*x), m in {-s,+s} equiprobable.

Global discrete operator is a contraction when q = a*T*(g+beta*T) < 1.
phi is 1-Lipschitz and bounded by 1/2. This is NOT a continuous-time
stochastic FBSDE theorem, learned model, or language reasoning evidence.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from fractions import Fraction as F
from time import process_time_ns, perf_counter_ns
import re

_NUM = re.compile(r"-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?\Z")

def rat(s: str) -> F:
    if type(s) is not str or len(s)>55 or not _NUM.fullmatch(s):
        raise ValueError("canonical bounded rational expected")
    f=F(s)
    if str(f)!=s or max(f.numerator.bit_length(),f.denominator.bit_length())>80:
        raise ValueError("noncanonical/unbounded rational")
    return f

def phi(v: F) -> F:
    return v/(1+v*v)

@dataclass(frozen=True)
class Law:
    depth: int = 3
    horizon: str = "3/4"
    a: str = "1/3"
    beta: str = "1/4"
    lam: str = "1/5"
    sigma: str = "1/3"
    s: str = "1/2"
    g: str = "1/2"
    x0: str = "1"

    def values(self) -> dict[str,F]:
        if type(self.depth) is not int or not 1<=self.depth<=3:
            raise ValueError("bounded depth 1..3")
        p={k:rat(getattr(self,k)) for k in
           ("horizon","a","beta","lam","sigma","s","g","x0")}
        if not (0<p["horizon"]<=F(2) and 0<=p["a"]<=1 and
                0<=p["beta"]<=1 and 0<=p["lam"]<=1 and
                0<p["sigma"]<=1 and 0<p["s"]<=1 and
                0<p["g"]<=1 and -2<=p["x0"]<=2):
            raise ValueError("unsupported registered parameter range")
        p["h"]=p["horizon"]/self.depth
        p["q"]=p["a"]*p["horizon"]*(p["g"]+p["beta"]*p["horizon"])
        if p["q"] >= F(3,4):
            raise ValueError("global contraction admission q<3/4 required")
        p["M"]=(p["g"]+p["beta"]*p["horizon"])/2
        return p

@dataclass(frozen=True)
class State:
    x: str
    y: str

@dataclass(frozen=True)
class Trace:
    states: tuple[State,...]
    z: tuple[str,...]

@dataclass(frozen=True)
class Solve:
    law: dict
    trace: Trace
    mapped_residual: str
    fixed_point_error_bound: str
    contraction_q: str
    requested_tolerance: str
    evaluations: int
    rounded_steps: int
    quantization_bits: int
    cpu_ns: int
    wall_ns: int
    qualified_discrete_bound: bool
    real_pretrained_forwards: int = 0
    production_accepted: bool = False
    authority: str = "DENY_ALL"


def operator(law: Law, y: tuple[F,...]) -> tuple[F,...]:
    """Exact entire-tree nonlinear operator. Y input is prefix-adapted."""
    p=law.values()
    n=2**law.depth-1
    if type(y) is not tuple or len(y)!=n or any(type(v) is not F for v in y):
        raise ValueError("complete rational public-prefix Y required")
    if any(abs(v)>p["M"] for v in y):
        raise ValueError("proposal escapes invariant bounded interval")
    x=[F(0)]*(2*n+1)
    x[0]=p["x0"]
    for k,yk in enumerate(y):
        center=x[k]+p["a"]*p["h"]*phi(yk)
        x[2*k+1]=center-p["sigma"]*p["s"]
        x[2*k+2]=center+p["sigma"]*p["s"]
    v=[F(0)]*(2*n+1)
    for k in range(n,2*n+1):
        v[k]=p["g"]*phi(x[k])
    for k in range(n-1,-1,-1):
        v[k]=((v[2*k+1]+v[2*k+2])/2+p["beta"]*p["h"]*phi(x[k]))/(1+p["lam"]*p["h"])
    return tuple(v[:n])


def _nearest_even(f: F, bits: int) -> F:
    scale=1<<bits
    numerator=abs(f.numerator)*scale
    rounded, r=divmod(numerator,f.denominator)
    if 2*r>f.denominator or (2*r==f.denominator and rounded%2):
        rounded+=1
    return F(rounded if f>=0 else -rounded,scale)


def build_trace(law: Law, y: tuple[F,...]) -> Trace:
    p=law.values()
    n=2**law.depth-1
    if type(y) is not tuple or len(y)!=n:
        raise ValueError("wrong complete Y vector length")
    x=[F(0)]*(2*n+1)
    yy=list(y)+[F(0)]*(n+1)
    x[0]=p["x0"]
    for k,yk in enumerate(y):
        center=x[k]+p["a"]*p["h"]*phi(yk)
        x[2*k+1]=center-p["sigma"]*p["s"]
        x[2*k+2]=center+p["sigma"]*p["s"]
    for k in range(n,2*n+1):
        yy[k]=p["g"]*phi(x[k])
    z=tuple(str((yy[2*k+2]-yy[2*k+1])/(2*p["s"])) for k in range(n))
    return Trace(tuple(State(str(a),str(b)) for a,b in zip(x,yy)),z)


def solve(law: Law, *, tolerance: str="1/10000", bits: int=16,
          max_calls: int=24) -> Solve:
    p=law.values()
    eps=rat(tolerance)
    if not (0<eps<=F(1,100) and type(bits) is int and 12<=bits<=22 and
            type(max_calls) is int and 1<=max_calls<=40):
        raise ValueError("solver budget outside registered profile")
    n=2**law.depth-1
    y=(F(0),)*n
    cpu=process_time_ns(); wall=perf_counter_ns()
    for k in range(1,max_calls+1):
        mapped=operator(law,y)
        residual=max(abs(a-b) for a,b in zip(y,mapped))
        error=residual/(1-p["q"])
        if error<=eps:
            trace=build_trace(law,y)
            return Solve(asdict(law),trace,str(residual),str(error),str(p["q"]),
                         str(eps),k,k-1,bits,process_time_ns()-cpu,
                         perf_counter_ns()-wall,True)
        y=tuple(_nearest_even(v,bits) for v in mapped)
    raise ValueError("bounded solver exhausted; no E12 certificate")
