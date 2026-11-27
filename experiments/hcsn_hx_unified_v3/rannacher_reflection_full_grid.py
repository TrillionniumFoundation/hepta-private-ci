"""All finite nodes: analytic rational reflection intervals vs two debt PDEs.

This is an auxiliary *analytic* validation path. Separate physical-time
Darboux validates selected first-hit cases and separately all 101 nodes on
two regimes (#4535). No global continuous-space or full HX equilibrium claim.
"""
from dataclasses import dataclass, asdict
from fractions import Fraction as F
import hashlib
import json
import math

from .first_hit_time_interval import financial_bond_from_hit_interval, _floor_grid, _ceil_grid
from .first_hit_reflection_interval import bound_first_hit_reflection
from .hx_bond_pde_independent import solve_bond_pde
from .hx_bond_pde_rannacher import solve_bond_rannacher
from .rannacher_all_node_certificate import _identity, UnresolvedAllNode


@dataclass(frozen=True)
class ReflectionDebtNode:
    index: int
    log_distance_hex: str
    true_lower: str
    true_upper: str
    backward_euler_lower_error: str
    backward_euler_upper_error: str
    rannacher_lower_error: str
    rannacher_upper_error: str


@dataclass(frozen=True)
class ReflectionFullGrid:
    physical_identity_sha256: str
    nodes: int
    time_steps: int
    worst_be_lower: str
    worst_be_upper: str
    worst_rcn_lower: str
    worst_rcn_upper: str
    strict_all_node_advantage: bool
    strict_margin: str
    be_witness_index: int
    rcn_worst_upper_index: int
    rows: tuple[ReflectionDebtNode,...]
    reference_type: str = 'rational Gaussian-series reflection; analytic auxiliary'
    debt_continuum_space_certified: bool = False
    global_hx_equilibrium_certified: bool = False
    production_activation: bool = False
    all_scientific_blockers_closed: bool = False

    def canonical(self):
        p=asdict(self)
        p['rows']=[asdict(x) for x in self.rows]
        digest=hashlib.sha256(json.dumps(p,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        return {'canonical_sha256':digest,**p}


def _errors(point,lo,hi):
    return max(F(0),lo-point,point-hi),max(abs(point-lo),abs(point-hi))


def certify_reflection_full_grid(p,barrier:float,*,nodes:int,
                                    time_steps:int,log_upper:float=3.6):
    if (type(nodes) is not int or not 33<=nodes<=5001
            or type(time_steps) is not int or not 1<=time_steps<=20000
            or type(log_upper) not in (float,int) or not math.isfinite(log_upper)
            or type(barrier) not in (float,int) or not math.isfinite(barrier)
            or barrier<=0):
        raise UnresolvedAllNode('invalid finite reflection panel')
    be=solve_bond_pde(p,barrier,nodes=nodes,time_steps=time_steps,log_upper=log_upper)
    rn=solve_bond_rannacher(p,barrier,nodes=nodes,time_steps=time_steps,log_upper=log_upper)
    if not (len(be.values)==len(rn.values)==nodes and
            be.barrier==rn.barrier==barrier and
            be.log_upper==rn.log_upper==log_upper):
        raise UnresolvedAllNode('unmatched physical PDE grid')
    mu=F(p.rate)-F(p.payout)-F(p.volatility)**2/2
    q=F(p.rate)+F(p.shock_intensity)*F(p.sale_fraction)
    rows=[];blo=[];bhi=[];rlo=[];rhi=[]
    for i in range(nodes):
        y=float(i*(log_upper/(nodes-1)))
        if i==0:
            low=high=F(p.recovery)*F(barrier)/F(p.maturity)
        else:
            first=bound_first_hit_reflection(distance=F(y),drift=mu,
                diffusion=F(p.volatility),maturity=F(p.maturity),discount=q)
            low,high=financial_bond_from_hit_interval(first=first,
                rate=F(p.rate),maturity=F(p.maturity),
                principal=F(p.principal),coupon=F(p.coupon),
                shock_intensity=F(p.shock_intensity),
                sale_fraction=F(p.sale_fraction),recovery=F(p.recovery),
                boundary=F(barrier))
        # Outward quantize to the audited 1e-35 rational grid before storing.
        # Exact reflection fractions can otherwise contain >4300 digits.
        low,high=_floor_grid(low),_ceil_grid(high)
        if not 0<=low<=high:
            raise UnresolvedAllNode('invalid exact true bond enclosure')
        a,b=_errors(F(be.values[i]),low,high)
        c,d=_errors(F(rn.values[i]),low,high)
        blo.append(a);bhi.append(b);rlo.append(c);rhi.append(d)
        rows.append(ReflectionDebtNode(i,y.hex(),str(low),str(high),str(a),str(b),str(c),str(d)))
    if len(rows)!=nodes or tuple(x.index for x in rows)!=tuple(range(nodes)):
        raise UnresolvedAllNode('incomplete physical node coverage')
    old_min=max(blo);old_max=max(bhi);new_min=max(rlo);new_max=max(rhi)
    strict=new_max<old_min
    return ReflectionFullGrid(_identity(p,barrier,nodes,time_steps,log_upper),
        nodes,time_steps,str(old_min),str(old_max),str(new_min),str(new_max),
        strict,str(old_min-new_max),blo.index(old_min),rhi.index(new_max),tuple(rows))
