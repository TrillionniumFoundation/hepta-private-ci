"""Research-only P2 causal checkpoint admission at vanishing physical mass."""
import math
import random
import unittest

import numpy as np
from scipy.linalg import expm

from .renewal_event_oracle import RenewalState, advance


class LocalSubsetUlpTests(unittest.TestCase):
    def test_empty_active_cannot_claim_unfired_active_particle(self):
        # Positive no-fire active mass on an exact zero unconditional active
        # population is impossible. The old 16*ulp(1) gate accepted it.
        bad = RenewalState(0., 0., 1e-16, 1.-1e-16, 0., 0.)
        self.assertEqual(math.fsum((bad.no_fire_active,
                                    bad.no_fire_refractory,bad.ever_fired)), 1.)
        with self.assertRaisesRegex(ValueError, 'subset'):
            advance(bad, 1., 1., 0.)

    def test_empty_refractory_cannot_claim_unfired_refractory_particle(self):
        bad = RenewalState(0., 1., 0., 1e-16, 1.-1e-16, 1.)
        self.assertEqual(math.fsum((bad.no_fire_active,
                                    bad.no_fire_refractory,bad.ever_fired)), 1.)
        with self.assertRaisesRegex(ValueError, 'subset'):
            advance(bad, 1., 1., 0.)

    def test_binary64_one_ulp_roundoff_near_half_remains_admissible(self):
        a = .5
        almost = RenewalState(0., a, a+math.ulp(a), a-math.ulp(a), 0., 0.)
        self.assertIs(advance(almost, 1., 2., 0.), almost)

    def test_real_subnormal_scale_probability_passes_when_causal(self):
        for t in (1e-12, 1e-17, 1e-20):
            with self.subTest(t=t):
                x = advance(RenewalState.initial(0.),1.,1.,t)
                self.assertGreater(x.active, 0.)
                self.assertLessEqual(x.no_fire_active, x.active)
                self.assertIs(advance(x, 1., 1., 0.), x)

    def test_5000_reachable_transitions_are_not_rejected(self):
        rng = random.Random(2026103101)
        for _ in range(1000):
            state = RenewalState.initial(rng.random())
            for _ in range(5):
                state = advance(state, rng.uniform(.05,12.),
                                rng.uniform(.05,12.),rng.uniform(.0001,1.))
                self.assertIs(advance(state,1.,1.,0.),state)

    def test_independent_expm_64_random_cases(self):
        rng = random.Random(2026103017)
        for _ in range(64):
            lam, gamma = rng.uniform(.1,10.), rng.uniform(.1,10.)
            t, a = rng.uniform(.001,3.), rng.uniform(0.,1.)
            v = advance(RenewalState.initial(a),lam,gamma,t)
            physical = np.array([a,1-a]) @ expm(np.array(
                [[-lam,lam],[gamma,-gamma]])*t)
            killed = np.array([a,1-a]) @ expm(np.array(
                [[-lam,0],[gamma,-gamma]])*t)
            self.assertAlmostEqual(v.active, physical[0], delta=4e-12)
            self.assertAlmostEqual(v.no_fire_active,killed[0],delta=4e-12)
            self.assertAlmostEqual(v.no_fire_refractory,killed[1],delta=4e-12)

    def test_unchanged_saturated_cdf_still_rejects(self):
        prefix = advance(RenewalState.initial(1.),1.,1.,30.)
        with self.assertRaisesRegex(ArithmeticError,'first-fire CDF increment erased'):
            advance(prefix,1.,1.,1e-4)


if __name__ == '__main__':
    unittest.main()
