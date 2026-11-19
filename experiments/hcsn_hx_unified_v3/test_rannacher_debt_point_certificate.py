"""Exact-rational selected-node improvement claims; all-science gate remains NO_GO."""
from dataclasses import replace
from fractions import Fraction as F
import math
import unittest
from unittest.mock import patch

from .hx import HX,boundary,bond_value
from .hx_bond_pde_rannacher import (solve_bond_rannacher,UnresolvedRannacher)
from .rannacher_debt_point_certificate import certify_debt_node

class RannacherPointTests(unittest.TestCase):
    def test_six_development_selected_nodes_have_strict_enclosed_error_advantage(self):
        # Chosen from a prior exploratory max-error scan; not preregistered,
        # independent statistical samples or proof of all-node superiority.
        for sf,probes in ((.015,(19,37,75)),(.2,(9,17,35))):
            p=HX(sale_fraction=sf);b=boundary(p)
            for (n,t),i in zip(((101,250),(201,500),(401,1000)),probes):
                with self.subTest(sf=sf,n=n,i=i):
                    v=certify_debt_node(p,b,nodes=n,time_steps=t,index=i)
                    self.assertTrue(v.guaranteed_pointwise_improvement)
                    self.assertLess(F(v.rannacher_error_upper),F(v.be_error_lower))
                    self.assertFalse(v.all_node_financial_error_certified)
                    self.assertFalse(v.global_financial_obstacle_certified)
                    self.assertFalse(v.production_activation)
                    self.assertGreater(v.first_hit_cells,10)
                    # Cross-check separately against original Eq8, which the
                    # oracle itself does NOT import or invoke.
                    exact=bond_value(p,b*math.exp(float.fromhex(v.log_state_float_hex)),
                                     p.maturity,b)
                    self.assertGreaterEqual(exact+1e-11,float(F(v.true_price_lower)))
                    self.assertLessEqual(exact-1e-11,float(F(v.true_price_upper)))

    def test_tie_cannot_be_reported_as_strict_improvement(self):
        p=HX(sale_fraction=.2);b=boundary(p)
        candidate=solve_bond_rannacher(p,b,nodes=33,time_steps=100)
        # Negative control: force both implementations to produce exactly
        # identical arrays, so strict ordering must be false by construction.
        with patch('experiments.hcsn_hx_unified_v3.rannacher_debt_point_certificate.solve_bond_pde',
                   return_value=candidate):
            v=certify_debt_node(p,b,nodes=33,time_steps=100,index=5,tolerance='.002')
        self.assertFalse(v.guaranteed_pointwise_improvement)

    def test_physical_fingerprint_changes_on_parameter_change(self):
        p=HX();b=boundary(p)
        a=certify_debt_node(p,b,nodes=33,time_steps=100,index=5,tolerance='.002')
        altered=replace(p,volatility=p.volatility+.001)
        c=certify_debt_node(altered,b,nodes=33,time_steps=100,index=5,tolerance='.002')
        self.assertNotEqual(a.physical_identity_sha256,c.physical_identity_sha256)

    def test_invalid_or_incomplete_probes_refuse(self):
        p=HX();b=boundary(p)
        for i in (-1,0,32,33):
            with self.subTest(index=i),self.assertRaises(UnresolvedRannacher):
                certify_debt_node(p,b,nodes=33,time_steps=100,index=i)
        with self.assertRaises(UnresolvedRannacher):
            certify_debt_node(p,b,nodes=33,time_steps=100,index=5,tolerance='bad')
        with self.assertRaises(UnresolvedRannacher):
            certify_debt_node(p,b,nodes=33,time_steps=100,index=5,max_cells=12)

if __name__=='__main__':
    unittest.main()
