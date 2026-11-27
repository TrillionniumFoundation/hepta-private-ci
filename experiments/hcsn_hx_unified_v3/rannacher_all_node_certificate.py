"""Exact-rational all-node comparison of fixed-barrier HX debt BE vs Rannacher.

A separate Brownian first-hit time-density interval oracle bounds the TRUE
fixed-barrier financial debt price at *every* finite PDE grid node. The two
PDEs are not used by the oracle. Both computed binary64 PDE outputs are
compared as exact rationals to the SAME true-price interval. An improvement
claim requires max_i Rannacher_error_upper(i) < max_i BE_error_lower(i).

This is a complete finite panel, NOT a continuum-in-space/time theorem,
self-consistent HX equilibrium, all-parameter certificate, or production gate.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from fractions import Fraction as F
import hashlib
import json
import math

from .first_hit_time_interval import (
    bound_first_hit, financial_bond_from_hit_interval, UnresolvedFirstHit,
)
from .hx_bond_pde_independent import solve_bond_pde
from .hx_bond_pde_rannacher import solve_bond_rannacher


class UnresolvedAllNode(ValueError):
    """Any missing interval, invalid provenance or incomplete panel refuses."""


FIELDS=("rate","payout","volatility","maturity","principal","coupon",
        "tax_shield","recovery","shock_intensity","sale_fraction")


@dataclass(frozen=True)
class NodeEvidence:
    index: int
    log_state_hex: str
    lower_true_price: str
    upper_true_price: str
    be_lower_error: str
    be_upper_error: str
    rannacher_lower_error: str
    rannacher_upper_error: str
    first_hit_cells: int
    tolerance_used: str
    times_refined: int


@dataclass(frozen=True)
class AllNodeResult:
    identity_sha256: str
    all_nodes: int
    time_steps: int
    log_upper_hex: str
    tolerance_initial: str
    tolerance_final: str
    refinement_budget: int
    refinements_used: int
    be_max_error_lower: str
    be_max_error_upper: str
    rannacher_max_error_lower: str
    rannacher_max_error_upper: str
    guaranteed_strict_all_node_improvement: bool
    improvement_witness: str
    status: str
    rows: tuple[NodeEvidence,...]
    complete_continuum_hx_certification: bool = False
    all_scientific_blockers_closed: bool = False
    production_activation: bool = False

    def canonical(self):
        obj=asdict(self)
        obj['rows']=[asdict(r) for r in self.rows]
        payload=json.dumps(obj,sort_keys=True,separators=(',',':'),allow_nan=False)
        return {'canonical_sha256':hashlib.sha256(payload.encode()).hexdigest(),**obj}


def _exact_f64_number(x):
    if type(x) not in (int,float) or not math.isfinite(x):
        raise UnresolvedAllNode('finite physical f64 or integer required')
    return F(x)


def _identity(p, barrier, nodes, steps, log_upper):
    try:
        pvals={k:float(getattr(p,k)).hex() for k in FIELDS}
    except (ValueError,TypeError,AttributeError) as e:
        raise UnresolvedAllNode('physical identity missing or nonfinite') from e
    obj={'financial_params':pvals,'barrier':float(barrier).hex(),
         'nodes':nodes,'time_steps':steps,'log_upper':float(log_upper).hex(),
         'source_contract':'independent rational first-hit; BE/Rannacher finite-debt grids'}
    return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _distance(point,lo,hi):
    if lo>hi or point.denominator == 0:
        raise UnresolvedAllNode('invalid true price interval')
    return max(F(0),lo-point,point-hi),max(abs(point-lo),abs(point-hi))


def _positive_budget(tolerance, limit):
    if type(tolerance) is not str or type(limit) is not int:
        raise UnresolvedAllNode('tolerance must be exact rational string')
    try: v=F(tolerance)
    except (TypeError,ValueError,ZeroDivisionError) as e:
        raise UnresolvedAllNode('invalid exact rational tolerance') from e
    if not 0<v<=F(1,20) or limit<0 or limit>200 or limit and v<F(1,10**10):
        raise UnresolvedAllNode('unsupported first-hit/refinement work budget')
    return v


def audit_rannacher_all_nodes(p, barrier:float, *,nodes:int=101,
              time_steps:int=250,log_upper:float=3.6,
              first_tolerance:str='0.002',refine_tolerance:str='0.00005',
              max_refinements:int=80,max_cells:int=30000)->AllNodeResult:
    """Audit all nodes; adaptively refine worst-error candidates.

    Refinement is driven only by *previously computed* certified intervals and
    observed PDE points. The result never upgrades a failing or unresolved
    inequality to a strict improvement.
    """
    _positive_budget(first_tolerance,max_refinements)
    _positive_budget(refine_tolerance,max_refinements)
    if F(refine_tolerance)>F(first_tolerance):
        raise UnresolvedAllNode('final tolerance must be no coarser')
    if type(max_cells) is not int or not 100<=max_cells<=100000:
        raise UnresolvedAllNode('unsupported first-hit cell cap')
    _exact_f64_number(barrier);_exact_f64_number(log_upper)
    if barrier<=0 or type(nodes) is not int or not 33<=nodes<=2001:
        raise UnresolvedAllNode('invalid grid')
    old=solve_bond_pde(p,barrier,nodes=nodes,time_steps=time_steps,log_upper=log_upper)
    new=solve_bond_rannacher(p,barrier,nodes=nodes,time_steps=time_steps,log_upper=log_upper)
    if not (len(old.values)==nodes==len(new.values)
            and float(old.barrier)==float(new.barrier)==float(barrier)
            and float(old.log_upper)==float(new.log_upper)==float(log_upper)):
        raise UnresolvedAllNode('non-identical physical PDE coordinate systems')
    id_sha=_identity(p,barrier,nodes,time_steps,log_upper)
    mu=F(p.rate)-F(p.payout)-F(p.volatility)**2/2
    discount=F(p.rate)+F(p.shock_intensity)*F(p.sale_fraction)
    sigma=F(p.volatility);T=F(p.maturity)
    def measure(i,tol,prev_revisions=0):
        y=float(i*(log_upper/(nodes-1)))
        if i==0:
            lo=hi=F(p.recovery)*F(barrier)/T
            cells=0
        else:
            try:
                first=bound_first_hit(distance=F(y),drift=mu,diffusion=sigma,
                      maturity=T,discount=discount,tolerance=tol,max_cells=max_cells)
                lo,hi=financial_bond_from_hit_interval(
                      first=first,rate=F(p.rate),maturity=T,
                      principal=F(p.principal),coupon=F(p.coupon),
                      shock_intensity=F(p.shock_intensity),
                      sale_fraction=F(p.sale_fraction),recovery=F(p.recovery),
                      boundary=F(barrier))
                cells=first.cells
            except (UnresolvedFirstHit,OverflowError,ZeroDivisionError) as e:
                raise UnresolvedAllNode(f'no rigorous first-hit interval for node {i}: {e}') from e
        if not 0<=lo<=hi:
            raise UnresolvedAllNode(f'nonordered or negative debt interval at node {i}')
        be0,be1=_distance(F(old.values[i]),lo,hi)
        ne0,ne1=_distance(F(new.values[i]),lo,hi)
        return NodeEvidence(i,y.hex(),str(lo),str(hi),str(be0),str(be1),
                       str(ne0),str(ne1),cells,tol,prev_revisions)
    rows=[measure(i,first_tolerance) for i in range(nodes)]
    # Each row is a mathematically valid enclosed true physical value;
    # choosing a smaller interval afterward is never allowed to drop nodes.
    refinements=0
    while refinements<max_refinements:
        be_witness=max(F(x.be_lower_error) for x in rows)
        rn_upper=max(F(x.rannacher_upper_error) for x in rows)
        if rn_upper < be_witness: break
        # Maximum upper candidate can be loose even if it is NOT the actual
        # worst Rannacher state. Use its bound and an approximate BE witness to
        # resolve the most informative undecided nodes, with deterministic ties.
        candidates=[(float(F(x.rannacher_upper_error)),i)
                    for i,x in enumerate(rows) if x.tolerance_used!=refine_tolerance]
        if not candidates: break
        top_rn=max(candidates)[1]
        # BE midpoint estimate is for prioritization ONLY, never used as proof.
        be_candidates=[(float(abs(F(old.values[i])-(F(x.lower_true_price)+F(x.upper_true_price))/2)),i)
                       for i,x in enumerate(rows) if x.tolerance_used!=refine_tolerance]
        top_be=max(be_candidates)[1] if be_candidates else top_rn
        # Prefer refining witness while its lower-bound margin is too weak.
        choose=top_be if refinements%3==0 else top_rn
        prev=rows[choose]
        rows[choose]=measure(choose,refine_tolerance,prev.times_refined+1)
        refinements+=1
    be_lo=max(F(x.be_lower_error) for x in rows)
    be_hi=max(F(x.be_upper_error) for x in rows)
    rn_lo=max(F(x.rannacher_lower_error) for x in rows)
    rn_hi=max(F(x.rannacher_upper_error) for x in rows)
    strict=rn_hi<be_lo
    return AllNodeResult(id_sha,nodes,time_steps,float(log_upper).hex(),
        first_tolerance,refine_tolerance,max_refinements,refinements,
        str(be_lo),str(be_hi),str(rn_lo),str(rn_hi),strict,
        str(be_lo-rn_hi), 'GUARANTEED_ALL_NODE_ADVANTAGE' if strict else 'INCONCLUSIVE_NOT_CERTIFIED',
        tuple(rows))
