"""Actual-debt-only conditional STOP is not full equity acceptance."""
from dataclasses import replace
from fractions import Fraction as F
import unittest

from .hx import HX,boundary
from .debt_pde_rational_interval_audit import audit_all_debt_nodes,UnresolvedDebtAudit
from .hx_measured_debt_conditional_bridge import check_idealized_equity_boundary


class TrueDebtBridgeTests(unittest.TestCase):
    def test_actual_high_liquidity_debt_blocks_stop_even_under_ideal_equity(self):
        p=HX(sale_fraction=.2)
        panel=audit_all_debt_nodes(p,boundary(p),nodes=101,time_steps=250)
        receipt=check_idealized_equity_boundary(p,panel)
        self.assertEqual(receipt.conditional_stop,0)
        self.assertEqual(receipt.conditional_continue,93)
        self.assertEqual(receipt.conditional_ambiguous,6)
        self.assertGreaterEqual(F(receipt.debt_bound_rounded_up),
                                F(panel.worst_absolute_discrepancy_upper))
        self.assertFalse(receipt.equity_boundary_error_proved)
        self.assertFalse(receipt.continuum_stop_certified)
        self.assertFalse(receipt.scientific_gate_closed)
        self.assertFalse(receipt.production_activation)

    def test_invalid_parameter_or_missing_node_is_refused(self):
        p=HX(sale_fraction=.015)
        panel=audit_all_debt_nodes(p,boundary(p),nodes=33,time_steps=100)
        with self.assertRaises(UnresolvedDebtAudit):
            check_idealized_equity_boundary(HX(sale_fraction=.2),panel)
        with self.assertRaises(UnresolvedDebtAudit):
            check_idealized_equity_boundary(p,replace(panel,rows=panel.rows[:-1]))
        with self.assertRaises(UnresolvedDebtAudit):
            check_idealized_equity_boundary(p,replace(panel,independent_nodes=32))


if __name__=='__main__':
    unittest.main()
