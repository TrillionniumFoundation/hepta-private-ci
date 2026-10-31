"""Deterministic finite-panel HX obstacle audit with corrected maturity-T tail.

All attempted cases receive a public verdict, including computation refusals.
No finite panel proves global optimality, even with a stable positive finding.
"""
from dataclasses import dataclass,asdict
import hashlib
import json
import math
import random

from .hx import HX
from .hx_coupled_smoothfit_independent import independent_smoothfit_root
from .hx_obstacle_grid_tail_v2 import solve_fixed_boundary_obstacle


@dataclass(frozen=True)
class PanelRow:
    index: int
    parameters: dict
    verdict: str
    algebraic_boundary: float | None
    stop_coarse: float | None
    stop_fine: float | None
    stop_wide: float | None
    max_bellman_residual: float | None
    refusal: str | None


def panel_parameters(*, count: int = 24, seed: int = 20261031):
    if type(count) is not int or not 2<=count<=1024:
        raise ValueError('invalid panel count')
    if type(seed) is not int or not 0<=seed<2**64:
        raise ValueError('invalid seed')
    rng=random.Random(seed)
    cases=[HX(),HX(sale_fraction=.2)]
    for _ in range(count-2):
        cases.append(HX(rate=rng.uniform(.025,.12),
                        payout=rng.uniform(.008,.09),
                        volatility=rng.uniform(.18,.5),
                        maturity=rng.uniform(.7,5.0),
                        principal=rng.uniform(35,90),
                        coupon=rng.uniform(2,9),
                        tax_shield=rng.uniform(.05,.45),
                        recovery=rng.uniform(.2,.85),
                        shock_intensity=rng.uniform(.05,4),
                        sale_fraction=rng.choice([0.,rng.uniform(.002,.3)])))
    return tuple(cases)


def _spread(frontiers):
    if all(x is None for x in frontiers): return 0.
    if any(x is None for x in frontiers): return math.inf
    return math.log(max(frontiers)/min(frontiers))


def audit_panel(*, count: int = 24, seed: int = 20261031,
                coarse_nodes: int=101, fine_nodes: int=201,
                log_upper: float=3.6, wide_log_upper: float=4.2,
                max_frontier_log_spread: float=.09) -> dict:
    if not (type(coarse_nodes) is int and type(fine_nodes) is int
            and 33<=coarse_nodes<fine_nodes<=4001 and
            coarse_nodes%2==1 and fine_nodes%2==1 and
            type(log_upper) in (int,float) and type(wide_log_upper) in (int,float)
            and math.isfinite(log_upper) and math.isfinite(wide_log_upper)
            and .5<=log_upper<wide_log_upper<=6.
            and type(max_frontier_log_spread) in (int,float)
            and math.isfinite(max_frontier_log_spread)
            and .001<=max_frontier_log_spread<=.25):
        raise ValueError('invalid audit grids')
    rows=[]
    for i,p in enumerate(panel_parameters(count=count,seed=seed)):
        root=None;grids=[];reason=None
        try:
            root=independent_smoothfit_root(p)
            for n,U in ((coarse_nodes,log_upper),(fine_nodes,log_upper),
                        (fine_nodes,wide_log_upper)):
                grids.append(solve_fixed_boundary_obstacle(p,root.boundary,
                                                           nodes=n,log_upper=U))
            spread=_spread([g.last_stop_asset for g in grids])
            if spread>max_frontier_log_spread:
                verdict='UNRESOLVED'
                reason='mesh or upper-bound sensitivity exceeds declared limit'
            elif grids[0].last_stop_asset is not None:
                verdict='OBSERVED_EXTRA_STOP'
            else:
                verdict='NO_EXTRA_STOP_ON_GRID'
        except (ValueError,ArithmeticError,OverflowError,ZeroDivisionError) as e:
            verdict='UNRESOLVED'
            reason=f'{type(e).__name__}: {str(e)[:180]}'
        f=[g.last_stop_asset for g in grids]
        rows.append(PanelRow(i,asdict(p),verdict,
                             root.boundary if root is not None else None,
                             f[0] if len(f)>0 else None,
                             f[1] if len(f)>1 else None,
                             f[2] if len(f)>2 else None,
                             max(g.max_bellman_residual for g in grids) if grids else None,
                             reason))
    counts={k:sum(r.verdict==k for r in rows) for k in
            ('OBSERVED_EXTRA_STOP','NO_EXTRA_STOP_ON_GRID','UNRESOLVED')}
    assert sum(counts.values())==count and len(rows)==count
    body=dict(contract='HX_FINANCIAL_OBSTACLE_PANEL_V2_MATURITY_TAIL',
              correct_far_bond='c/q + exp(-q*T)*(P-c/q)',
              seed=seed,count=count,coarse_nodes=coarse_nodes,fine_nodes=fine_nodes,
              log_upper=log_upper,wide_log_upper=wide_log_upper,
              max_frontier_log_spread=max_frontier_log_spread,
              counts=counts,items=[asdict(r) for r in rows],
              global_certification=False,production_activation=False,
              all_scientific_blockers_closed=False,
              status='RESEARCH_ONLY_DENY_ALL_NO_GO')
    canonical=json.dumps(body,sort_keys=True,separators=(',',':'),allow_nan=False)
    return {'sha256':hashlib.sha256(canonical.encode()).hexdigest(),**body}
