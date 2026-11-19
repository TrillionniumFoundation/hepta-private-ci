"""Deterministic whole-panel *bounded* financial HX obstacle admission audit.

Scientific gate reports every sampled panel item, with no silent drops.
This is not a proof over the entire structural parameter domain. It uses the
independent first-hit financial smooth-fit and fixed-barrier obstacle solvers.
"""
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
import random

from .hx import HX
from .hx_coupled_smoothfit_independent import independent_smoothfit_root
from .hx_obstacle_grid_independent import (
    UnresolvedObstacle, solve_fixed_boundary_obstacle,
)


@dataclass(frozen=True)
class PanelResult:
    index: int
    parameters: dict
    verdict: str
    algebraic_boundary: float | None
    extra_stop_on_coarse: bool | None
    extra_stop_on_fine: bool | None
    stop_frontier_coarse: float | None
    stop_frontier_fine: float | None
    max_discrete_residual: float | None
    refusal: str | None


def generate_panel(*, count: int = 24, seed: int = 20261031):
    """Fixed seed plus mandatory adverse and regular cases."""
    if type(count) is not int or not 2 <= count <= 1024:
        raise ValueError("count outside declared panel size")
    if type(seed) is not int or not 0 <= seed < 2**64:
        raise ValueError("invalid deterministic seed")
    rng=random.Random(seed)
    cases=[HX(), HX(sale_fraction=.2)]
    for _ in range(count-2):
        cases.append(HX(
            rate=rng.uniform(.025,.12),
            payout=rng.uniform(.008,.09),
            volatility=rng.uniform(.18,.5),
            maturity=rng.uniform(.7,5.0),
            principal=rng.uniform(35,90),
            coupon=rng.uniform(2,9),
            tax_shield=rng.uniform(.05,.45),
            recovery=rng.uniform(.2,.85),
            shock_intensity=rng.uniform(.05,4),
            sale_fraction=rng.choice([0.,rng.uniform(.002,.3)]),
        ))
    return tuple(cases)


def _relative_frontier_difference(coarse, fine, boundary):
    if coarse.last_stop_asset is None and fine.last_stop_asset is None:
        return 0.0
    if (coarse.last_stop_asset is None) != (fine.last_stop_asset is None):
        return math.inf
    return abs(math.log(coarse.last_stop_asset/fine.last_stop_asset))


def audit_panel(*, count: int = 24, seed: int = 20261031,
                coarse_nodes: int = 101, fine_nodes: int = 201,
                log_upper: float = 3.6, max_relative_frontier: float = .09):
    """An honest bounded audit: pass != globally valid continuum solution.

    Classification:
      OBSERVED_EXTRA_STOP: failure of algebraic-boundary obstacle candidate.
      NO_EXTRA_STOP_ON_GRID: only a finite-grid observation, NOT a proof.
      UNRESOLVED: any domain refusal, mesh disagreement or numerical failure.
    """
    if not (type(coarse_nodes) is int and type(fine_nodes) is int
            and 33<=coarse_nodes<fine_nodes<=4001
            and coarse_nodes%2==1 and fine_nodes%2==1
            and type(max_relative_frontier) in (float,int)
            and math.isfinite(max_relative_frontier)
            and 0<max_relative_frontier<=.25):
        raise ValueError('invalid independent mesh audit contract')
    results=[]
    for i,p in enumerate(generate_panel(count=count,seed=seed)):
        root=None;low=None;high=None
        try:
            root=independent_smoothfit_root(p)
            low=solve_fixed_boundary_obstacle(
                p,root.boundary,nodes=coarse_nodes,log_upper=log_upper)
            high=solve_fixed_boundary_obstacle(
                p,root.boundary,nodes=fine_nodes,log_upper=log_upper)
            gap=_relative_frontier_difference(low,high,root.boundary)
            if gap>max_relative_frontier:
                verdict='UNRESOLVED'
                reason='frontier changes excessively across tested meshes'
            elif low.last_stop_asset is not None and high.last_stop_asset is not None:
                verdict='OBSERVED_EXTRA_STOP'
                reason=None
            else:
                verdict='NO_EXTRA_STOP_ON_GRID'
                reason=None
        except (ValueError,ArithmeticError,OverflowError,UnresolvedObstacle) as e:
            verdict='UNRESOLVED'
            reason=f'{type(e).__name__}: {str(e)[:180]}'
        results.append(PanelResult(
            i,asdict(p),verdict,
            root.boundary if root is not None else None,
            low.last_stop_asset is not None if low is not None else None,
            high.last_stop_asset is not None if high is not None else None,
            low.last_stop_asset if low is not None else None,
            high.last_stop_asset if high is not None else None,
            max(low.max_bellman_residual,high.max_bellman_residual)
                if low is not None and high is not None else None,
            reason,
        ))
    counts={name:sum(r.verdict==name for r in results)
            for name in ('NO_EXTRA_STOP_ON_GRID','OBSERVED_EXTRA_STOP','UNRESOLVED')}
    assert sum(counts.values())==count
    body={'contract_version':'HX_OBSTACLE_PANEL_V1',
          'status':'RESEARCH_ONLY_DENY_ALL_NO_GO',
          'seed':seed,'count':count,'coarse_nodes':coarse_nodes,
          'fine_nodes':fine_nodes,'log_upper':log_upper,
          'max_relative_frontier':max_relative_frontier,
          'counts':counts,'items':[asdict(r) for r in results],
          'global_certification':False,'production_activation':False,
          'all_scientific_blockers_closed':False}
    canonical=json.dumps(body,sort_keys=True,separators=(',',':'),allow_nan=False)
    return {'sha256':hashlib.sha256(canonical.encode()).hexdigest(),**body}


def audit_json(**kwargs):
    return json.dumps(audit_panel(**kwargs),sort_keys=True,indent=2,allow_nan=False)
