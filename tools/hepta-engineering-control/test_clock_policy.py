import unittest

from control_engineering_v2.clock_policy import (
    ClockSkewPolicy,
    STRICT_CLOCK_POLICY,
    validate_signed_window,
)


class ClockPolicyTests(unittest.TestCase):
    def test_strict_policy_preserves_no_future_observation_rule(self):
        with self.assertRaisesRegex(ValueError, "future"):
            validate_signed_window(
                101,
                200,
                100,
                STRICT_CLOCK_POLICY,
                error_code="future",
            )

    def test_measured_skew_age_and_validity_are_all_enforced(self):
        policy = ClockSkewPolicy(5, 20, 50)
        validate_signed_window(104, 140, 100, policy, error_code="window")
        with self.assertRaisesRegex(ValueError, "window"):
            validate_signed_window(106, 140, 100, policy, error_code="window")
        with self.assertRaisesRegex(ValueError, "window"):
            validate_signed_window(70, 110, 100, policy, error_code="window")
        with self.assertRaisesRegex(ValueError, "window"):
            validate_signed_window(90, 141, 100, policy, error_code="window")

    def test_invalid_policy_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid_maximum_future_skew_ns"):
            ClockSkewPolicy(-1, 1, 1)
        with self.assertRaisesRegex(ValueError, "invalid_maximum_validity_ns"):
            ClockSkewPolicy(0, 1, 0)


if __name__ == "__main__":
    unittest.main()
