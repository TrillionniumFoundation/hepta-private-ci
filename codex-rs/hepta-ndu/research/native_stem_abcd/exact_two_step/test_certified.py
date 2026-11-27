"""R14: full-law branch, exact rational proof and independent high precision checks."""
import unittest
from fractions import Fraction as Q
import numpy as np
import mpmath as mp
from problem import XS,PS,EPS,GAMMA,RHO,phi,leaves,evaluate,evaluate_with_risk
from intervals import I,down,up,expi,exp_exact,logi,log_exact,ce,softmax
from certificate import A,B,STRONG_CONVEXITY,gradient_enclosure,certificate,risk_neutral_optimum,moment_support
from solver import population,initial,verified_quality,QUALITY
from scout import calc,mpf
from stress import evaluate_continuous

class CertifiedTests(unittest.TestCase):
    def test_01_full_law_normalization(self):
        self.assertEqual(len(XS)*len(PS)*len(EPS)**2,40)
        self.assertEqual(sum([Q(1,40)]*40),1)
        self.assertEqual(XS,(Q(-1),Q(-1,2),Q(0),Q(1,2),Q(1)))
    def test_02_risks_strictly_positive(self):
        self.assertEqual(RHO,(Q(1,2),Q(1)))
    def test_03_forward_and_preference_branch_coupling(self):
        for p0 in PS:
            for e1 in EPS:
                l1,g1,p1,last=leaves(A,B,Q(1,2),p0,e1)
                self.assertEqual(p1,p0^(e1==1))
                self.assertEqual([z[2] for z in last],[p1^(e2==1) for e2 in EPS])
                self.assertEqual(len(g1),2)
                self.assertEqual(len(last),2)
    def test_04_backward_martingale_coefficients(self):
        for x in XS:
            for p0 in PS:
                for e1 in EPS:
                    l1,g1,p1,last=leaves(A,B,x,p0,e1)
                    plus,minus=last[1][0],last[0][0]
                    avg=(plus+minus)/2
                    Z=plus-minus
                    self.assertEqual(plus-avg,Z/2)
                    self.assertEqual(minus-avg,-Z/2)
    def test_05_exact_moment_gram_strong_bound(self):
        self.assertEqual(moment_support(4),Q(17,40))
        self.assertEqual(moment_support(5),0)
        self.assertEqual(moment_support(6),Q(13,32))
        self.assertEqual(STRONG_CONVEXITY,2*GAMMA*moment_support(6))
    def test_06_outward_rounding_negative_and_tiny(self):
        for q in (Q(-1,3),Q(-1,10**100),Q(0),Q(7,19),Q(10**20)):
            self.assertLessEqual(down(q),q)
            self.assertGreaterEqual(up(q),q)
    def test_07_interval_arithmetic_endpoints_and_denominator(self):
        a=I(Q(-2,3),Q(7,9)); b=I(Q(3,7),Q(9,8))
        vals=[Q(-2,3)*Q(9,8),Q(7,9)*Q(9,8),Q(-2,3)*Q(3,7),Q(7,9)*Q(3,7)]
        self.assertLessEqual((a*b).lo,min(vals))
        self.assertGreaterEqual((a*b).hi,max(vals))
        self.assertLessEqual((a/b).lo,Q(-2,3)/Q(3,7))
    def test_08_exp_interval_contains_independent_mp(self):
        mp.mp.dps=90
        for z in (Q(-7,3),Q(-1,2),Q(0),Q(1,5),Q(5)):
            v=exp_exact(z)
            truth=mp.exp(mpf(z))
            self.assertLessEqual(mpf(v.lo),truth)
            self.assertGreaterEqual(mpf(v.hi),truth)
    def test_09_log_interval_contains_independent_mp(self):
        mp.mp.dps=90
        for z in (Q(1,13),Q(1,2),Q(1),Q(3,2),Q(2),Q(23,5),Q(400)):
            v=log_exact(z);truth=mp.log(mpf(z))
            self.assertLessEqual(mpf(v.lo),truth)
            self.assertGreaterEqual(mpf(v.hi),truth)
    def test_10_certified_nested_gradient_contains_independent_mp(self):
        mp.mp.dps=85
        _,truth=calc(mpf(A),mpf(B))
        box=gradient_enclosure()
        for j in range(2):
            self.assertLessEqual(mpf(box[j].lo),truth[j])
            self.assertGreaterEqual(mpf(box[j].hi),truth[j])
    def test_11_analytic_gradient_equals_independent_mp(self):
        x=(.64,-.93)
        f,g,H=population(x)
        mf,mg=calc(mp.mpf(x[0]),mp.mpf(x[1]))
        self.assertAlmostEqual(f,float(mf),places=13)
        np.testing.assert_allclose(g,[float(z) for z in mg],atol=5e-15,rtol=1e-13)
    def test_12_gradient_and_Hessian_finite_differences(self):
        x=np.array([.8,-1.2]);h=1e-5
        f,g,H=population(x)
        for j in range(2):
            e=np.eye(2)[j]*h
            fd_f=(population(x+e)[0]-population(x-e)[0])/(2*h)
            fd_g=(population(x+e)[1]-population(x-e)[1])/(2*h)
            self.assertAlmostEqual(fd_f,g[j],delta=1e-9)
            np.testing.assert_allclose(fd_g,H[:,j],atol=1e-8,rtol=1e-6)
    def test_13_all_sample_Hessians_above_global_bound(self):
        rng=np.random.default_rng(44)
        for x in rng.normal(size=(12,2)):
            vals=np.linalg.eigvalsh(population(x)[2]);self.assertGreater(vals[0],float(STRONG_CONVEXITY)-1e-11)
    def test_14_certificate_global_error_thresholds(self):
        j=certificate()
        self.assertLess(Q(j['distance_to_unique_global_optimum_upper']),Q(1,10**10))
        self.assertLess(Q(j['true_population_cost_excess_upper']),Q(1,10**18))
    def test_15_one_weight_global_exclusion(self):
        j=certificate()
        self.assertGreater(Q(j['global_one_weight_b_zero_excess_lower']),Q(1,3))
    def test_16_exact_risk_neutral_reference_independent(self):
        (a,b),H,d=risk_neutral_optimum()
        self.assertEqual(H[0][0]*a+H[0][1]*b,-d[0])
        self.assertEqual(H[1][0]*a+H[1][1]*b,-d[1])
        _,g=evaluate_with_risk([float(a),float(b)],0.)
        self.assertLess(np.max(abs(g)),1e-12)
        self.assertGreater(abs(A-a),Q(1,10000))
    def test_17_wrong_population_cannot_be_covered_by_old_certificate(self):
        a,b=[float(A),float(B)]
        _,g=evaluate_continuous((a,b),32)
        self.assertGreater(np.linalg.norm(g),.1)
        self.assertFalse(certificate()['uniform_continuous_input_certificate'])
    def test_18_exact_qualification_never_accepts_wrong_weight(self):
        d=Q(certificate()['distance_to_unique_global_optimum_upper'])
        self.assertTrue(verified_quality(np.array([float(A),float(B)]),d))
        self.assertFalse(verified_quality(np.array([float(A)+1e-4,float(B)]),d))
        self.assertFalse(verified_quality(np.array([float('nan'),float(B)]),d))
    def test_19_deterministic_matched_initials(self):
        np.testing.assert_array_equal(initial(23),initial(23))
        self.assertFalse(np.array_equal(initial(23),initial(47)))
    def test_20_bad_adversarial_ill_formed_problem_is_rejected(self):
        with self.assertRaises(ValueError):ce([I(1)],Q(1,2))
        with self.assertRaises(ValueError):log_exact(Q(0))
        with self.assertRaises(ZeroDivisionError):I(1)/I(Q(-1),Q(1))

if __name__=='__main__':unittest.main(verbosity=2)
