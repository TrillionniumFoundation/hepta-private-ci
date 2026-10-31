"""Explicit NO_GO gate for method/mesh agreement in financial obstacle studies.

This orchestration deliberately calls *separate* numerical implementations:
 - physical-maturity bond PDE + scipy-banded financial obstacle;
 - Brownian first-hit density bond + separate Thomas/Howard obstacle.
The component solvers do not import each other's implementation.

Mesh agreement itself is only a bounded numerical observation; it NEVER
upgrades complete HX mathematical admissibility or production authority.
"""
from dataclasses import dataclass
import math

from .hx_joint_pde_obstacle import audit_fixed_barrier_from_bond_pde
from .hx_obstacle_grid_tail_v2 import solve_fixed_boundary_obstacle as density_obstacle


@dataclass(frozen=True)
class MeshComparison:
    nodes: int
    bond_time_steps: int
    pde_last_stop: float | None
    density_last_stop: float | None
    exact_decision_agreement: bool
    endpoint_within_one_cell: bool
    pde_equity_residual: float
    density_equity_residual: float


@dataclass(frozen=True)
class MeshGate:
    status: str
    comparisons: tuple[MeshComparison,...]
    scientific_gate_closed: bool = False
    production_activation: bool = False


def financial_obstacle_mesh_gate(p, candidate_boundary: float, *,
                                 log_upper: float=3.6,
                                 meshes: tuple[tuple[int,int],...]=(
                                     (101,250),(201,500),(401,1000))) -> MeshGate:
    """Never silence real cross-method STOP/CONTINUE disagreement."""
    if not (isinstance(meshes,tuple) and len(meshes)>=2 and
            all(isinstance(a,tuple) and len(a)==2 for a in meshes)):
        raise ValueError('invalid mesh plan')
    seen=set();results=[]
    for n,nt in meshes:
        if type(n) is not int or type(nt) is not int or n in seen:
            raise ValueError('duplicate or invalid mesh')
        seen.add(n)
        pde=audit_fixed_barrier_from_bond_pde(p,candidate_boundary,
                  nodes=n,bond_time_steps=nt,log_upper=log_upper)
        den=density_obstacle(p,candidate_boundary,nodes=n,log_upper=log_upper)
        left=pde.last_stop_asset;right=den.last_stop_asset
        same=(left is None)==(right is None)
        step=candidate_boundary*math.exp(log_upper)*log_upper/(n-1)
        near=(same and (left is None or abs(left-right)<=step))
        results.append(MeshComparison(n,nt,left,right,same,near,
                       pde.max_equity_bellman_residual,den.max_bellman_residual))
    has_mismatch=any(not x.endpoint_within_one_cell for x in results)
    return MeshGate('NUMERICAL_DISAGREEMENT_NO_GO' if has_mismatch
                    else 'MESH_AGREEMENT_NOT_GLOBAL_PROOF',tuple(results))
