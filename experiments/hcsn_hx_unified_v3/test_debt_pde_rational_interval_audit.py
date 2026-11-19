"""All-node true external debt bounds, fail-closed budgets and corruption."""
from dataclasses import replace
from fractions import Fraction as F
import math
import unittest
from unittest.mock import patch

from .hx import HX,boundary,bond_value
from .hx_bond_pde_independent import solve_bond_pde
from .debt_pde_rational_interval_audit import (
    audit_all_debt_nodes, demand_external_debt_error_budget, UnresolvedDebtAudit)


class DebtIntervalGridTests(unittest.TestCase):
    def test_all_nodes_enclose_independent_closed_financial_bond(self):
        for sf in (.015,.2):
            with self.subTest(sf=sf):
                p=HX(sale_fraction=sf);b=boundary(p)
                grid=audit_all_debt_nodes(p,b,nodes=33,time_steps=100)
                self.assertEqual(grid.independent_nodes,33)
                self.assertEqual(len(grid.rows),33)
                self.assertGreater(F(grid.worst_absolute_discrepancy_upper),0)
                self.assertGreater(F(grid.guaranteed_max_absolute_discrepancy_lower),0)
                for row in grid.rows:
                    asset=b*math.exp(row.log_distance)
                    target=(p.recovery*b/p.maturity if row.index==0 else
                            bond_value(p,asset,p.maturity,b))
                    low=F(row.continuum_bond_lower);hi=F(row.continuum_bond_upper)
                    self.assertLessEqual(float(low)-2e-10,target)
                    self.assertGreaterEqual(float(hi)+2e-10,target)
                    self.assertLessEqual(float(F(row.guaranteed_abs_discrepancy_upper))+1e-10,
                                         1.0)  # 33 nodes, fixed bounded panel
                self.assertFalse(grid.global_continuum_certified)
                self.assertFalse(grid.complete_hx_equilibrium_certified)
                self.assertFalse(grid.production_activation)

    def test_real_budget_refusal_not_hypothetical_success(self):
        p=HX(sale_fraction=.2)
        grid=audit_all_debt_nodes(p,boundary(p),nodes=33,time_steps=100)
        with self.assertRaisesRegex(UnresolvedDebtAudit,'exceeds budget'):
            demand_external_debt_error_budget(grid,'0.000001')
        self.assertTrue(demand_external_debt_error_budget(grid,'10'))
        for token in ('-1','nan','bad'):
            with self.subTest(token=token),self.assertRaises((UnresolvedDebtAudit,ValueError)):
                demand_external_debt_error_budget(grid,token)

    def test_injected_debt_fault_is_not_hidden(self):
        p=HX(sale_fraction=.015);b=boundary(p)
        baseline=audit_all_debt_nodes(p,b,nodes=33,time_steps=100)
        pde=solve_bond_pde(p,b,nodes=33,time_steps=100,log_upper=3.6)
        corrupt=list(pde.values)
        corrupt[6]+=1.
        with patch('experiments.hcsn_hx_unified_v3.debt_pde_rational_interval_audit.solve_bond_pde',
                   return_value=replace(pde,values=tuple(corrupt))):
            audit=audit_all_debt_nodes(p,b,nodes=33,time_steps=100)
        self.assertGreater(F(audit.guaranteed_max_absolute_discrepancy_lower),F('0.5'))
        self.assertGreater(F(audit.worst_absolute_discrepancy_upper),
                           F(baseline.worst_absolute_discrepancy_upper))

    def test_invalid_barrier_and_corner_refused(self):
        p=HX()
        for v in (0,-1,math.inf,math.nan):
            with self.subTest(v=v),self.assertRaises(UnresolvedDebtAudit):
                audit_all_debt_nodes(p,v,nodes=33,time_steps=100)


if __name__=='__main__':
    unittest.main()
