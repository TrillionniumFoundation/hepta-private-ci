"""Run exact-rational *conditional* obstacle classification on actual HX debt-PDE grids.

Connects the existing independent finite-maturity debt PDE / equity obstacle
with the existing exact-rational Bellman perturbation certificate. It reports
all distinct unknown errors separately; zero uncertainty means quantized-grid
self-consistency ONLY, not an equality to the continuum bond/equity problem.

NO_GO research. No external debt/truncation/rounding certificates are inferred.
"""
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math

from .hx_joint_pde_obstacle import audit_fixed_barrier_from_bond_pde
from .hx_conditional_debt_interval_gate import conditional_debt_error_gate


class UnresolvedActualGrid(ValueError):
    pass


@dataclass(frozen=True)
class PanelCase:
    sale_fraction: float
    nodes: int
    maturity_steps: int
    debt_error_assumed: str
    upper_equity_error_assumed: str
    nominal_extra_stop: bool
    solver_boundary_drift: str
    boundary_projection_allowance: str
    guaranteed_stop_count: int
    guaranteed_continue_count: int
    ambiguous_count: int
    guaranteed_stop_max_asset: float | None
    nominal_last_stop_asset: float | None
    finite_bellman_residual: str
    quantized_residual: str
    conditional_value_error: str
    status: str = 'CONDITIONAL_QUANTIZED_GRID_ONLY'


def evaluate_grid(p, *, barrier, nodes, maturity_steps,
                  debt_error: str, upper_equity_error: str,
                  log_upper: float = 3.6) -> PanelCase:
    if not (type(barrier) in (float,int) and math.isfinite(barrier) and barrier > 0):
        raise UnresolvedActualGrid('invalid externally provided fixed barrier')
    # Never infer any externally supplied debt uncertainty from PDE-vs-analytic
    # discrepancies, numerical quadrature error, or a mesh-refinement gap.
    g = audit_fixed_barrier_from_bond_pde(p, barrier,
        nodes=nodes,bond_time_steps=maturity_steps,log_upper=log_upper)
    # LAPACK banded solve is backward stable, but can return a boundary value
    # of order 1e-13 even when the exact Dirichlet boundary is zero. Accept
    # projection ONLY within a predeclared local floating-point allowance;
    # do not change the exact-rational checker, and recompute its interior
    # Bellman residual after projection (including the first adjacent row).
    v0=g.equity_values[0]
    scale=max(1.,max(abs(x) for x in g.equity_values))
    tolerance=64.*math.ulp(scale)
    if not (math.isfinite(v0) and abs(v0)<=tolerance):
        raise UnresolvedActualGrid('unresolved numerical default-boundary drift')
    projected=replace(g,equity_values=(0.0,)+g.equity_values[1:])
    c = conditional_debt_error_gate(p,projected,debt_error=debt_error,
                                    upper_equity_error=upper_equity_error)
    if len(c.guaranteed_stop)+len(c.guaranteed_continue)+len(c.ambiguous)!=nodes-2:
        raise UnresolvedActualGrid('missing interior decisions')
    step = log_upper/(nodes-1)
    top = (barrier*math.exp(c.guaranteed_stop[-1]*step)
           if c.guaranteed_stop else None)
    return PanelCase(p.sale_fraction,nodes,maturity_steps,
        debt_error,upper_equity_error, bool(g.last_stop_asset),
        str(v0),str(tolerance),
        len(c.guaranteed_stop),len(c.guaranteed_continue),len(c.ambiguous),
        top,g.last_stop_asset,str(g.max_equity_bellman_residual),
        str(c.exact_nominal_residual),str(c.sup_value_perturbation))


def run_fixed_two_case_panel(*, fast: bool = False):
    """Deterministic grid diagnostic. Does NOT upgrade P0 admission."""
    # Import original repo HX equations for the *candidate*, never for bond PDE.
    from .hx import HX,boundary
    shapes = ((101,250),(201,500)) if fast else ((101,250),(201,500),(401,1000))
    # Zero budget tests quantized finite grid internally. Nonzero 'what-if'
    # budgets are *hypotheses*, not accepted physical error enclosures.
    budgets = (('0','0'),('0.000001','0.000001'),('0.001','0.001'))
    rows=[]
    for sf in (0.015,0.2):
        p=HX(sale_fraction=sf)
        b=boundary(p)
        for n,t in shapes:
            for e,u in budgets:
                rows.append(asdict(evaluate_grid(p,barrier=b,nodes=n,
                    maturity_steps=t,debt_error=e,upper_equity_error=u)))
    payload={'schema':'hcsn-hx-actual-pde-conditional-grid-v1',
        'research_only':True,'production_activation':False,
        'all_scientific_blockers_closed':False,
        'complete_debt_error_budget':False,
        'continuum_certified':False,
        'unmeasured_errors':['financial_bond_PDE_spatial_discretization',
            'financial_bond_PDE_time_discretization',
            'debt_upper_tail', 'equity_far_field',
            'real_arithmetic_roundoff', 'endogenous_equilibrium_fixed_point'],
        'rows':rows}
    seal=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),
                                   allow_nan=False).encode('utf-8')).hexdigest()
    return {'sha256_canonical_payload':seal,**payload}


if __name__=='__main__':
    print(json.dumps(run_fixed_two_case_panel(),ensure_ascii=False,
                     sort_keys=True,indent=2,allow_nan=False))
