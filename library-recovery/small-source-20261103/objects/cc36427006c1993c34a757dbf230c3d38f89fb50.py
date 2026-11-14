from dataclasses import dataclass,replace
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from experiments.hcsn_hx_unified_v3.hx_debt_panel_identity import HX_FIELDS,panel_input_digest
from experiments.hcsn_hx_unified_v3.debt_pde_rational_interval_audit import DebtNodeBound,FullDebtGridBound,UnresolvedDebtAudit
from experiments.hcsn_hx_unified_v3.hx_measured_debt_conditional_bridge import check_idealized_equity_boundary
@dataclass(frozen=True)
class P:
    rate:float=.05
    payout:float=.03
    volatility:float=.25
    maturity:float=2.
    principal:float=60.
    coupon:float=4.
    tax_shield:float=.25
    recovery:float=.6
    shock_intensity:float=1.
    sale_fraction:float=.2

def panel(p):
    rows=tuple(DebtNodeBound(i, i*3.6/32, 1.,'0','2','2',0) for i in range(33))
    return FullDebtGridBound(33,100,3.6,100.,p.sale_fraction,'0.005','0.04','0.001',2,2,33,rows,
            physical_parameters_sha256=panel_input_digest(p,barrier=100.,nodes=33,time_steps=100,log_upper=3.6))
class Check(unittest.TestCase):
    def test_valid_fixture_is_conditional_only(self):
        p=P();s=panel(p)
        with patch('experiments.hcsn_hx_unified_v3.hx_measured_debt_conditional_bridge.evaluate_grid',return_value=SimpleNamespace(guaranteed_stop_count=0,guaranteed_continue_count=31,ambiguous_count=0)) as gate:
            r=check_idealized_equity_boundary(p,s)
            gate.assert_called_once()
        self.assertFalse(r.scientific_gate_closed)
        self.assertFalse(r.production_activation)
    def test_ten_cross_regime_fail_before_equity(self):
        p=P();s=panel(p)
        with patch('experiments.hcsn_hx_unified_v3.hx_measured_debt_conditional_bridge.evaluate_grid') as gate:
            for k in HX_FIELDS:
                with self.subTest(field=k),self.assertRaises(UnresolvedDebtAudit):
                    check_idealized_equity_boundary(replace(p,**{k:getattr(p,k)+.0001}),s)
            gate.assert_not_called()
    def test_mesh_and_digest_mutation_fail_before_equity(self):
        p=P();s=panel(p)
        with patch('experiments.hcsn_hx_unified_v3.hx_measured_debt_conditional_bridge.evaluate_grid') as gate:
            for t in (replace(s, time_steps=101),replace(s,log_upper=4.),replace(s,candidate_barrier=101.),replace(s,physical_parameters_sha256='')):
                with self.assertRaises(UnresolvedDebtAudit):check_idealized_equity_boundary(p,t)
            gate.assert_not_called()
if __name__=='__main__':unittest.main()
