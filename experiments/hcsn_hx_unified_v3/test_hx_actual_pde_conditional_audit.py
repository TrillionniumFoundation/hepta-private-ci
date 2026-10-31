"""Use actual bond-PDE/equity outputs; never promote supplied budgets to truth."""
import unittest
from dataclasses import replace
from unittest.mock import patch
from .hx import HX,boundary
from .hx_actual_pde_conditional_audit import (
    UnresolvedActualGrid, evaluate_grid, run_fixed_two_case_panel)
from .hx_conditional_debt_interval_gate import UnresolvedDebtInterval


class ActualPDEConditionalTests(unittest.TestCase):
    def test_real_financial_pde_zero_budget_classifies_some_grid_states(self):
        for sf in (0.015,0.2):
            p=HX(sale_fraction=sf)
            a=evaluate_grid(p,barrier=boundary(p),nodes=101,
                maturity_steps=250,debt_error='0',upper_equity_error='0')
            self.assertGreater(a.guaranteed_continue_count,0)
            self.assertEqual(sum((a.guaranteed_stop_count,
                                  a.guaranteed_continue_count,
                                  a.ambiguous_count)),99)
            self.assertEqual(a.status,'CONDITIONAL_QUANTIZED_GRID_ONLY')

    def test_external_uncertainty_never_increases_certified_sign_counts(self):
        p=HX(sale_fraction=.2);b=boundary(p)
        results=[evaluate_grid(p,barrier=b,nodes=101,maturity_steps=250,
                debt_error=x,upper_equity_error=x)
                for x in ('0','0.000001','0.001')]
        for before,after in zip(results,results[1:]):
            self.assertLessEqual(after.guaranteed_continue_count,
                                 before.guaranteed_continue_count)
            self.assertLessEqual(after.guaranteed_stop_count,
                                 before.guaranteed_stop_count)
            self.assertGreaterEqual(after.ambiguous_count,before.ambiguous_count)

    def test_financial_obstacle_does_not_relabel_mesh_failure(self):
        p=HX(sale_fraction=.2)
        a=evaluate_grid(p,barrier=boundary(p),nodes=101,
            maturity_steps=250,debt_error='0',upper_equity_error='0')
        # Coarse grid is KNOWN to miss the narrow additional STOP region.
        # A conditional quantized-grid certificate CANNOT repair that error.
        self.assertFalse(a.nominal_extra_stop)
        self.assertEqual(a.status,'CONDITIONAL_QUANTIZED_GRID_ONLY')

    def test_bad_uncertainty_or_state_fail_closed(self):
        p=HX();b=boundary(p)
        with self.assertRaises(UnresolvedDebtInterval):
            evaluate_grid(p,barrier=b,nodes=101,maturity_steps=250,
                debt_error='nan',upper_equity_error='0')
        with self.assertRaises(UnresolvedActualGrid):
            evaluate_grid(p,barrier=-1,nodes=101,maturity_steps=250,
                debt_error='0',upper_equity_error='0')

    def test_boundary_projection_refuses_large_solver_error(self):
        from .hx_joint_pde_obstacle import audit_fixed_barrier_from_bond_pde
        p=HX();b=boundary(p)
        real=audit_fixed_barrier_from_bond_pde(p,b,nodes=101,bond_time_steps=250)
        corrupted=replace(real,equity_values=(0.000001,)+real.equity_values[1:])
        with patch('experiments.hcsn_hx_unified_v3.hx_actual_pde_conditional_audit.audit_fixed_barrier_from_bond_pde', return_value=corrupted):
            with self.assertRaises(UnresolvedActualGrid):
                evaluate_grid(p,barrier=b,nodes=101,maturity_steps=250,
                    debt_error='0',upper_equity_error='0')

    def test_canonical_output_preserves_missing_external_certificates(self):
        out=run_fixed_two_case_panel(fast=True)
        self.assertEqual(len(out['rows']),12)
        self.assertFalse(out['production_activation'])
        self.assertFalse(out['all_scientific_blockers_closed'])
        self.assertFalse(out['continuum_certified'])
        self.assertFalse(out['complete_debt_error_budget'])
        self.assertEqual(len(out['sha256_canonical_payload']),64)
        self.assertEqual(out,run_fixed_two_case_panel(fast=True))


if __name__=='__main__':unittest.main()
