"""R17: exact interval proof plus independent forward/backward sanity checks."""
import unittest
from fractions import Fraction as F
import numpy as np
from certificate import (I, G, RHO, S, LOWER_T, UPPER_T, scalar_gradient, certify,
                         exp_enclosure, log_I, tanh_I, sigmoid_I)
from problem import (KAPPA, leaf, direct, population, objective, transfer, GAMMA)

class ProofAndDynamics(unittest.TestCase):
    def test_01_exact_interval(self):
        a=I.at(F(1,3)); b=I.at(F(7,8))
        self.assertTrue((a*b).contains(F(7,24)))
        self.assertTrue((a/b).contains(F(8,21)))
        self.assertTrue(exp_enclosure(0).contains(1))
        self.assertTrue(log_I(1).contains(0))
        self.assertTrue(tanh_I(0).contains(0))
        self.assertTrue(sigmoid_I(0).contains(F(1,2)))
    def test_02_exact_root_sign(self):
        self.assertLess(scalar_gradient(LOWER_T).hi,0)
        self.assertGreater(scalar_gradient(UPPER_T).lo,0)
        self.assertLess(scalar_gradient(0).hi,0)
    def test_03_global_rational_bounds(self):
        c=certify()
        self.assertLess(F(c['weight_component_error_upper']), F(1,10**13))
        self.assertLess(F(c['true_population_excess_upper']), F(1,10**28))
        self.assertGreater(F(c['one_weight_b_zero_regret_lower']), F(39,100))
        self.assertGreater(F(c['rigorously_nonzero_risk_shift_lower']), F(4,1000))
        self.assertEqual(c['nonproduct_kappa'], '1/4')
    def test_04_exact_two_preference_flips(self):
        for x in (-1,1):
            for p0 in (0,1):
                for e1 in (-1,1):
                    for e2 in (-1,1):
                        t=leaf(.3,.8,x,p0,e1,e2)
                        self.assertEqual(t['p1'],p0^(e1==1))
                        self.assertEqual(t['p2'],t['p1']^(e2==1))
                        self.assertAlmostEqual(t['h2'],.3*.8*x+KAPPA*(.3-.8)**2+e2*x/10)
    def test_05_direct_tree_matches_derivative_model(self):
        for ab in ((0,0),(.5,.3),(-1,-1),(2,.5),(.7,-.4)):
            self.assertAlmostEqual(direct(ab),objective(ab)[0],places=13)
    def test_06_population_even_in_offset(self):
        for t in (-3,-1,0,.5,1,3):
            for d in (0,.1,.4,2):
                self.assertAlmostEqual(population(t,d)[0],population(t,-d)[0],places=12)
                self.assertAlmostEqual(population(t,d)[1][1],-population(t,-d)[1][1],places=11)
    def test_07_global_conditional_offset_curvature(self):
        for t in (-3,-1,0,.5,1,3):
            for d in (-1,0,.5,3):
                self.assertGreaterEqual(population(t,d)[2][1,1],2*GAMMA**2-1e-12)
    def test_08_certified_nonproduct_lower(self):
        for a,b in ((1,1),(.8,.4),(-1,-1),(3,-2),(.1,-.1)):
            t=a*b; d=KAPPA*(a-b)**2
            lhs=population(t,d)[0]-population(t,0)[0]
            self.assertGreaterEqual(lhs+.00000000001,GAMMA**2*d*d)
    def test_09_no_simple_product_quotient(self):
        p=population(1,0)[0]; q=population(1,KAPPA*(2-.5)**2)[0]
        self.assertGreater(q,p+.1)
    def test_10_chain_gradient_matches_fd(self):
        for th in ((.2,.4),(-1.2,.9),(.8,.6),(-.8,-.8)):
            x=np.asarray(th,dtype=float); j,g,h=objective(x)
            for k in range(2):
                e=np.eye(2)[k]*1e-5
                fd=(objective(x+e)[0]-objective(x-e)[0])/(2e-5)
                self.assertAlmostEqual(float(g[k]),fd,places=7)
    def test_11_chain_hessian_matches_fd(self):
        x=np.array([.4,.8]); j,g,h=objective(x)
        for k in range(2):
            e=np.eye(2)[k]*1e-5
            fd=(objective(x+e)[1]-objective(x-e)[1])/(2e-5)
            np.testing.assert_allclose(h[:,k],fd,rtol=1e-6,atol=1e-7)
    def test_12_origin_is_strict_saddle(self):
        j,g,h=objective([0,0]);np.testing.assert_array_equal(g,[0,0])
        self.assertLess(np.linalg.eigvalsh(h)[0],-1.)
        self.assertGreater(j,objective([float(S),float(S)])[0]+.3)
    def test_13_certified_two_global_minima(self):
        s=float(S)
        self.assertAlmostEqual(objective([s,s])[0],objective([-s,-s])[0],places=14)
        self.assertGreater(objective([s,-s])[0],objective([s,s])[0]+.1)
    def test_14_counterfactual_noise_breaks_symmetry(self):
        t=.6;d=.2
        self.assertGreater(abs(population(t,d,'uncorrelated')[0]-population(t,-d,'uncorrelated')[0]),1e-7)
    def test_15_weight_capacity_control(self):
        for a in (-2,-1,0,1,2):
            self.assertGreater(objective([a,0])[0], objective([float(S),float(S)])[0]+.3)
    def test_16_law_transfer_declared(self):
        x=transfer([.8,.4])
        self.assertEqual(set(x), {'uncorrelated_noise','biased_input','product_only'})
        self.assertNotAlmostEqual(x['uncorrelated_noise'],objective([.8,.4])[0],places=9)
    def test_17_analytic_risk_not_neutral(self):
        self.assertGreater(float(LOWER_T-F(56,81)),.004)
    def test_18_exp_domain_fail_closed(self):
        with self.assertRaises(ValueError):exp_enclosure(2)
        with self.assertRaises(ValueError):log_I(-1)

if __name__=='__main__': unittest.main(verbosity=2)
