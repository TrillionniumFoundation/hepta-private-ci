import unittest

from control_engineering_v2.capacity_policy import (
    SQLiteCapacityObservation,
    SQLiteCapacityPolicy,
    evaluate_sqlite_capacity,
)


class CapacityPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = SQLiteCapacityPolicy(
            "target-a",
            1_000,
            100,
            10_000,
            100,
            100,
            50,
            500,
            80,
        )

    def test_warning_threshold_and_hard_limit_are_distinct(self):
        warning = evaluate_sqlite_capacity(
            self.policy,
            SQLiteCapacityObservation(800, 1, 1, 1, 1, 1, 1),
        )
        self.assertTrue(warning.within_hard_limits)
        self.assertTrue(warning.migration_required)
        self.assertIn("migration_threshold:database_bytes", warning.reasons)
        hard = evaluate_sqlite_capacity(
            self.policy,
            SQLiteCapacityObservation(1_001, 1, 1, 1, 1, 1, 1),
        )
        self.assertFalse(hard.within_hard_limits)
        self.assertIn("hard_limit:database_bytes", hard.reasons)


if __name__ == "__main__":
    unittest.main()
