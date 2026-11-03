from dataclasses import replace
import unittest
from hx_published_boundary import published_boundary,independent_comparison
from full_hx_numeric import HXCoupled,solve_free_boundary

class FullPublishedHXBoundary(unittest.TestCase):
    def test_match_independent_full_equity_ode_mesh_convergence(self):
        p=HXCoupled()
        a=float(published_boundary(p)['boundary'])
        errors=[abs(solve_free_boundary(p,N=n)['boundary']-a) for n in (200,400,800,1600)]
        self.assertLess(errors[-1],1e-4)
        self.assertTrue(all(errors[i+1]<errors[i] for i in range(3)))
        self.assertTrue(all(errors[i]/errors[i+1]>3 for i in range(2,3)))

    def test_zero_liquidity_premium_uses_removable_limit(self):
        p=HXCoupled(shock_intensity=0)
        r=published_boundary(p)
        self.assertTrue(r['zero_premium_removable_limit_used'])
        d=independent_comparison(p,N=1600)
        self.assertLess(float(d['absolute_boundary_disagreement']),2e-4)

    def test_coupled_stress_parameter_variations(self):
        base=HXCoupled()
        for p in [replace(base,shock_intensity=.3,sale_fraction=.3),
                  replace(base,volatility=.35),
                  replace(base,maturity=4.)]:
            with self.subTest(p=p):
                ret=independent_comparison(p,N=1600)
                self.assertLess(float(ret['absolute_boundary_disagreement']),5e-4)

    def test_failed_domain_is_not_automatically_promoted(self):
        with self.assertRaises(ValueError):published_boundary(replace(HXCoupled(),tax_shield=1))
        with self.assertRaises(ValueError):published_boundary(HXCoupled(),dps=5)
        with self.assertRaises(ArithmeticError):published_boundary(replace(HXCoupled(),shock_intensity=.8,sale_fraction=.3))

if __name__=='__main__':unittest.main()
