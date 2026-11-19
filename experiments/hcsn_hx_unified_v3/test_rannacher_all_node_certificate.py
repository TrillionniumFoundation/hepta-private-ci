"""Rational full-node debt errors: strict positive, conservative negative controls."""
from dataclasses import replace
from fractions import Fraction as F
import unittest
from unittest.mock import patch

from .hx import HX,boundary
from .hx_bond_pde_rannacher import solve_bond_rannacher
from .first_hit_time_interval import UnresolvedFirstHit
from .rannacher_all_node_certificate import (
    audit_rannacher_all_nodes, UnresolvedAllNode, _identity,
)


class RationalAllNodeTests(unittest.TestCase):
    def test_two_101_node_panels_have_provable_max_error_advantage(self):
        configs=(
           (.015,'7279b14252698334da9a1d98d679a6b18e10bb9acb1dfcbe6d401124f9e72171'),
           (.2,'456a83edbada7bc98559b934bc6266b5e4c43188bf750bec20a53098064612b1'),
        )
        for sf,seal in configs:
            with self.subTest(sale_fraction=sf):
                p=HX(sale_fraction=sf)
                out=audit_rannacher_all_nodes(p,boundary(p),nodes=101,time_steps=250,
                    first_tolerance='.002',refine_tolerance='.00005',max_refinements=80)
                self.assertEqual(len(out.rows),101)
                self.assertEqual(tuple(r.index for r in out.rows),tuple(range(101)))
                self.assertTrue(out.guaranteed_strict_all_node_improvement)
                self.assertLess(F(out.rannacher_max_error_upper),F(out.be_max_error_lower))
                self.assertEqual(out.canonical()['canonical_sha256'],seal)
                self.assertFalse(out.complete_continuum_hx_certification)
                self.assertFalse(out.production_activation)

    def test_coarse_audit_fails_closed_instead_of_selecting_winning_nodes(self):
        p=HX()
        out=audit_rannacher_all_nodes(p,boundary(p),nodes=33,time_steps=100,
              first_tolerance='.005',refine_tolerance='.005',max_refinements=0)
        self.assertEqual(len(out.rows),33)
        self.assertEqual(out.status,'INCONCLUSIVE_NOT_CERTIFIED')
        self.assertFalse(out.guaranteed_strict_all_node_improvement)
        self.assertEqual(out.refinements_used,0)

    def test_equal_solvers_never_prove_strict_advantage(self):
        p=HX(); b=boundary(p)
        same=solve_bond_rannacher(p,b,nodes=33,time_steps=100)
        with patch('experiments.hcsn_hx_unified_v3.rannacher_all_node_certificate.solve_bond_pde',
                   return_value=same):
            v=audit_rannacher_all_nodes(p,b,nodes=33,time_steps=100,
                  first_tolerance='.005',refine_tolerance='.005',max_refinements=0)
        self.assertFalse(v.guaranteed_strict_all_node_improvement)
        self.assertEqual(v.status,'INCONCLUSIVE_NOT_CERTIFIED')

    def test_full_financial_parameter_identity_changes(self):
        p=HX(); b=boundary(p)
        original=_identity(p,b,101,250,3.6)
        for name in ('rate','payout','volatility','maturity','principal','coupon',
                     'tax_shield','recovery','shock_intensity','sale_fraction'):
            with self.subTest(name=name):
                q=replace(p,**{name:getattr(p,name)+.00001})
                self.assertNotEqual(original,_identity(q,b,101,250,3.6))
        self.assertNotEqual(original,_identity(p,b,201,250,3.6))
        self.assertNotEqual(original,_identity(p,b,101,500,3.6))
        self.assertNotEqual(original,_identity(p,b,101,250,4.0))

    def test_oracle_unavailable_cannot_forge_full_certification(self):
        p=HX(); b=boundary(p)
        with patch('experiments.hcsn_hx_unified_v3.rannacher_all_node_certificate.bound_first_hit',
                   side_effect=UnresolvedFirstHit('artificial oracle refusal')):
            with self.assertRaisesRegex(UnresolvedAllNode,'node 1'):
                audit_rannacher_all_nodes(p,b,nodes=33,time_steps=100,
                      first_tolerance='.005',refine_tolerance='.005',max_refinements=0)

    def test_invalid_budget_must_refuse_before_any_numerical_result(self):
        p=HX();b=boundary(p)
        cases=({'first_tolerance':'nan'}, {'first_tolerance':'0'},
               {'refine_tolerance':'0.01','first_tolerance':'0.002'},
               {'max_refinements':-1}, {'max_refinements':201},
               {'nodes':32}, {'barrier':float('nan')},
               {'max_cells':5}, {'max_cells':100001})
        for kw in cases:
            with self.subTest(kw=kw),self.assertRaises((UnresolvedAllNode,TypeError)):
                audit_rannacher_all_nodes(p,kw.pop('barrier',b),nodes=101,time_steps=250,**kw)


if __name__=='__main__': unittest.main()
