"""Implicit financial algebraic-root gradients vs separate HX Eq12 differences."""
from dataclasses import replace
import math
import unittest
from .hx import HX, boundary
from .hx_implicit_gradient_reference import implicit_financial_boundary_gradient
from .hx_obstacle_grid_independent import UnresolvedObstacle


class HXImplicitGradientTests(unittest.TestCase):
    def test_parameter_sensitivities_vs_independent_root_differences(self):
        for p in (HX(),HX(sale_fraction=.2)):
            out=implicit_financial_boundary_gradient(p)
            for name,derivative in out.gradients.items():
                with self.subTest(sale=p.sale_fraction,field=name):
                    h=out.perturbations[name]
                    bp=boundary(replace(p,**{name:getattr(p,name)+h}))
                    bm=boundary(replace(p,**{name:getattr(p,name)-h}))
                    independent=(bp-bm)/(2*h)
                    self.assertTrue(math.isfinite(derivative))
                    self.assertLess(abs(derivative-independent),
                                    1e-3*(1+abs(independent)))

    def test_out_of_domain_or_unsupported_parameter_refused(self):
        for p,fields in ((HX(sale_fraction=0),('sale_fraction',)),
                         (HX(),('unknown',)),(HX(),()),
                         (HX(),('rate','rate'))):
            with self.subTest(p=p,fields=fields),self.assertRaises(UnresolvedObstacle):
                implicit_financial_boundary_gradient(p,fields=fields)


if __name__=='__main__':
    unittest.main()
