"""P0: reject primary smooth-fit roots whose f64 cost translation destroys reward.

This is a necessary admission guard; not a rigorous binary64 interval proof,
or financial He-Xiong coupled obstacle/QVI certification.
"""
import math
import unittest

from .stopping import Stop, regenerative_boundary, regenerative_boundary_independent
from .test_independent_offset_gate import high_precision_displacement


class PrimaryRewardResolutionGate(unittest.TestCase):
    def test_positive_large_cost_unresolved_firing_reward_is_refused(self):
        for cost in (1e10, 1e12, 1e14, 1e15):
            p=Stop(0., 1., .005, cost, cost-10., 0.)
            with self.subTest(cost=cost), self.assertRaisesRegex(ArithmeticError, 'boundary resolution'):
                regenerative_boundary(p)

    def test_negative_large_cost_unresolved_reward_is_refused(self):
        for cost in (-1e10, -1e12, -1e14):
            p=Stop(0., 1., .005, cost, cost-10., 0.)
            with self.subTest(cost=cost), self.assertRaisesRegex(ArithmeticError, 'boundary resolution'):
                regenerative_boundary(p)

    def test_resolved_large_offset_and_normal_case_are_preserved(self):
        for cost in (0., 1e4, 1e6, 1e8, -1e8):
            p=Stop(0., 1., .005, cost, cost-10., 0.)
            with self.subTest(cost=cost):
                got=regenerative_boundary(p)
                independent=regenerative_boundary_independent(p)
                reference=high_precision_displacement(p)
                self.assertTrue(math.isfinite(got) and got>cost)
                self.assertLessEqual(abs(got-independent), 3*math.ulp(got))
                self.assertLessEqual(abs((got-cost)-reference), 3*math.ulp(got))
        p=Stop(.1,.4,.1,1.,0.,.3)
        self.assertGreater(regenerative_boundary(p),p.cost)

    def test_primary_and_independent_reject_same_known_offset(self):
        p=Stop(0.,1.,.005,1e14,1e14-10.,0.)
        with self.assertRaises(ArithmeticError):
            regenerative_boundary_independent(p)
        with self.assertRaises(ArithmeticError):
            regenerative_boundary(p)


if __name__ == '__main__':
    unittest.main()
