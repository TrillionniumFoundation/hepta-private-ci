"""All algebraic/certificate tests run without stochastic sampling or fitting."""
import unittest
from fractions import Fraction as F
from math import comb
from certificate import (A,B,DEGREE,GAMMA,DELTA,STRONG_CONVEXITY,
                         moment,poly_mul,poly_add,poly_scale,zpoly,bernstein_hull,
                         global_hull,tanh_coefficients,tanh_poly,uniform_tanh_argument_bound,
                         exact_poly_gradient,certificate)


class ExactCertificateTests(unittest.TestCase):
    def test_01_population_moments_are_exact(self):
        self.assertEqual(moment(4),F(1,5))
        self.assertEqual(moment(6),F(1,7))
        self.assertEqual(moment(8),F(1,9))
        self.assertEqual(moment(5),F(0))
        with self.assertRaises(ValueError): moment(-1)

    def test_02_polynomial_operations_exact(self):
        self.assertEqual(poly_mul([F(1),F(2)],[F(3),F(4)]),[F(3),F(10),F(8)])
        self.assertEqual(poly_add([F(1)],[F(0),F(2)]),[F(1),F(2)])
        self.assertEqual(poly_scale([F(1),F(2)],F(1,2)),[F(1,2),F(1)])

    def test_03_bernstein_hull_on_segments(self):
        p=[F(0),F(0),F(1)]
        lo,hi=bernstein_hull(p,F(0),F(1))
        self.assertEqual((lo,hi),(F(0),F(1)))
        lo,hi=global_hull(zpoly(),16)
        self.assertLessEqual(lo,F(-1,2))
        self.assertGreaterEqual(hi,F(1,3))

    def test_04_bernstein_guarantees_expansion_radius(self):
        result=uniform_tanh_argument_bound()
        self.assertLess(result['max_tanh_argument'],F(1,2))
        self.assertLess(-result['state_lower'],F(3,4))
        self.assertLess(result['state_upper'],F(3,4))

    def test_05_complex_cauchy_majorants_are_rational(self):
        cosh_upper=F(1)+F(1,2)+F(1,24)/(1-F(1,30))
        sinh_upper=F(1)+F(1,6)+F(1,120)/(1-F(1,42))
        self.assertLess(cosh_upper,F(5,3))
        self.assertLess(sinh_upper,F(4,3))

    def test_06_tanh_ode_coefficients(self):
        a=tanh_coefficients(9)
        self.assertEqual(a[1],1)
        self.assertEqual(a[3],F(-1,3))
        self.assertEqual(a[5],F(2,15))
        self.assertEqual(a[7],F(-17,315))
        self.assertEqual(a[9],F(62,2835))
        with self.assertRaises(ValueError):tanh_coefficients(0)

    def test_07_exact_composition(self):
        z=[F(0),F(1)]
        self.assertEqual(tanh_poly(z,3),[F(0),F(1),F(0),F(-1,3)])

    def test_08_gradient_is_exact_fraction(self):
        grad=exact_poly_gradient()
        self.assertEqual(len(grad),2)
        self.assertTrue(all(isinstance(v,F) for v in grad))
        self.assertLess(max(map(abs,grad)),F(1,10**12))

    def test_09_global_strong_convexity(self):
        # Basis phi=(x^2,x^3) has exact diagonal population Gram.
        self.assertEqual(2*GAMMA*moment(4),F(9,25))
        self.assertEqual(2*GAMMA*moment(6),STRONG_CONVEXITY)
        self.assertEqual(moment(5),0)

    def test_10_rigorous_distance_and_global_regret(self):
        out=certificate()
        radius=F(out['rigorous_parameter_error_upper'])
        regret=F(out['rigorous_objective_excess_upper'])
        self.assertLess(radius,F(1,10**11))
        self.assertLess(regret,F(1,10**23))
        self.assertEqual(regret,STRONG_CONVEXITY*radius**2/2)

    def test_11_nonzero_risk_changes_shared_coefficients(self):
        out=certificate()
        err=F(out['rigorous_parameter_error_upper'])
        self.assertGreater(abs(A-F(19,14))-err,F(1,1000))
        self.assertGreater(abs(B-F(-7,5))-err,F(1,100000))

    def test_12_one_weight_insufficient_globally(self):
        out=certificate()
        self.assertGreater(F(out['one_weight_b_zero_excess_lower']),F(1,4))

    def test_13_no_float_in_proof_fields(self):
        out=certificate()
        self.assertEqual(out['all_arithmetic_in_certificate'],
                         'fractions of arbitrary precision integers')
        self.assertTrue(out['rigorous_population_parameter_and_cost_certificate'])
        self.assertFalse(out['general_multilayer_fbsde_certificate'])

    def test_14_failing_candidate_needs_separate_hull(self):
        with self.assertRaises(ValueError):uniform_tanh_argument_bound(F(20),F(-20))

    def test_15_composition_degree(self):
        out=tanh_poly([F(0),F(1),F(0),F(0),F(1)], 9)
        self.assertEqual(len(out)-1,36)


if __name__=='__main__':unittest.main(verbosity=2)
