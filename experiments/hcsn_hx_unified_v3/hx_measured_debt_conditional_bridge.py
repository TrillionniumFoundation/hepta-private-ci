"""Use REAL all-node debt bounds in the existing HX conditional obstacle gate.

This is a diagnostic with the equity upper Dirichlet error *hypothetically zero*.
It is NOT an admissible full physical error budget, not a continuum STOP proof,
not production. Unlike #4520's what-if debt values, the debt input has a
concrete independent first-hit bound on every stored debt-PDE node.
"""
from dataclasses import dataclass
from fractions import Fraction as F
import math

from .debt_pde_rational_interval_audit import FullDebtGridBound, UnresolvedDebtAudit
from .hx_actual_pde_conditional_audit import evaluate_grid
from .hx_debt_panel_identity import panel_input_digest, UnboundDebtPanel


@dataclass(frozen=True)
class DebtOnlyConditionalReceipt:
    nodes: int
    maturity_steps: int
    debt_bound_rounded_up: str
    conditional_stop: int
    conditional_continue: int
    conditional_ambiguous: int
    equity_upper_error_assumed: str = '0'
    real_debt_bound_supplied: bool = True
    equity_boundary_error_proved: bool = False
    continuum_stop_certified: bool = False
    scientific_gate_closed: bool = False
    production_activation: bool = False


def check_idealized_equity_boundary(p, panel: FullDebtGridBound) -> DebtOnlyConditionalReceipt:
    """Exact decimal ceil of real debt bound, hypothetical zero equity error.

    Caller cannot mark P0 success: even if the conditional quantized-grid STOP
    set were nonempty, the equity Dirichlet and continuum free boundary are
    not supplied/certified. Also refuse any panel/parameter mismatch.
    """
    if not isinstance(panel,FullDebtGridBound) or panel.independent_nodes!=panel.nodes:
        raise UnresolvedDebtAudit('incomplete all-node rational panel')
    if not (type(p.sale_fraction) is float and math.isfinite(p.sale_fraction)
            and p.sale_fraction==panel.sale_fraction and
            type(panel.candidate_barrier) is float and math.isfinite(panel.candidate_barrier)
            and panel.candidate_barrier>0 and
            len(panel.rows)==panel.nodes and
            tuple(row.index for row in panel.rows)==tuple(range(panel.nodes))):
        raise UnresolvedDebtAudit('physical panel mismatch')
    try:
        expected=panel_input_digest(p,barrier=panel.candidate_barrier,
            nodes=panel.nodes,time_steps=panel.time_steps,
            log_upper=panel.log_upper)
    except UnboundDebtPanel as exc:
        raise UnresolvedDebtAudit('invalid HX physical identity') from exc
    if (type(panel.physical_parameters_sha256) is not str or
            panel.physical_parameters_sha256!=expected):
        raise UnresolvedDebtAudit('stale/unbound physical HX debt-error panel')
    debt=F(panel.worst_absolute_discrepancy_upper)
    if debt<0:
        raise UnresolvedDebtAudit('negative external debt error')
    # Outward decimal conversion. Existing gate refuses unbounded Fraction
    # strings and accepts at most 40 significant digits of a decimal literal.
    scaled=(debt.numerator*10**9+debt.denominator-1)//debt.denominator
    error_string=f'{scaled//10**9}.{scaled%10**9:09d}'
    decision=evaluate_grid(p,barrier=panel.candidate_barrier,nodes=panel.nodes,
         maturity_steps=panel.time_steps,log_upper=panel.log_upper,
         debt_error=error_string,upper_equity_error='0')
    if (decision.guaranteed_stop_count + decision.guaranteed_continue_count
            + decision.ambiguous_count !=panel.nodes-2):
        raise UnresolvedDebtAudit('conditional decision partition invalid')
    return DebtOnlyConditionalReceipt(panel.nodes,panel.time_steps,error_string,
         decision.guaranteed_stop_count,decision.guaranteed_continue_count,
         decision.ambiguous_count)
