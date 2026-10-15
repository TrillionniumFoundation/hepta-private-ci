"""R19 algebra, analytic derivative, bounds, B&B coverage and no-fit-oracle tests."""
import unittest
from fractions import Fraction as F
import numpy as np
from model import ETA, full, qfun, dq, ddq, leaves, independent_direct, components
from global_bound import q, qrange, p_range, zrange, lower, bisect, run, setup, A, B, THRESHOLD, ETA as FETA
from fitters import fit

class Tests(unittest.TestCase):
    def test_01_q_global_bound_and_critical_points(self):
        self.assertEqual(q(F(1)),FETA/2)
        self.assertEqual(q(F(-1)),-FETA/2)
        self.assertEqual(qrange(F(-3),F(3)),(-FETA/2,FETA/2))
        self.assertLessEqual(q(F(100)),FETA/2)
    def test_02_qrange_exact_endpoints_and_critical(self):
        for lo,hi in ((F(-3),F(-2)),(F(-2),F(0)),(F(0),F(2)),(F(3,2),F(3))):
            mini,maxi=qrange(lo,hi)
            for k in range(11):
                value=q(lo+(hi-lo)*F(k,10))
                self.assertTrue(mini<=value<=maxi)
    def test_03_product_and_square_ranges(self):
        self.assertEqual(p_range(F(-2),F(3)),(0,9))
        self.assertEqual(p_range(F(1),F(2)),(1,4))
        (tl,th),(ul,uh),maxq=zrange(F(1),F(2),F(0),F(1))
        for a,b in ((F(1),F(0)),(F(1),F(1)),(F(2),F(1)),(F(2),F(0))):
            self.assertTrue(tl<=a*b<=th)
            self.assertTrue(ul<=(a-b)**2/4+q(a)<=uh)
    def test_04_nonquotient_signed_symmetry_break(self):
        a,b=1.3,.6
        self.assertNotAlmostEqual(full((a,b),ETA)[0],full((-a,-b),ETA)[0],places=7)
        self.assertAlmostEqual(full((a,b),0)[0],full((-a,-b),0)[0],places=12)
    def test_05_same_t_d_different_cost(self):
        a,b=1.7,.42
        self.assertNotAlmostEqual(full((a,b),ETA)[0],full((b,a),ETA)[0],places=7)
        self.assertAlmostEqual(full((a,b),0)[0],full((b,a),0)[0],places=12)
    def test_06_known_old_parent_equivalence(self):
        from pathlib import Path
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'asymmetric_2d'))
        from problem import objective
        for theta in ((0.,0.),(1.67,.42),(-1.67,-.42),(.5,1.)):
            self.assertAlmostEqual(full(theta,0)[0],objective(theta,shift=1.)[0],places=13)
    def test_07_leaf_enumeration(self):
        for eta in (0,ETA):
            ls=leaves((1.67,.42),eta)
            self.assertEqual(ls.shape,(16,10))
            self.assertEqual(len(set(map(tuple,ls[:,:4]))),16)
    def test_08_independent_nested_utility(self):
        for eta in (0,ETA):
            for theta in ((0.,0.),(.5,.4),(1.67,.42),(-1.67,-.42),(.42,1.67)):
                self.assertAlmostEqual(full(theta,eta)[0],independent_direct(theta,eta),places=13)
    def test_09_analytic_gradient_fd(self):
        for eta in (0,ETA):
            for theta in ((.6,.8),(1.67,.42),(-.5,1.3)):
                v=np.array(theta)
                G=full(v,eta)[1]
                for axis in np.eye(2):
                    h=1e-5
                    fd=(full(v+h*axis,eta)[0]-full(v-h*axis,eta)[0])/(2*h)
                    self.assertAlmostEqual(fd,float(axis@G),places=7)
    def test_10_analytic_hessian_fd(self):
        for eta in (0,ETA):
            v=np.array([1.3,.77]);H=full(v,eta)[2]
            for axis in np.eye(2):
                h=1e-5
                fd=(full(v+h*axis,eta)[1]-full(v-h*axis,eta)[1])/(2*h)
                np.testing.assert_allclose(fd,H@axis,atol=2e-8,rtol=1e-6)
    def test_11_stationary_origin_not_global(self):
        self.assertAlmostEqual(full((0,0),ETA)[0],full((0,0),0)[0])
        self.assertGreater(full((0,0),ETA)[0],full((1.64,.423),ETA)[0])
    def test_12_parent_convexity_constant(self):
        s=setup();self.assertEqual(s['m'],F(81,50))
        self.assertLess(s['exact_candidate_absolute_upper'],F(9,4))
    def test_13_exact_interval_branch(self):
        box=(F(-3),F(3),F(-3),F(3))
        left,right=bisect(box)
        self.assertEqual(left[1],right[0])
        self.assertEqual(left[0],box[0]);self.assertEqual(right[1],box[1])
        self.assertLessEqual(lower(box,setup()),lower(left,setup()))
        self.assertLessEqual(lower(box,setup()),lower(right,setup()))
    def test_14_root_lower_bound_numerical_crosscheck(self):
        s=setup();root=(F(-3),F(3),F(-3),F(3));lb=float(lower(root,s))
        cand=full((float(A),float(B)),ETA)[0]
        rng=np.random.default_rng(139)
        for _ in range(30):
            x=rng.uniform(-3,3,size=2)
            self.assertGreater(full(x,ETA)[0]-cand,lb-5e-12)
    def test_15_bnb_frozen_threshold_and_census(self):
        out=run(limit=50000,threshold=THRESHOLD)
        self.assertTrue(out['passes_frozen_global_threshold'])
        self.assertLessEqual(F(out['global_cost_regret_rigorous_upper']),THRESHOLD)
        self.assertEqual(out['frontier_count'],out['nodes_split']+1)
    def test_16_no_unbounded_claim(self):
        out=run()
        self.assertFalse(out['global_optimum_unique_proven'])
        self.assertFalse(out['exact_quotient_convexification_valid'])
    def test_17_short_fit_zero_oracle(self):
        s=fit((0.,0.),'trust-exact',ETA,cap=.08)
        self.assertEqual(len(s['theta']),2)
        self.assertGreaterEqual(len(s['history']),1)
    def test_18_bad_inputs_rejected(self):
        with self.assertRaises(ValueError):fit((0,0),'BADC',ETA)
        with self.assertRaises(ValueError):qrange(F(2),F(1))
        with self.assertRaises(ValueError):run(limit=0)

if __name__=='__main__':unittest.main(verbosity=2)
