"""Adversarial physical-identity tests. Synthetic receipts test provenance only.

The mocked equity gate here makes NO statement about mathematical STOP quality.
Full real-PDE regression tests reside in test_hx_measured_debt_conditional_bridge.
"""
from dataclasses import replace
import math
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from .hx import HX
from .debt_pde_rational_interval_audit import (
    DebtNodeBound, FullDebtGridBound, UnresolvedDebtAudit)
from .hx_debt_panel_identity import (
    HX_FIELDS, UnboundDebtPanel, panel_input_digest)
from .hx_measured_debt_conditional_bridge import check_idealized_equity_boundary


class PhysicalIdentityContract(unittest.TestCase):
    @staticmethod
    def digest(p, *, barrier=100.0, nodes=33, time_steps=100, log_upper=3.6):
        return panel_input_digest(p, barrier=barrier, nodes=nodes,
                                  time_steps=time_steps, log_upper=log_upper)

    @classmethod
    def panel(cls, p):
        rows=tuple(DebtNodeBound(i, float(i*(3.6/32)), 1.0,
                     '0','2','2',0) for i in range(33))
        return FullDebtGridBound(
            nodes=33,time_steps=100,log_upper=3.6,
            candidate_barrier=100.0,sale_fraction=p.sale_fraction,
            tolerance='0.005',worst_absolute_discrepancy_upper='0.04',
            guaranteed_max_absolute_discrepancy_lower='0.001',
            worst_node=2,guaranteed_lower_witness_node=2,
            independent_nodes=33,rows=rows,
            physical_parameters_sha256=cls.digest(p))

    def test_frozen_digest_and_exact_binary64_identity(self):
        p=HX(sale_fraction=.2)
        self.assertEqual(self.digest(p),self.digest(replace(p)))
        self.assertEqual(len(self.digest(p)),64)
        self.assertNotEqual(self.digest(replace(p,payout=0.)),
                            self.digest(replace(p,payout=-0.)))

    def test_every_hx_physical_input_changes_identity(self):
        p=HX(sale_fraction=.2)
        for field in HX_FIELDS:
            with self.subTest(field=field):
                alternate=replace(p,**{field:getattr(p,field)+.0001})
                self.assertNotEqual(self.digest(p),self.digest(alternate))

    def test_all_mesh_and_barrier_inputs_change_identity(self):
        p=HX(sale_fraction=.2)
        for changes in ({'barrier':100.01},{'nodes':101},
                        {'time_steps':250},{'log_upper':4.0}):
            with self.subTest(changes=changes):
                self.assertNotEqual(self.digest(p),self.digest(p,**changes))

    def test_invalid_input_refuses(self):
        p=HX(sale_fraction=.2)
        for changes in ({'barrier':math.nan},{'barrier':True},
                        {'nodes':True},{'time_steps':0},
                        {'log_upper':'3.6'},{'barrier':0.0}):
            with self.subTest(changes=changes),self.assertRaises(UnboundDebtPanel):
                self.digest(p,**changes)

    def test_valid_sealed_panel_reaches_only_conditional_gate(self):
        p=HX(sale_fraction=.2)
        panel=self.panel(p)
        fixed=SimpleNamespace(guaranteed_stop_count=0,
             guaranteed_continue_count=31,ambiguous_count=0)
        with patch('experiments.hcsn_hx_unified_v3.hx_measured_debt_conditional_bridge.evaluate_grid',
                   return_value=fixed) as gate:
            receipt=check_idealized_equity_boundary(p,panel)
            gate.assert_called_once()
        self.assertEqual(receipt.conditional_stop,0)
        self.assertFalse(receipt.equity_boundary_error_proved)
        self.assertFalse(receipt.production_activation)

    def test_all_ten_cross_regime_panels_refused_before_equity(self):
        p=HX(sale_fraction=.2)
        panel=self.panel(p)
        with patch('experiments.hcsn_hx_unified_v3.hx_measured_debt_conditional_bridge.evaluate_grid') as gate:
            for field in HX_FIELDS:
                with self.subTest(field=field),self.assertRaises(UnresolvedDebtAudit):
                    altered=replace(p,**{field:getattr(p,field)+.0001})
                    check_idealized_equity_boundary(altered,panel)
            gate.assert_not_called()

    def test_stale_grid_or_forged_identity_refused(self):
        p=HX(sale_fraction=.2)
        panel=self.panel(p)
        with patch('experiments.hcsn_hx_unified_v3.hx_measured_debt_conditional_bridge.evaluate_grid') as gate:
            for alternate in (replace(panel,time_steps=101),
                              replace(panel,log_upper=3.7),
                              replace(panel,candidate_barrier=100.001),
                              replace(panel,physical_parameters_sha256=''),
                              replace(panel,physical_parameters_sha256='0'*64)):
                with self.subTest(alternate=alternate),self.assertRaises(UnresolvedDebtAudit):
                    check_idealized_equity_boundary(p,alternate)
            gate.assert_not_called()


if __name__=='__main__':
    unittest.main()
