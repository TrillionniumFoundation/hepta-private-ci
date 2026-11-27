"""Two-independent-equation fixed-barrier HX financial consistency audit.

Step A solves the *finite-maturity bond* backward parabolic PDE, using
only the financial contractual boundary/terminal conditions (not Eq.8).
Step B uses this numerical debt price to solve a distinct stationary
log-asset equity obstacle with scipy banded linear algebra (not Eq.A7
or the prior first-hit/Howard obstacle implementation).

A local smooth-fit root passed from outside is *not* a globally admissible
self-consistent default policy. Here bond absorbing boundary is FIXED;
additional stockholder exercise nodes reveal its possible inconsistency.
Grid agreement is empirical, not an all-parameter continuum theorem.
"""
from dataclasses import dataclass
import math

import numpy as np
from scipy.linalg import solve_banded
from .hx_bond_pde_independent import solve_bond_pde, UnresolvedBondPDE


class UnresolvedCoupledAudit(ValueError):
    pass


@dataclass(frozen=True)
class CoupledPDEObstacle:
    candidate_barrier: float
    log_upper: float
    nodes: int
    bond_time_steps: int
    equity_values: tuple[float, ...]
    debt_values: tuple[float, ...]
    exercise_runs: tuple[tuple[float,float], ...]
    last_stop_asset: float | None
    max_bond_time_residual: float
    max_equity_bellman_residual: float
    min_equity_value: float
    policy_iterations: int
    interpretation: str = 'fixed-barrier numerical consistency audit, NOT self-consistent equilibrium'


def audit_fixed_barrier_from_bond_pde(p, candidate_barrier: float, *,
                                      log_upper: float=3.6, nodes: int=201,
                                      bond_time_steps: int=800,
                                      max_policy_iterations: int=100) -> CoupledPDEObstacle:
    """Fail closed when equity M-matrix/policy or bond PDE is unresolved."""
    if type(max_policy_iterations) is not int or not 1<=max_policy_iterations<=1000:
        raise UnresolvedCoupledAudit('invalid policy iteration budget')
    try:
        bond=solve_bond_pde(p,candidate_barrier,log_upper=log_upper,
                            nodes=nodes,time_steps=bond_time_steps)
    except UnresolvedBondPDE as e:
        raise UnresolvedCoupledAudit(str(e)) from e
    n=bond.nodes
    h=bond.log_upper/(n-1)
    ql,qr=bond.left_jump_rate,bond.right_jump_rate
    discount=p.rate
    const=(1-p.tax_shield)*p.coupon+p.principal/p.maturity
    b=bond.barrier
    cash=np.array([p.payout*b*math.exp(i*h)+v-const
                   for i,v in enumerate(bond.values)],dtype=np.float64)
    # The *debt* upper boundary already includes maturity principal.
    end=b*math.exp(log_upper)+(bond.values[-1]-const)/discount
    if not math.isfinite(end) or end<=0:
        raise UnresolvedCoupledAudit('unresolved nondefault upper-tail equity boundary')

    policy=np.zeros(n,dtype=bool)
    policy[0]=True  # zero shareholder payoff on default
    values=None
    for iteration in range(1,max_policy_iterations+1):
        diag=np.full(n,discount+ql+qr)
        lo=np.full(n,-ql)
        up=np.full(n,-qr)
        rhs=cash.copy()
        diag[policy]=1.;lo[policy]=0.;up[policy]=0.;rhs[policy]=0.
        diag[-1]=1.;lo[-1]=0.;up[-1]=0.;rhs[-1]=end
        bands=np.zeros((3,n))
        bands[0,1:]=up[:-1]
        bands[1,:]=diag
        bands[2,:-1]=lo[1:]
        if not np.all(np.isfinite(bands)) or not np.all(np.isfinite(rhs)):
            raise UnresolvedCoupledAudit('nonfinite financial obstacle coefficients')
        try:
            values=solve_banded((1,1),bands,rhs,overwrite_ab=False,
                                overwrite_b=False,check_finite=True)
        except (ValueError,ArithmeticError) as e:
            raise UnresolvedCoupledAudit('unresolved banded financial obstacle') from e
        # A provisional all-continue policy can have *negative* equity; that
        # is the very counterexample being detected. Only the stabilized
        # VI solution must satisfy nonnegative limited liability.
        if not np.all(np.isfinite(values)):
            raise UnresolvedCoupledAudit('nonfinite intermediate equity policy')
        continuation=(ql*values[:-2]+qr*values[2:]+cash[1:-1])/(discount+ql+qr)
        proposal=policy.copy()
        proposal[1:-1]=continuation<=1e-12*(1+np.abs(continuation))
        if np.array_equal(policy,proposal):
            break
        policy=proposal
    else:
        raise UnresolvedCoupledAudit('financial equity obstacle policy not stable')
    if values is None:
        raise UnresolvedCoupledAudit('no policy evaluation')
    residual=float(np.max(np.abs(values[1:-1]-np.maximum(0.,continuation))))
    if (not math.isfinite(residual) or values.min()<-1e-8 or
            residual>1e-7*(1+float(np.max(values)))):
        raise UnresolvedCoupledAudit('unresolved discrete obstacle residual')
    exercises=np.flatnonzero(policy[1:-1])+1
    runs=[]
    if len(exercises):
        left=last=int(exercises[0])
        for index in exercises[1:]:
            idx=int(index)
            if idx!=last+1:
                runs.append((b*math.exp(left*h),b*math.exp(last*h)))
                left=idx
            last=idx
        runs.append((b*math.exp(left*h),b*math.exp(last*h)))
    return CoupledPDEObstacle(b,log_upper,n,bond.time_steps,
                              tuple(float(v) for v in values),bond.values,
                              tuple(runs),runs[-1][1] if runs else None,
                              bond.max_time_residual,residual,
                              float(np.min(values)),iteration)
