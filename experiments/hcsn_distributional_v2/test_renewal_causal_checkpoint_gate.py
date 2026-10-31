"""P2 physical checkpoint subset and representable-clock negative/positive gates."""

import math
import random
import unittest

from .renewal_event_oracle import RenewalState, advance


class CausalCheckpointGuards(unittest.TestCase):
    def test_reject_killed_active_larger_than_unconditional_active_even_at_zero_step(self):
        # All old scalar/mass checks pass, but P(no previous FIRE and active)
        # exceeds P(active), which is impossible for a joint process.
        invalid = RenewalState(0., .1, .6, .3, .1, 5.)
        with self.assertRaisesRegex(ValueError, "subset"):
            advance(invalid, 1., 2., 0.)

    def test_reject_killed_refractory_larger_than_unconditional_refractory(self):
        invalid = RenewalState(0., .9, .05, .8, .15, 5.)
        with self.assertRaisesRegex(ValueError, "subset"):
            advance(invalid, 1., 2., 0.)

    def test_reject_erased_positive_physical_time_with_nonzero_event_flow(self):
        # This is a reachable checkpoint: a long segment with extremely low
        # firing hazard accumulates 1e16 time but few events.
        checkpoint = advance(RenewalState.initial(1.), 1e-20, 1., 1e16)
        self.assertEqual(checkpoint.time, 1e16)
        self.assertLess(checkpoint.expected_count, .001)
        self.assertEqual(math.fsum((checkpoint.time, .25)), checkpoint.time)
        with self.assertRaisesRegex(ArithmeticError, "time"):
            advance(checkpoint, 1., 1., .25)
        # A representably large step remains valid and advances the clock.
        advanced = advance(checkpoint, 1., 1., 4.)
        self.assertGreater(advanced.time, checkpoint.time)
        self.assertGreater(advanced.expected_count, checkpoint.expected_count)

    def test_ulp_sized_subset_roundoff_admitted(self):
        a = .5
        tiny = math.ulp(a)
        nearly_consistent = RenewalState(0., a, a+tiny, a-tiny, 0., 0.)
        self.assertEqual(advance(nearly_consistent, 1., 2., 0.), nearly_consistent)

    def test_reachable_multisegment_states_preserve_subset(self):
        rng = random.Random(2026103101)
        for _ in range(1000):
            state = RenewalState.initial(rng.random())
            for _ in range(5):
                state = advance(state, rng.uniform(.05, 12.),
                                rng.uniform(.05, 12.), rng.uniform(.0001, 1.))
                self.assertLessEqual(state.no_fire_active,
                                     state.active+16*math.ulp(1.))
                self.assertLessEqual(state.no_fire_refractory,
                                     (1.-state.active)+16*math.ulp(1.))
                self.assertGreaterEqual(state.expected_count+1e-10,
                                        state.ever_fired)


if __name__ == "__main__":
    unittest.main()
