import unittest
from fractions import Fraction as Q
from conditional_moments import calculate

class MomentsTests(unittest.TestCase):
    def test_centered_bernoulli_not_generic_dt(self):
        p=(Q(2,3),Q(1,3))
        r=calculate(p,((0,),(1,)),(2,8))
        self.assertEqual(r.conditional_utility,4)
        self.assertEqual(r.conditional_increment_mean,(Q(1,3),))
        self.assertEqual(r.covariance,((Q(2,9),),))
        self.assertEqual(r.utility_covariance,(Q(4,3),))
        self.assertEqual(r.z,(6,))
        self.assertEqual(r.covariance_regression_residual,(0,))
        self.assertTrue(r.martingale_complete)
        self.assertFalse(r.stochastic_fbsde_global_qualified)
    def test_two_independent_drivers_complete_additive(self):
        worlds=((0,0),(0,1),(1,0),(1,1))
        utility=tuple(2*a-3*b for a,b in worlds)
        r=calculate((Q(1,4),)*4,worlds,utility)
        self.assertEqual(r.z,(2,-3))
        self.assertTrue(r.martingale_complete)
    def test_full_rank_incomplete_martingale_representation(self):
        # Nonadditive outcome needs a higher-order driver or orthogonal M.
        worlds=((0,0),(0,1),(1,0),(1,1))
        r=calculate((Q(1,4),)*4,worlds,tuple(a*b for a,b in worlds))
        self.assertTrue(r.full_rank)
        self.assertEqual(r.z,(Q(1,2),Q(1,2)))
        self.assertFalse(r.martingale_complete)
        self.assertGreater(max(map(abs,r.martingale_representation_residual)),0)
        self.assertEqual(r.covariance_regression_residual,(0,0))
    def test_singular_profile_fails_closed(self):
        with self.assertRaises(ValueError):
            calculate((Q(1,2),Q(1,2)),((0,0),(1,1)),(0,1))
    def test_bad_law_and_future_confusion(self):
        wrong=[((1,0),((0,),(1,)),(0,1)),
               ((Q(1,2),Q(1,3)),((0,),(1,)),(0,1)),
               ((.5,.5),((0,),(1,)),(0,1)),
               ((Q(1,2),Q(1,2)),((0,),(1,)),(0,)),
               ((Q(1,2),Q(1,2)),((0,),(1,1)),(0,1))]
        for law in wrong:
            with self.subTest(law=law),self.assertRaises(ValueError):
                calculate(*law)
    def test_constant_driver_cannot_identify_z(self):
        with self.assertRaises(ValueError):
            calculate((Q(1,3),Q(2,3)),((1,),(1,)),(0,2))
    def test_cross_covariance_not_diagonal_shortcut(self):
        # Three-point support, correlated but independent 2D rank.
        worlds=((0,0),(1,0),(1,1))
        r=calculate((Q(1,3),)*3,worlds,(1,4,6))
        self.assertEqual(r.z,(3,2))
        self.assertNotEqual(r.covariance[0][1],0)
        self.assertTrue(r.martingale_complete)

if __name__=='__main__':unittest.main()
