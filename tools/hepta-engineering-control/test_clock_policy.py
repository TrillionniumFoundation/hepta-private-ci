import unittest

from control_engineering_v2.clock_policy import (
    ClockPolicy,
    FixedEngineeringClock,
    validate_signed_window,
)
from control_engineering_v2.control_plane import EngineeringError


class ClockPolicyTests(unittest.TestCase):
    def test_valid_window_records_age_skew_and_validity(self):
        decision = validate_signed_window(
            1_000,
            2_000,
            now_ns=1_100,
            policy=ClockPolicy(
                maximum_future_skew_ns=10,
                maximum_observation_age_ns=200,
                minimum_validity_ns=1,
                maximum_validity_ns=2_000,
            ),
        )
        self.assertEqual((decision.age_ns, decision.future_skew_ns), (100, 0))
        self.assertEqual(decision.validity_ns, 1_000)

    def test_future_stale_old_and_invalid_validity_fail_closed(self):
        policy = ClockPolicy(
            maximum_future_skew_ns=5,
            maximum_observation_age_ns=20,
            minimum_validity_ns=2,
            maximum_validity_ns=100,
        )
        cases = (
            ((106, 150, 100), "receipt_from_future"),
            ((100, 110, 110), "receipt_stale"),
            ((100, 150, 121), "receipt_too_old"),
            ((100, 101, 100), "receipt_validity_window"),
            ((100, 201, 100), "receipt_validity_window"),
        )
        for (observed, expires, now), code in cases:
            with self.subTest(code=code), self.assertRaisesRegex(EngineeringError, code):
                validate_signed_window(
                    observed,
                    expires,
                    now_ns=now,
                    policy=policy,
                )

    def test_fixed_clock_separates_wall_and_monotonic_time(self):
        clock = FixedEngineeringClock(123, 456)
        self.assertEqual(clock.wall_time_ns(), 123)
        self.assertEqual(clock.monotonic_ns(), 456)


if __name__ == "__main__":
    unittest.main()
