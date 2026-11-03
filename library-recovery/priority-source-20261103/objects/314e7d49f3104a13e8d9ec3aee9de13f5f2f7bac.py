import unittest
from dataclasses import replace
from full_hx_numeric import HXCoupled,first_hit_factors,bond_price,solve_free_boundary,mesh_convergence

class PublishedHXCoupledNumericalReference(unittest.TestCase):
    def test_free_boundary_positive_and_smooth_pasting(self):
        p=HXCoupled()
        r=solve_free_boundary(p,N=800)
        self.assertGreater(r['boundary'],0)
        self.assertLess(r['smooth_pasting_log_derivative_residual'],1e-7)
        self.assertLess(r['boundary_value_abs'],1e-6)
        self.assertFalse(r['original_HX_equity_A7_verified'])

    def test_grid_convergence(self):
        c=mesh_convergence()
        self.assertEqual(len(c['rows']),4)
        diffs=c['successive_boundary_deltas']
        self.assertLess(diffs[-1],diffs[-2])
        self.assertLess(diffs[-2],diffs[-3])

    def test_bond_boundary_and_maturity_price(self):
        p=HXCoupled()
        b=.5
        self.assertAlmostEqual(float(bond_price(p,0,b)),p.recovery_fraction*b/p.maturity)
        for v in (.2,.8,2.,4.):
            f,g=first_hit_factors(p,v)
            self.assertTrue(0<=g<=f<=1)

    def test_illegal_parameters_fail_closed(self):
        p=HXCoupled()
        with self.assertRaises(ValueError):solve_free_boundary(replace(p,maturity=0))
        with self.assertRaises(ValueError):solve_free_boundary(replace(p,sale_fraction=2))
        with self.assertRaises(ValueError):solve_free_boundary(p,N=16)

if __name__=='__main__':unittest.main()
