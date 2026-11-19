"""Fail-closed finite f64 one-shot reference boundary, not a finance HX certificate."""
import math
import random
import unittest

from .stopping import Stop, one_shot_boundary, one_shot_value


class OneShotResolutionTests(unittest.TestCase):
    def test_finite_characteristic_root_with_overflowed_inverse_must_refuse(self):
        # Root itself is resolved, but threshold 1/kappa is beyond f64.
        p = Stop(1e308, 1., .1, 0., -1., 0.)
        self.assertTrue(0 < p.kappa < 1e-308)
        with self.assertRaisesRegex(ArithmeticError, 'One-shot boundary'):
            one_shot_boundary(p)
        with self.assertRaisesRegex(ArithmeticError, 'One-shot boundary'):
            one_shot_value(p, 0.)

    def test_cost_rounding_away_strict_threshold_must_refuse(self):
        # 1/kappa ~ 1 is far below the ulp of a 1e308 cost.
        p = Stop(0., 1., .5, 1e308, 0., 0.)
        with self.assertRaisesRegex(ArithmeticError, 'One-shot boundary'):
            one_shot_boundary(p)

    def test_finite_inverse_but_overflowing_cost_addition_must_refuse(self):
        p = Stop(1e307, 1., .1, 1.4e308, 1e308, 0.)
        self.assertTrue(math.isfinite(1 / p.kappa))
        with self.assertRaisesRegex(ArithmeticError, 'One-shot boundary'):
            one_shot_boundary(p)

    def test_finite_boundary_but_nonfinite_immediate_reward_must_refuse(self):
        # Keep the overflow witness reachable through a boundary whose
        # displacement remains well-resolved under the new f64 cost ULP gate.
        p = Stop(5e306, 1., .1, -1e308, -1.2e308, 0.)
        b = one_shot_boundary(p)
        self.assertTrue(math.isfinite(b))
        self.assertTrue(b > p.cost)
        with self.assertRaisesRegex(ArithmeticError, 'One-shot value'):
            one_shot_value(p, 1e308)

    def test_normal_analytic_cases_preserve_values_and_boundary(self):
        cases = (Stop(.1,.4,.1,1.,0.,.3),Stop(-.3,1.,.01,.4,-1.,1.),
                 Stop(.5,.05,1.,1.,0.,0.),Stop(0.,.6,.5,1.,0.,2.))
        for p in cases:
            b = one_shot_boundary(p)
            self.assertGreater(b, p.cost)
            for x in (p.reset, b - .1, b, b + .1):
                expected = x-p.cost if x >= b else (b-p.cost)*math.exp(-p.kappa*(b-x))
                self.assertAlmostEqual(one_shot_value(p,x), expected, delta=1e-12)

    def test_seeded_normal_domain_matches_independent_maximizer(self):
        rng = random.Random(2026103141)
        for i in range(128):
            p = Stop(rng.uniform(-2.,2.), 10**rng.uniform(-1.,.5),
                     10**rng.uniform(-2.,.3), rng.uniform(.1,3.),
                     rng.uniform(-3.,0.), rng.uniform(0.,2.))
            # enforce reset<cost; both independently drawn ranges are strict
            self.assertLess(p.reset, p.cost)
            k = p.kappa
            b = one_shot_boundary(p)
            x = p.reset
            expected = (1/k)*math.exp(-k*(b-x))
            self.assertAlmostEqual(one_shot_value(p,x), expected, delta=2e-12)
            for shift in (-.5,-.1,.1,.5):
                rival = max(x,p.cost+1e-6,b+shift)
                rival_value = (rival-p.cost)*math.exp(-k*(rival-x))
                self.assertLessEqual(rival_value, expected+1e-9, (i,p))


if __name__=='__main__':
    unittest.main()
