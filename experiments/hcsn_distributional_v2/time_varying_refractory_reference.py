"""P2: finite-grid renewal reference for time-varying event intensity.

A neuron starts ACTIVE and fires with a piecewise-constant intensity lam(t).
After each event it is inactive for an *exact deterministic* refractory period
L=k*dt (k>=1); it then re-enters the same time-inhomogeneous active hazard.

For the active probability a(t) and event density m(t)=lam(t)*a(t):

    a'(t)=-m(t)+1_{t>=L} m(t-L), a(0)=1,
    E N_T = int_0^T m(s) ds, P(N_T>=1)=1-exp(-int_0^T lam(s) ds).

The renewal delay differential equation is exact for this restricted physical
model. The implementation below is a *positive-mass time-grid approximation*:
events are assigned to the midpoint of their hazard cell and become active
again at the midpoint k cells later. Each rate cell is integrated by two
exact exponential half-hazard steps surrounding the release. This differs
from physical random event times by up to half a cell, but conserves active
and refractory probability mass. It recomputes positive cohort mass per cell
for f64 safety (O(n*k), explicitly budgeted) and can be compared
to independent continuous-time Gamma/Monte Carlo references. No universal
numerical error bound or convergence rate is certified.

The fixed-grid interface requires a deterministic refractory length exactly
an integer multiple of dt; inputs outside this contract must be rejected.
The local counterfactual is important: endpoint spike probability is NOT an
expected number of repeated events. No rounding-to-[0,1] is performed.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence


class InhomogeneousRenewalError(ValueError):
    """Explicitly refused numeric, grid or physical contract."""


@dataclass(frozen=True)
class RenewalFlow:
    dt: float
    refractory_steps: int
    first_event_probability: float
    expected_event_count: float
    active_at_end: float
    step_expected_counts: tuple[float, ...]
    step_end_active: tuple[float, ...]
    approximation: str = 'positive midpoint-cohort time-grid approximation; not certified'



def expected_renewals(rates: Sequence[float], dt: float, refractory_steps: int,
                      *, max_steps: int = 20000) -> RenewalFlow:
    """Causal expected counts for a piecewise-constant time-varying rate.

    rates[j] applies on [j*dt,(j+1)*dt), and the first state is ACTIVE.
    Requires max(lambda*dt)<=0.5 for reference resolution; this is a
    conservative admission rule rather than a formal approximation bound.
    For zero refractory (k=0), the exact time-inhomogeneous Poisson solution
    is returned instead of running a delay approximation.
    """
    if (type(dt) not in (float,int) or not math.isfinite(dt) or dt<=0 or
            type(refractory_steps) is not int or refractory_steps<0 or
            type(max_steps) is not int or max_steps<1 or
            not isinstance(rates,(tuple,list)) or not 1<=len(rates)<=max_steps):
        raise InhomogeneousRenewalError('invalid finite uniform-grid contract')
    h=float(dt)
    lam=[]
    weights=[]
    for value in rates:
        if type(value) not in (int,float) or not math.isfinite(value) or value<0:
            raise InhomogeneousRenewalError('intensities must be finite nonnegative reals')
        product=float(value)*h
        if not math.isfinite(product) or product>.5:
            raise InhomogeneousRenewalError('lambda*dt exceeds bounded reference resolution')
        lam.append(float(value))
        weights.append(product)
    exposure=math.fsum(weights)
    if not math.isfinite(exposure):
        raise InhomogeneousRenewalError('total exposure outside reference domain')
    first=-math.expm1(-exposure)
    if refractory_steps==0:
        return RenewalFlow(h,0,first,exposure,1.,tuple(weights),
                           tuple(1. for _ in lam))

    k=refractory_steps
    if len(lam)*min(k,len(lam)) > 2_000_000:
        raise InhomogeneousRenewalError('reference cohort-sum work budget exceeded')
    active=1.
    counts=[]
    end_active=[]
    for j,x in enumerate(weights):
        # The current k cohorts are refractory before this cell. The oldest
        # cohort (if any) becomes active at the midpoint. Recompute mass from
        # nonnegative cohorts rather than accumulating cancellation in a
        # probability repeatedly released toward exactly one.
        active=1-math.fsum(counts[max(0,j-k):j])
        if not 0<=active<=1 or not math.isfinite(active):
            raise ArithmeticError('renewal pre-step probability unresolved')
        half_loss=-math.expm1(-x/2)
        early=active*half_loss
        active_mid=1-math.fsum(counts[max(0,j-k+1):j])-early
        if not 0<=active_mid<=1 or not math.isfinite(active_mid):
            raise ArithmeticError('renewal release violates probability envelope')
        late=active_mid*half_loss
        event=math.fsum((early,late))
        active=1-math.fsum((*counts[max(0,j-k+1):j],event))
        if (not math.isfinite(active) or not math.isfinite(event) or
                not 0<=active<=1 or event<0 or
                (event==0 and x>0 and active>0)):
            raise ArithmeticError('nonphysical or underresolved renewal step')
        counts.append(event)
        end_active.append(active)
    total=math.fsum(counts)
    # Events in the current last k cells remain in deterministic refractory.
    # This direct cohort identity independently audits the recurrence.
    inactive=math.fsum(counts[-k:])
    if (not math.isfinite(total) or total+2e-8*max(1.,total)<first or
            total>len(lam)+1e-9 or
            abs(math.fsum((active,inactive))-1)>1e-10):
        raise ArithmeticError('renewal count/mass/first-event envelope unresolved')

    return RenewalFlow(h,k,first,total,active,tuple(counts),tuple(end_active))
