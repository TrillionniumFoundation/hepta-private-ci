"""Focused tests; compare independent first-hit quadrature and obstacle results.

The independent implementation never calls the formulas under test.
Tests are bounded witnesses, not all-parameter or continuum certificates.
"""
from dataclasses import replace
import math
import unittest

from .hx import HX, boundary, bond_value, equity_closed
from .hx_obstacle_grid_independent import (UnresolvedObstacle,
    bond_from_first_hit, solve_fixed_boundary_obstacle)


class FinancialObstacleTests(unittest.TestCase):
    def test_independent_bond_vs_published_expression(self):
        for p in (HX(),HX(sale_fraction=.2),HX(shock_intensity=0),
                  HX(payout=.005,volatility=.4)):
            b=boundary(p)
            for ratio in (1.001,1.05,1.5,4,15):
                with self.subTest(p=p,ratio=ratio):
                    actual,err=bond_from_first_hit(p,b*ratio,b)
                    target=bond_value(p,b*ratio,p.maturity,b)
                    self.assertLess(abs(actual-target),2e-7*(1+abs(target)))
                    self.assertLess(err,1e-7)

    def test_extreme_liquidity_refused_by_global_obstacle(self):
        p=HX(sale_fraction=.2)
        b=boundary(p)
        # Retain the historical negative-equity counterexample.
        self.assertLess(equity_closed(p,b*1.01,b),0.)
        result=solve_fixed_boundary_obstacle(p,b,nodes=201)
        self.assertIsNotNone(result.last_stop_asset)
        self.assertGreater(result.last_stop_asset,b)
        self.assertLess(result.max_bellman_residual,1e-6)
        self.assertGreaterEqual(min(result.values),-1e-9)

    def test_regular_hx_does_not_need_extra_immediate_stop(self):
        p=HX()
        result=solve_fixed_boundary_obstacle(p,boundary(p),nodes=201)
        self.assertIsNone(result.last_stop_asset)
        self.assertLess(result.max_bellman_residual,1e-6)
        self.assertTrue(all(v>=-1e-9 for v in result.values))

    def test_mesh_and_far_field_sensitivity(self):
        p=HX(sale_fraction=.2); b=boundary(p)
        three=[solve_fixed_boundary_obstacle(p,b,nodes=n)
               for n in (101,201,401)]
        # A finite-domain diagnostic may change by a mesh cell; it must not
        # lose the extra STOP zone as the grid is refined.
        self.assertTrue(all(x.last_stop_asset is not None for x in three))
        self.assertTrue(all(x.max_bellman_residual<1e-6 for x in three))
        other=solve_fixed_boundary_obstacle(p,b,nodes=201,log_upper=4.2)
        self.assertIsNotNone(other.last_stop_asset)

    def test_fail_closed_invalid_or_unresolved(self):
        p=HX()
        for kw in ({'nodes':20},{'nodes':202},{'nodes':4003},
                   {'log_upper':0.01},{'log_upper':10},
                   {'max_iterations':0}):
            with self.subTest(kw=kw),self.assertRaises(UnresolvedObstacle):
                solve_fixed_boundary_obstacle(p,boundary(p),**kw)
        with self.assertRaises(UnresolvedObstacle):
            solve_fixed_boundary_obstacle(replace(p,payout=0),boundary(p))
        for asset in (-1,0,float('nan')):
            with self.assertRaises(UnresolvedObstacle):
                bond_from_first_hit(p,asset,1.0)
        with self.assertRaises(UnresolvedObstacle):
            solve_fixed_boundary_obstacle(p,float('inf'))


if __name__=='__main__':
    unittest.main()
