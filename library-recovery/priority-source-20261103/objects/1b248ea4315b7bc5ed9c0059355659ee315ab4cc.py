"""P2: zero-time and positive-time renewal checkpoint causality checks.

Research-only narrow test: neither a lifetime CTMC certification nor a
proof of long-memory neural sequence utility.
"""
import random
import unittest

from .renewal_event_oracle import RenewalState, advance


class InitialCheckpointGateTests(unittest.TestCase):
    def test_time_zero_cannot_contain_historical_fires(self):
        # Conservation/subset checks pass, but a positive-event history at
        # exactly physical time 0 is impossible under finite Exp rates.
        forged = RenewalState(0., .5, 0., 0., 1., 1.)
        with self.assertRaisesRegex(ValueError, 'initial.*checkpoint'):
            advance(forged, 1., 2., 0.)

    def test_time_zero_cannot_contain_positive_expected_count_alone(self):
        forged = RenewalState(0., .5, .5, .5, 0., 1.)
        with self.assertRaisesRegex(ValueError, 'initial.*checkpoint'):
            advance(forged, 1., 2., 0.)

    def test_time_zero_cannot_contain_changed_killed_distribution(self):
        forged = RenewalState(0., .5, .4, .4, .2, .2)
        with self.assertRaisesRegex(ValueError, 'initial.*checkpoint'):
            advance(forged, 1., 2., 0.)

    def test_positive_time_cannot_have_zero_first_fire(self):
        forged = RenewalState(1., .4, .4, .6, 0., 0.)
        with self.assertRaisesRegex(ValueError, 'positive-time'):
            advance(forged, 1., 2., 0.)

    def test_positive_time_cannot_have_zero_expected_event_count(self):
        forged = RenewalState(1., .5, .5-1e-12, .5, 1e-12, 0.)
        with self.assertRaisesRegex(ValueError, 'positive-time'):
            advance(forged, 1., 2., 0.)

    def test_legitimate_initial_states_are_unchanged(self):
        for active in (0., .2, .5, .8, 1.):
            initial = RenewalState.initial(active)
            self.assertIs(advance(initial, 1., 2., 0.), initial)
            next_state = advance(initial, 1., 2., .1)
            self.assertGreater(next_state.time, 0.)
            self.assertGreater(next_state.ever_fired, 0.)
            self.assertGreater(next_state.expected_count, 0.)
            self.assertIs(advance(next_state, 1., 2., 0.), next_state)

    def test_1000_actual_reachable_transitions_not_rejected(self):
        rng = random.Random(2026103131)
        for _ in range(200):
            state = RenewalState.initial(rng.random())
            for _ in range(5):
                state = advance(state, rng.uniform(.5, 2.0),
                                rng.uniform(.5, 2.0), rng.uniform(.001, .05))
                self.assertIs(advance(state, 1., 1., 0.), state)


if __name__ == '__main__':
    unittest.main()
