"""Actual debt-PDE versus rigorous first-hit time-density intervals, by node.

A *true external* error bound at each discrete y_i, unlike hypothetical error
budgets. Does not inherit or invoke the HX bond Eq.(8) or original PDF oracle.
The independent fixed-boundary Brownian bond at each node lies in its time-
first-hit interval; the PDE float output is treated as an exact rational point
for measuring its actual discrepancy. A maximum over ALL nodes thus bounds
that finite-grid panel's external debt pricing error (including numerical
roundoff of the computed PDE), but NOT arbitrary spatial positions, time
maturities, or a self-consistent financial equilibrium.
"""
from dataclasses import dataclass
from fractions import Fraction as F
import hashlib
import json
import math

from .first_hit_time_interval import (bound_first_hit,
    financial_bond_from_hit_interval, UnresolvedFirstHit, _ceil_grid)
from .hx_bond_pde_independent import solve_bond_pde
from .hx_debt_panel_identity import panel_input_digest, UnboundDebtPanel


class UnresolvedDebtAudit(ValueError):
    """Reject incomplete all-node audits and unsupported budgets."""


@dataclass(frozen=True)
class DebtNodeBound:
    index: int
    log_distance: float
    pde_value: float
    continuum_bond_lower: str
    continuum_bond_upper: str
    guaranteed_abs_discrepancy_upper: str
    hit_cells: int


@dataclass(frozen=True)
class FullDebtGridBound:
    nodes: int
    time_steps: int
    log_upper: float
    candidate_barrier: float
    sale_fraction: float
    tolerance: str
    worst_absolute_discrepancy_upper: str
    guaranteed_max_absolute_discrepancy_lower: str
    worst_node: int
    guaranteed_lower_witness_node: int
    independent_nodes: int
    rows: tuple[DebtNodeBound,...]
    physical_parameters_sha256: str = ''
    global_continuum_certified: bool = False
    complete_hx_equilibrium_certified: bool = False
    production_activation: bool = False
    research_only: bool = True

    def canonical_panel(self):
        def record(row):
            return {k:getattr(row,k) for k in row.__dataclass_fields__}
        payload={k:getattr(self,k) for k in self.__dataclass_fields__ if k!='rows'}
        payload['rows']=[record(row) for row in self.rows]
        digest=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),
                                         ensure_ascii=False,allow_nan=False).encode()).hexdigest()
        return {'sha256_canonical_payload':digest,**payload}


def audit_all_debt_nodes(p, barrier: float, *, nodes: int=101,
                         time_steps: int=250, log_upper: float=3.6,
                         hit_tolerance: str='0.005',
                         hit_max_cells: int=5000):
    """Fail closed unless every PDE grid state has a true interval.

    Float model inputs are exactly converted to binary64 rationals. Drift and
    discount are formed as exact arithmetic of these inputs, *not* rounded
    intermediate Python floats; recorded PDE-roundoff difference is included.
    """
    if not (type(barrier) in (int,float) and math.isfinite(barrier) and barrier>0):
        raise UnresolvedDebtAudit('invalid fixed candidate barrier')
    try:
        input_digest=panel_input_digest(p,barrier=barrier,nodes=nodes,
                 time_steps=time_steps,log_upper=log_upper)
    except UnboundDebtPanel as exc:
        raise UnresolvedDebtAudit('unbound HX physical inputs') from exc
    grid=solve_bond_pde(p,barrier,nodes=nodes,time_steps=time_steps,
                        log_upper=log_upper)
    float_r=F.from_float
    mu=float_r(p.rate)-float_r(p.payout)-float_r(p.volatility)**2/2
    q=float_r(p.rate)+float_r(p.shock_intensity)*float_r(p.sale_fraction)
    rows=[];largest=F(0);imax=0
    guaranteed_lower=F(0);lower_imax=0
    for i,value in enumerate(grid.values):
        if i==0:
            exact=F.from_float(p.recovery)*float_r(barrier)/float_r(p.maturity)
            low=high=exact;cells=0
        else:
            # The discrete mesh multiplies a rounded h by integer i.
            # The exact continuum reference uses precisely this coordinate.
            y=float(i*(log_upper/(nodes-1)))
            try:
                hit=bound_first_hit(distance=float_r(y),drift=mu,
                                    diffusion=float_r(p.volatility),
                                    maturity=float_r(p.maturity),discount=q,
                                    tolerance=hit_tolerance,max_cells=hit_max_cells)
                low,high=financial_bond_from_hit_interval(first=hit,
                      rate=float_r(p.rate),maturity=float_r(p.maturity),
                      principal=float_r(p.principal),coupon=float_r(p.coupon),
                      shock_intensity=float_r(p.shock_intensity),
                      sale_fraction=float_r(p.sale_fraction),
                      recovery=float_r(p.recovery),boundary=float_r(barrier))
                cells=hit.cells
            except UnresolvedFirstHit as err:
                raise UnresolvedDebtAudit(f'node {i} missing certified hit interval: {err}') from err
        point=float_r(value)
        diff=_ceil_grid(max(abs(point-low),abs(point-high)))
        certain=max(F(0),low-point,point-high)
        if diff>largest:
            largest=diff;imax=i
        if certain>guaranteed_lower:
            guaranteed_lower=certain;lower_imax=i
        rows.append(DebtNodeBound(i, float(i*(log_upper/(nodes-1))),value,
                  str(low),str(high),str(diff),cells))
    if len(rows)!=nodes:
        raise UnresolvedDebtAudit('incomplete grid panel')
    return FullDebtGridBound(nodes,time_steps,log_upper,barrier,p.sale_fraction,
            hit_tolerance,str(largest),str(guaranteed_lower),imax,lower_imax,
            len(rows),tuple(rows),physical_parameters_sha256=input_digest)


if __name__=='__main__':
    from .hx import HX,boundary
    import sys
    p=HX(sale_fraction=float(sys.argv[1]) if len(sys.argv)>1 else 0.2)
    n=int(sys.argv[2]) if len(sys.argv)>2 else 101
    audit=audit_all_debt_nodes(p,boundary(p),nodes=n,time_steps=max(250,5*n//2))
    print(json.dumps(audit.canonical_panel(),indent=2,sort_keys=True))


def demand_external_debt_error_budget(panel: FullDebtGridBound, budget: str):
    """Refuse until the *actual* all-node debt bound is within the budget.

    A mismatch with an imagined number is not a scientific success. This
    remains conditional on independently certifying the equity boundary and
    completing the financial equilibrium; passing this alone does not admit.
    """
    try:
        limit=F(budget)
    except (ValueError,ZeroDivisionError,TypeError) as e:
        raise UnresolvedDebtAudit('invalid exact debt-error budget') from e
    if limit<0 or F(panel.worst_absolute_discrepancy_upper)>limit:
        raise UnresolvedDebtAudit('actual external debt bound exceeds budget')
    return True
