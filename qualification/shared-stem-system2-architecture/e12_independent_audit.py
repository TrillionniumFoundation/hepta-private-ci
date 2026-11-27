"""Independent prefix-based E12 whole-tree oracle and exact fixed-point bound.

Do not import the executable nonlinear operator, its phi function, or its
rounding method. We independently recompute the complete original law,
martingale condition and EACH iteration from 0. Finite special case only.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from fractions import Fraction as Q
from typing import Sequence
from e12_nonlinear_cert import Law, Solve, State, Trace, rat
import re

_SIGNED = re.compile(r"-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?\Z")


def exact(text: str) -> Q:
    if type(text) is not str or not 1<=len(text)<=2500 or not _SIGNED.fullmatch(text):
        raise ValueError("noncanonical or oversized exact trace component")
    x=Q(text)
    if str(x)!=text or max(x.numerator.bit_length(),x.denominator.bit_length())>7200:
        raise ValueError("noncanonical or too-large rational")
    return x


def nonlinear(x: Q) -> Q:
    # Alternate integral numerator/denominator form; no shared phi function.
    n,d=x.numerator,x.denominator
    return Q(n*d, n*n+d*d)


def _children(prefix: tuple[int,...]) -> tuple[tuple[int,...],tuple[int,...]]:
    return prefix + (-1,), prefix + (1,)


def reference(law: Law, y: Sequence[Q]) -> tuple[dict[tuple[int,...], Q],dict[tuple[int,...], Q],tuple[Q,...]]:
    """Independent prefix-dictionary nonlinear full forward/backward map."""
    p=law.values()
    depth=law.depth
    keys=tuple(tuple(-1 if ((i >> (n-1-b))&1)==0 else 1 for b in range(n))
               for n in range(depth) for i in range(1<<n))
    if len(y)!=len(keys) or any(type(v) is not Q for v in y):
        raise ValueError("whole prefix-indexed candidate required")
    given=dict(zip(keys,y))
    X={():p['x0']}
    for key in keys:
        left,right=_children(key)
        center=X[key]+p['a']*p['h']*nonlinear(given[key])
        X[left]=center-p['sigma']*p['s']
        X[right]=center+p['sigma']*p['s']
    U={key:p['g']*nonlinear(value) for key,value in X.items() if len(key)==depth}
    for key in reversed(keys):
        left,right=_children(key)
        U[key]=((U[left]+U[right])/2+p['beta']*p['h']*nonlinear(X[key]))/(1+p['lam']*p['h'])
    return X,U,tuple(U[key] for key in keys)


def round_even(value: Q, bits: int) -> Q:
    # Independent remainder threshold test; exact ties round to even.
    d=1<<bits
    z=value*d
    lower=z.numerator//z.denominator
    frac=z-Q(lower)
    if frac>Q(1,2) or (frac==Q(1,2) and lower%2!=0):
        lower+=1
    return Q(lower,d)

@dataclass(frozen=True)
class Review:
    certified: bool
    entire_public_tree_checked: bool
    independent_iteration_replay: bool
    exact_residual: str
    rigorous_finite_discrete_error_bound: str
    maximum_forward_error: str
    maximum_backward_error: str
    maximum_terminal_error: str
    maximum_covariance_error: str
    maximum_martingale_error: str
    all_source_identity_authenticated: bool=False
    continuous_stochastic_fbsde_qualified: bool=False
    natural_task_improvement_proven: bool=False
    production_accepted: bool=False
    authority: str='DENY_ALL'


def audit(law: Law, result: Solve) -> Review:
    if type(result) is not Solve or type(result.trace) is not Trace:
        raise ValueError("exact typed output required")
    if result.law != asdict(law):
        raise ValueError("changed law profile")
    p=law.values()
    if (type(result.authority) is not str or result.authority!='DENY_ALL' or
        result.production_accepted is not False or result.qualified_discrete_bound is not True or
        type(result.real_pretrained_forwards) is not int or result.real_pretrained_forwards!=0):
        raise ValueError("research-only capability envelope violated")
    if (type(result.evaluations) is not int or type(result.rounded_steps) is not int or
        type(result.quantization_bits) is not int or
        not 1<=result.evaluations<=24 or result.rounded_steps!=result.evaluations-1 or
        not 12<=result.quantization_bits<=22 or
        type(result.cpu_ns) is not int or result.cpu_ns<=0 or result.cpu_ns>=10**12 or
        type(result.wall_ns) is not int or result.wall_ns<=0 or result.wall_ns>=10**12):
        raise ValueError("invalid work/precision/timer claim")
    tol=rat(result.requested_tolerance)
    if not 0<tol<=Q(1,100) or exact(result.contraction_q)!=p['q']:
        raise ValueError("unqualified tolerance or contraction bound")
    m=2**law.depth-1
    if (type(result.trace.states) is not tuple or type(result.trace.z) is not tuple or
        len(result.trace.states)!=2*m+1 or len(result.trace.z)!=m or
        any(type(s) is not State for s in result.trace.states)):
        raise ValueError("missing or untyped graph states")
    x=tuple(exact(state.x) for state in result.trace.states)
    y=tuple(exact(state.y) for state in result.trace.states)
    z=tuple(exact(t) for t in result.trace.z)
    if any(abs(v)>p['M'] for v in y[:m]):
        raise ValueError("internal Y leaves invariant region")
    forward=abs(x[0]-p['x0'])
    backward=terminal=cov=mart=Q(0)
    for k in range(m):
        left,right=2*k+1,2*k+2
        center=x[k]+p['a']*p['h']*nonlinear(y[k])
        forward=max(forward,abs(x[left]-center+p['sigma']*p['s']),
                    abs(x[right]-center-p['sigma']*p['s']))
        conditional=(y[left]+y[right])/2
        backward=max(backward,abs((1+p['lam']*p['h'])*y[k]-conditional-
                                  p['beta']*p['h']*nonlinear(x[k])))
        cov=max(cov,abs(z[k]*p['s']**2 - (y[right]-y[left])*p['s']/2))
        mart=max(mart,abs(y[left]-conditional+z[k]*p['s']),
                      abs(y[right]-conditional-z[k]*p['s']))
    for k in range(m,2*m+1):
        terminal=max(terminal,abs(y[k]-p['g']*nonlinear(x[k])))
    if forward or terminal or cov or mart:
        raise ValueError("forward/leaf/Z/martingale mismatch, not an admitted tree")
    # Separate prefix map cannot import the executor operator.
    root_inputs=tuple(y[:m])
    ref_x,ref_u,mapped=reference(law,root_inputs)
    residual=max(abs(a-b) for a,b in zip(root_inputs,mapped))
    envelope=residual/(1-p['q'])
    if residual!=exact(result.mapped_residual) or envelope!=exact(result.fixed_point_error_bound):
        raise ValueError("forged residual or global error enclosure")
    if envelope>tol:
        raise ValueError("claimed approximation outside certified bound")
    # Compare full public-prefix states with a different index/addressing scheme.
    keys=[tuple(-1 if ((i>>(n-1-b))&1)==0 else 1 for b in range(n))
          for n in range(law.depth+1) for i in range(1<<n)]
    if len(keys)!=len(x) or any(x[i]!=ref_x[key] for i,key in enumerate(keys)):
        raise ValueError("prefix state differs from independent forward trace")
    # Full replay of all reported iteration count from zero, using independent
    # prefix law and independent ties-to-even quantizer.
    current=(Q(0),)*m
    for k in range(1,result.evaluations+1):
        _states,_backward,mapped=reference(law,current)
        rr=max(abs(a-b) for a,b in zip(current,mapped))/(1-p['q'])
        if rr<=tol:
            if k!=result.evaluations or current!=root_inputs:
                raise ValueError("forged iteration count or quantized state")
            break
        if k==result.evaluations:
            raise ValueError("reported premature solver termination")
        current=tuple(round_even(v,result.quantization_bits) for v in mapped)
    else:
        raise ValueError("incomplete fixed-point iteration replay")
    return Review(True,True,True,str(residual),str(envelope),str(forward),
                  str(backward),str(terminal),str(cov),str(mart))
