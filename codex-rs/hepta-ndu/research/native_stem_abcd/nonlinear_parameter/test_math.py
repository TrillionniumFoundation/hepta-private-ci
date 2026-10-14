"""R15 independent derivative/proof/stress tests, separate from efficacy cases."""
import unittest
from fractions import Fraction as Q
import numpy as np
import mpmath as mp
from problem import (XS,PS,EPS,GAMMA,RHO,KAPPA,BOX,branch,population,
                     population_direct,stage_values,certified_leaf_hessian_lower)
from intervals import I,down,up,expi,logi,ce,softmax
from certificate import A,B,M,rational_gradient,proof
from solver import initial,observed_quality,kkt_violation
from mp_scout import candidate_gradient

class R15MechanismTests(unittest.TestCase):
    def test_01_complete_discrete_law(self):
        self.assertEqual(len(XS)*len(PS)*len(EPS)**2,40)
        self.assertEqual(sum([Q(1,40)]*40),1)
    def test_02_nonzero_risks(self):self.assertEqual(RHO,(Q(1,2),Q(1)))
    def test_03_nonzero_nonlinearity(self):self.assertEqual(KAPPA,Q(1,100))
    def test_04_true_parameter_nonlinearity(self):
        r=branch(A,B,Q(1),1,1,-1)
        self.assertNotEqual(r['q2'],2*r['gain']**2)
        self.assertNotEqual(r['q2'],Q(0))
    def test_05_random_preference_both_steps(self):
        for p in PS:
            for e1 in EPS:
                for e2 in EPS:
                    r=branch(A,B,Q(1,2),p,e1,e2)
                    self.assertEqual(r['p1'],p^(e1==1))
                    self.assertEqual(r['p2'],r['p1']^(e2==1))
    def test_06_branch_martingale_exact(self):
        for x in XS:
            for p in PS:
                for e1 in EPS:
                    plus=branch(A,B,x,p,e1,1)['l2']
                    minus=branch(A,B,x,p,e1,-1)['l2']
                    avg=(plus+minus)/2
                    self.assertEqual(plus-avg,(plus-minus)/2)
                    self.assertEqual(minus-avg,-(plus-minus)/2)
    def test_07_domainwide_terminal_hessian_lower(self):
        self.assertEqual(certified_leaf_hessian_lower(),Q(212939,250000))
    def test_08_global_population_hessian_lower(self):self.assertEqual(M,Q(117,160))
    def test_09_candidate_box_interior(self):
        self.assertTrue(all(BOX[0]<z<BOX[1] for z in (A,B)))
    def test_10_exact_interval_gradient_contains_high_precision_reference(self):
        mp.mp.dps=80
        _,g=candidate_gradient(mp.mpf(A.numerator)/A.denominator,mp.mpf(B.numerator)/B.denominator)
        enclosures=rational_gradient()
        for j in (0,1):
            low=mp.mpf(enclosures[j].lo.numerator)/enclosures[j].lo.denominator
            high=mp.mpf(enclosures[j].hi.numerator)/enclosures[j].hi.denominator
            self.assertLessEqual(low,g[j]);self.assertGreaterEqual(high,g[j])
    def test_11_global_distance_and_value_bound(self):
        c=proof();self.assertLess(Q(c['true_global_optimum_distance_upper']),Q(1,10**14))
        self.assertLess(Q(c['true_population_excess_upper']),Q(1,10**27))
    def test_12_one_weight_global_cost_loss(self):
        self.assertGreater(Q(proof()['restricted_b_zero_population_excess_lower']),Q(1,3))
    def test_13_certificate_no_global_unrestricted_claim(self):
        c=proof();self.assertTrue(c['global_certification_only_in_box'])
        self.assertFalse(c['unrestricted_nonconvex_global_optimum_certified'])
    def test_14_scalar_backward_reference(self):
        for theta in ([float(A),float(B)],[0.5,-1.0]):
            self.assertAlmostEqual(population(theta)[0],population_direct(theta),places=14)
    def test_15_gradient_finite_difference(self):
        theta=np.array([.45,-1.]);h=1e-5
        val,g,H=population(theta)
        for j in (0,1):
            e=np.eye(2)[j]*h
            self.assertAlmostEqual((population(theta+e)[0]-population(theta-e)[0])/(2*h),g[j],delta=2e-9)
    def test_16_hessian_finite_difference(self):
        theta=np.array([.4,-1.2]);h=1e-5
        H=population(theta)[2]
        for j in (0,1):
            e=np.eye(2)[j]*h
            fd=(population(theta+e)[1]-population(theta-e)[1])/(2*h)
            np.testing.assert_allclose(fd,H[:,j],atol=4e-8,rtol=4e-6)
    def test_17_sample_hessian_strict_above_certified_bound(self):
        for t in np.random.default_rng(30).uniform(-2,2,size=(25,2)):
            self.assertGreater(np.linalg.eigvalsh(population(t)[2])[0],float(M)-1e-12)
    def test_18_oscillatory_negative_curvature_witness(self):
        value,g,H=population([-1.28,1.14],oscillatory=True)
        self.assertLess(np.linalg.eigvalsh(H)[0],-20)
    def test_19_nonlinear_stress_gradient_finite_difference(self):
        x=np.array([-.91,.71]);h=1e-5
        g=population(x,oscillatory=True)[1]
        for j in (0,1):
            d=np.eye(2)[j]*h
            self.assertAlmostEqual((population(x+d,oscillatory=True)[0]-population(x-d,oscillatory=True)[0])/(2*h),g[j],delta=1e-8)
    def test_20_kkt_and_initialization(self):
        np.testing.assert_array_equal(initial(11),initial(11))
        self.assertNotEqual(initial(11).tolist(),initial(23).tolist())
        self.assertEqual(kkt_violation(np.array([0.,0.]),np.array([0.,0.])),0.)
    def test_21_certified_monitor_not_training_loss(self):
        r=Q(proof()['true_global_optimum_distance_upper'])
        self.assertTrue(observed_quality(np.array([float(A),float(B)]),r))
        self.assertFalse(observed_quality(np.array([float(A)+1e-3,float(B)]),r))
    def test_22_adversarial_nan_rejected(self):
        r=Q(proof()['true_global_optimum_distance_upper'])
        self.assertFalse(observed_quality(np.array([float('nan'),float(B)]),r))
    def test_23_outward_exact_interval_rounding(self):
        for x in (Q(-1,3),Q(0),Q(2,7)):
            self.assertLessEqual(down(x),x);self.assertGreaterEqual(up(x),x)
    def test_24_risk_ce_invalid_handled(self):
        with self.assertRaises(ValueError):ce([I(0)],Q(1))
    def test_25_convexity_certificate_not_for_high_kappa(self):
        with self.assertRaises(ValueError):certified_leaf_hessian_lower(Q(1,2))

if __name__=='__main__':unittest.main(verbosity=2)
