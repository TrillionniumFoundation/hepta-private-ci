"""Independent bond/quadrature financial smooth-fit root, including invalid obstacle."""
import unittest

from .hx import HX, boundary, equity_closed
from .hx_coupled_smoothfit_independent import independent_smoothfit_root
from .hx_obstacle_grid_independent import UnresolvedObstacle, solve_fixed_boundary_obstacle


class HXCoupledReferenceTests(unittest.TestCase):
    def test_coupled_smoothfit_against_separate_hx_formula(self):
        for p in (HX(), HX(sale_fraction=.2), HX(shock_intensity=0),
                  HX(rate=.08,payout=.05,volatility=.35,maturity=1.2),
                  HX(payout=.01,volatility=.45,maturity=3)):
            with self.subTest(p=p):
                root=independent_smoothfit_root(p)
                target=boundary(p)
                self.assertLess(abs(root.boundary-target)/target,2e-7)
                self.assertLess(root.quadrature_shift/target,2e-7)
                self.assertGreaterEqual(root.first_hit_tail_bound,0)
                self.assertLess(root.first_hit_tail_log10_bound,-20)

    def test_root_does_not_override_global_obstacle(self):
        p=HX(sale_fraction=.2)
        root=independent_smoothfit_root(p)
        self.assertLess(equity_closed(p,root.boundary*1.01,root.boundary),0)
        obstacle=solve_fixed_boundary_obstacle(p,root.boundary,nodes=201)
        self.assertIsNotNone(obstacle.last_stop_asset)
        self.assertGreater(obstacle.last_stop_asset,root.boundary)

    def test_tail_and_quadrature_parameter_guards(self):
        for kw in ({'nodes':0},{'nodes':65},{'log_cutoff':1},
                   {'log_cutoff':30}):
            with self.subTest(kw=kw),self.assertRaises(UnresolvedObstacle):
                independent_smoothfit_root(HX(),**kw)
        with self.assertRaises(UnresolvedObstacle):
            independent_smoothfit_root(HX(payout=0))


if __name__=='__main__':
    unittest.main()
