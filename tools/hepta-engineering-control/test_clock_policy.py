import unittest

from control_engineering_v2.clock import (
    ClockPolicy,
    FixedClock,
    elapsed_within_budget,
    validate_observation_window,
)


class ClockPolicyTests(unittest.TestCase):
    def test_window_accepts_bounded_future_skew_and_rejects_excess(self):
        policy = ClockPolicy(10, 100, 200)
        clock = FixedClock(1_000, 500)
        self.assertEqual(
            validate_observation_window(1_005, 1_100, policy, clock=clock),
            1_000,
        )
        with self.assertRaisesRegex(ValueError, "observation_from_future"):
            validate_observation_window(1_011, 1_100, policy, clock=clock)

    def test_monotonic_budget_is_independent_of_wall_time(self):
        clock = FixedClock(10_000, 20)
        clock.advance(5)
        self.assertEqual(elapsed_within_budget(20, 10, clock=clock), 5)
        with self.assertRaisesRegex(ValueError, "time_budget_exceeded"):
            elapsed_within_budget(20, 4, clock=clock)


if __name__ == "__main__":
    unittest.main()
