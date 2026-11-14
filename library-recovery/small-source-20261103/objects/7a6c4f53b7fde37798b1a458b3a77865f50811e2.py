"""Fixture of the exact dataclass schema for isolated bridge tests.
The actual PDE oracle is NOT executed by this fixture."""
from dataclasses import dataclass

class UnresolvedDebtAudit(ValueError):
    pass

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
