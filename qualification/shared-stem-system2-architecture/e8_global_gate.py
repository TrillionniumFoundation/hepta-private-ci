"""Independent exact-rational E8 two-sided global-trajectory/adaptive-cost guard.

ONLY the known deterministic dX=Ydt,dY=0,Y(T)=gX(T) profile is checked.
Not a stochastic, neural, arbitrary-tree or continuous-time existence theorem.
No claim that a certified solver residual proves real task success.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction as Q
import re
from typing import Sequence

_RE = re.compile(r'-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?\Z')


def fq(x):
    if type(x) is Q:
        out=x
    elif type(x) is int:
        out=Q(x)
    elif type(x) is str and len(x)<=32 and _RE.fullmatch(x):
        out=Q(x)
        if str(out)!=x:
            raise ValueError('noncanonical exact rational')
    else:
        raise ValueError('exact rational required, no float or implicit rounding')
    if out.numerator.bit_length()>96 or out.denominator.bit_length()>96:
        raise ValueError('excessive rational size')
    return out


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
class Certificate:
    case: str
    globally_solved: bool
    max_dynamics_error: Q
    max_interface_error: Q
    max_field_error: Q
    max_terminal_error: Q


def certify(x0,g,segments:Sequence[Segment])->Certificate:
    """Recompute every interface and the **one** global regular field.

    A sequence of unique local solves is NOT a global certificate. Even a
    perfectly valid final leaf does not excuse a broken backward interface.
    """
    x0,g=fq(x0),fq(g)
    if type(segments) not in (list,tuple) or not 1<=len(segments)<=32:
        raise ValueError('1..32 typed segments required')
    if any(type(s) is not Segment for s in segments):
        raise ValueError('a model may not self-certify with untyped receipts')
    if any(not -4<=v<=4 for v in (x0,g)):
        raise ValueError('outside declared coefficient domain')
    hs=[fq(s.duration) for s in segments]
    if any(not Q(0)<h<=4 for h in hs) or sum(hs,Q(0))>4:
        raise ValueError('unsupported duration/horizon')
    T=sum(hs,Q(0)); factor=1-g*T
    boundary=('non_unique' if g*x0==0 else 'no_solution') if not factor else (
        'unique_regular' if g<=0 or g*T<1 else 'nonregular_unique')
    regular=boundary=='unique_regular'
    errors={'dynamics':Q(0),'interface':Q(0),'field':Q(0),'terminal':Q(0)}
    t=Q(0)
    prev=None
    for h,s in zip(hs,segments):
        xs,ys,xe,ye,fs,fe=(fq(getattr(s,name)) for name in
                             ('x_start','y_start','x_end','y_end','field_start','field_end'))
        errors['dynamics']=max(errors['dynamics'],abs(xe-xs-h*ys),abs(ye-ys))
        if prev is None:
            errors['interface']=max(errors['interface'],abs(xs-x0))
        else:
            errors['interface']=max(errors['interface'],abs(xs-prev[0]),abs(ys-prev[1]))
        errors['field']=max(errors['field'],abs(ys-fs*xs),abs(ye-fe*xe))
        if regular:
            denom_start=1-g*(T-t)
            denom_end=1-g*(T-t-h)
            if denom_start<=0 or denom_end<=0:
                regular=False
            else:
                errors['field']=max(errors['field'],abs(fs-g/denom_start),
                                    abs(fe-g/denom_end))
        prev=(xe,ye)
        t+=h
    errors['terminal']=abs(prev[1]-g*prev[0])
    valid=regular and all(v==0 for v in errors.values())
    return Certificate(boundary,valid,errors['dynamics'],errors['interface'],
                       errors['field'],errors['terminal'])


@dataclass(frozen=True)
class Bound:
    action: str
    low: Q
    high: Q
    allowed: bool = True


@dataclass(frozen=True)
class Choice:
    selected: str
    global_check_executed: bool
    reason: str
    certified_margin: Q
    global_fbsde_case: str
    production_accepted: bool = False


def decide(bounds:Sequence[Bound],baseline:str,candidate:str,
           work_cost, *, x0, g, segments:Sequence[Segment])->Choice:
    """Conservative budgeted decision: net candidate LCB beats ALL rivals' UCB.

    Bound inputs are assumed to come from an *independent outcome/critic owner*;
    this demo validates their algebra only, NOT that the bounds have coverage.
    A FBSDE certificate alone is therefore NEVER a measured utility benefit.
    """
    if type(bounds) not in (list,tuple) or not 2<=len(bounds)<=128:
        raise ValueError('bounded complete action roster required')
    if type(baseline) is not str or type(candidate) is not str or baseline==candidate:
        raise ValueError('two distinct registered actions required')
    c=fq(work_cost)
    if not 0<=c<=100:
        raise ValueError('negative or unbounded incremental compute charge')
    seen={}
    for b in bounds:
        if type(b) is not Bound or type(b.action) is not str or not re.fullmatch(r'[a-z_0-9]{1,40}',b.action):
            raise ValueError('strict typed policy action')
        if b.action in seen or type(b.allowed) is not bool:
            raise ValueError('duplicate action or corrupt feasibility')
        low,high=fq(b.low),fq(b.high)
        if not -8<=low<=high<=8:
            raise ValueError('unbounded or contradictory value envelope')
        seen[b.action]=b
    if baseline not in seen or candidate not in seen or not seen[baseline].allowed:
        raise ValueError('no legal baseline/candidate inventory')
    if not seen[candidate].allowed:
        return Choice(baseline,False,'candidate_hard_infeasible',Q(0),'not_checked')
    rival=max((fq(b.high) for b in bounds if b.allowed and b.action!=candidate))
    margin=fq(seen[candidate].low)-c-rival
    if margin<=0:
        return Choice(baseline,False,'no_strict_cost_adjusted_advantage',margin,'not_checked')
    # Only after a cheap independent interval gate do we pay for global math.
    # This remains a deterministic analytic research special case.
    certificate=certify(x0,g,segments)
    if not certificate.globally_solved:
        return Choice(baseline,True,'no_globally_regular_solution',margin,certificate.case)
    # In reality physical System2 cost was ALREADY paid to estimate the
    # certificate. This mathematical predicate is not an on-demand saving.
    return Choice(candidate,True,'certified_toy_action_gap_only',margin,certificate.case)
