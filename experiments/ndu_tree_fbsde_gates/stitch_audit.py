"""Independent exact-rational two-sided FBSDE segment audit (shadow only).

Registered deterministic special case dX=Y dt, dY=0, X0=x0, YT=g XT.
No general FBSDE numerical convergence, neural capability, or authority claim.
Audit receives proposed segments rather than trusting a solver's residual flags.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction as Q
from typing import Sequence
import re


@dataclass(frozen=True)
class Segment:
    duration: Q
    x_start: Q
    y_start: Q
    x_end: Q
    y_end: Q
    field_start: Q
    field_end: Q


@dataclass(frozen=True)
class Audit:
    boundary_case: str
    global_regular_field: bool
    dynamics_residual: Q
    x_interface_residual: Q
    y_interface_residual: Q
    field_residual: Q
    terminal_residual: Q
    initial_residual: Q
    proposed_trajectory_valid: bool
    globally_solved: bool


def rational(value):
    """Strict canonical decimal/rational values; no floats, booleans or huge inputs."""
    if type(value) is Q:
        result = value
    elif type(value) is int:
        result = Q(value)
    elif type(value) is str and len(value) <= 30 and re.fullmatch(r"-?(0|[1-9][0-9]*)(?:/[1-9][0-9]*)?", value):
        result = Q(value)
        if str(result) != value:
            raise ValueError("noncanonical exact rational")
    else:
        raise ValueError("bounded exact rational required")
    if abs(result.numerator).bit_length() > 80 or result.denominator.bit_length() > 80:
        raise ValueError("rational exceeds resource bound")
    return result


def _profile(x0,g,steps):
    x0,g = rational(x0),rational(g)
    if not -4 <= x0 <= 4 or not -4 <= g <= 4:
        raise ValueError("outside reference coefficient domain")
    if not isinstance(steps,(list,tuple)) or not 1 <= len(steps) <= 32:
        raise ValueError("bounded nonempty segments required")
    ds=tuple(rational(h) for h in steps)
    if any(not Q(0)<h<=4 for h in ds) or sum(ds) > 4:
        raise ValueError("invalid horizon")
    return x0,g,ds


def boundary_case(x0,g,steps):
    x0,g,ds=_profile(x0,g,steps)
    factor=1-g*sum(ds)
    if factor==0:
        return "non_unique" if g*x0==0 else "no_solution"
    return "unique_regular" if g<=0 or g*sum(ds)<1 else "nonregular_unique"


def continuation_fields(g,steps):
    """Propagate ONE terminal decoupling field backwards across all intervals."""
    _,g,ds=_profile(0,g,steps)
    fields=[Q(0)]*(len(ds)+1)
    fields[-1]=g
    for k in reversed(range(len(ds))):
        denom=1-ds[k]*fields[k+1]
        if denom<=0:
            raise ValueError("global continuation pole; regular field unsupported")
        fields[k]=fields[k+1]/denom
        if abs(fields[k].numerator).bit_length()>80 or fields[k].denominator.bit_length()>80:
            raise ValueError("continuation leaves rational bound")
    return tuple(fields)


def construct_regular(x0,g,steps):
    """Reference positive trajectory; independent audit below recomputes all checks."""
    x0,g,ds=_profile(x0,g,steps)
    if boundary_case(x0,g,ds)!="unique_regular":
        raise ValueError("globally regular unique boundary required")
    fields=continuation_fields(g,ds)
    output=[]
    x=x0
    for i,h in enumerate(ds):
        y=fields[i]*x
        xe=x+h*y
        output.append(Segment(h,x,y,xe,y,fields[i],fields[i+1]))
        x=xe
    return tuple(output)


def audit(x0,g,segments: Sequence[Segment]):
    """Fail-closed separate audit of every forward, backward and interface coordinate.

    No self-reported success, residual or hash is considered evidence.
    In particular, correctness of the last leaf never substitutes for both
    x AND y interface continuity or registered global field admissibility.
    """
    if not isinstance(segments,(list,tuple)) or not segments or any(type(s) is not Segment for s in segments):
        raise ValueError("complete typed segment trajectory required")
    x0,g,ds=_profile(x0,g,[s.duration for s in segments])
    expected_case=boundary_case(x0,g,ds)
    regular=expected_case=="unique_regular"
    try:
        fields=continuation_fields(g,ds) if regular else None
    except ValueError:
        fields=None
        regular=False
    parsed=[]
    for s,h in zip(segments,ds):
        if rational(s.duration)!=h:
            raise ValueError("noncanonical segment duration")
        parsed.append(tuple(rational(getattr(s,k)) for k in (
            "x_start","y_start","x_end","y_end","field_start","field_end")))
    dynamics=Q(0)
    f_res=Q(0)
    xj=yj=Q(0)
    for i,(h,p) in enumerate(zip(ds,parsed)):
        xs,ys,xe,ye,fs,fe=p
        dynamics=max(dynamics,abs(xe-xs-h*ys),abs(ye-ys))
        f_res=max(f_res,abs(ys-fs*xs),abs(ye-fe*xe))
        if fields is not None:
            f_res=max(f_res,abs(fs-fields[i]),abs(fe-fields[i+1]))
        if i:
            xj=max(xj,abs(parsed[i-1][2]-xs))
            yj=max(yj,abs(parsed[i-1][3]-ys))
    initial=abs(parsed[0][0]-x0)
    terminal=abs(parsed[-1][3]-g*parsed[-1][2])
    proposed=not any((dynamics,xj,yj,initial,terminal))
    globally=proposed and regular and fields is not None and f_res==0
    return Audit(expected_case,regular and fields is not None,dynamics,xj,yj,
                 f_res,terminal,initial,proposed,globally)
