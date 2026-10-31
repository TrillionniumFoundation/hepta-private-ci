"""Test v2 finite-maturity far-field and independent high-precision time oracle."""
from dataclasses import replace
import math
import unittest
import mpmath as mp

from .hx import HX, boundary
from .hx_obstacle_grid_independent import solve_fixed_boundary_obstacle as v1_obstacle
from .hx_obstacle_grid_tail_v2 import (
    solve_fixed_boundary_obstacle as v2_obstacle,
    bond_from_first_hit, UnresolvedObstacle)
from .hx_bond_mp_reference import bond_time_integral,UnresolvedMP

class HXFinancialTailV2Tests(unittest.TestCase):
    def test_upper_asymptote_retains_maturity_principal(self):
        for sf in (.015,.2):
            p=HX(sale_fraction=sf)
            b=boundary(p)
            v1=v1_obstacle(p,b,log_upper=3.6,nodes=201)
            v2=v2_obstacle(p,b,log_upper=3.6,nodes=201)
            q=p.rate+p.hazard
            base=p.per_bond_coupon/q
            far=base+math.exp(-q*p.maturity)*(p.per_bond_principal-base)
            C=(1-p.tax_shield)*p.coupon+p.per_bond_principal
            expected=b*math.exp(3.6)+(far-C)/p.rate
            self.assertAlmostEqual(v2.values[-1],expected,places=8)
            self.assertAlmostEqual(v2.values[-1]-v1.values[-1],
                                   (far-base)/p.rate,places=8)
            self.assertIn('maturity',v2.tail_assumption)

    def test_independent_mp_first_hit_time_integrals(self):
        cases=(HX(),HX(sale_fraction=.2),HX(shock_intensity=0),
               HX(payout=.005,volatility=.4))
        max_error=0.
        for p in cases:
            b=boundary(p)
            for ratio in (1.001,1.05,1.5,4.):
                with self.subTest(p=p,ratio=ratio):
                    reference=bond_time_integral(p,b*ratio,b,digits=65)
                    candidate,_=bond_from_first_hit(p,b*ratio,b)
                    error=abs(candidate-float(mp.mpf(reference.value)))
                    max_error=max(max_error,error)
                    self.assertLess(error,2e-7*(1+abs(candidate)))
        self.assertLess(max_error,2e-7)

    def test_high_liquidity_stop_zone_survives_tail_correction(self):
        p=HX(sale_fraction=.2)
        b=boundary(p)
        res=[v2_obstacle(p,b,nodes=n) for n in (101,201,401)]
        for r in res:
            self.assertIsNotNone(r.last_stop_asset)
            self.assertGreater(r.last_stop_asset,b)
            self.assertLess(r.last_stop_asset,1.1*b)
            self.assertLess(r.max_bellman_residual,1e-6)
        self.assertGreater(abs(res[0].last_stop_asset-res[-1].last_stop_asset),0)

    def test_standard_liquidity_no_extra_stop_detected(self):
        p=HX()
        b=boundary(p)
        for n in (101,201,401):
            self.assertIsNone(v2_obstacle(p,b,nodes=n).last_stop_asset)

    def test_fail_closed_reference_and_grid(self):
        p=HX()
        b=boundary(p)
        with self.assertRaises(UnresolvedMP):
            bond_time_integral(p, b*.5,b)
        with self.assertRaises(UnresolvedMP):
            bond_time_integral(p, b*1.5,b,digits=8)
        with self.assertRaises(UnresolvedObstacle):
            v2_obstacle(replace(p,payout=0),b)

if __name__=='__main__':
    unittest.main()
