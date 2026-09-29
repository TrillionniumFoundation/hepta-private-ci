import unittest
from scripts.hepta_inference_capacity import evaluate


class CapacityTests(unittest.TestCase):
    def setUp(self):
        self.profile = dict(host="synthetic-planning-test-not-target-host",
            peak_commands_per_second=20, assumed_service_bound_ms=2,
            ordinary_burst=8, terminal_burst=4, queue_wait_budget_ms=30,
            reply_budget_ms=40, shutdown_budget_ms=40, maximum_utilization=0.7)

    def test_feasible_assumptions_never_qualify_production(self):
        result = evaluate(self.profile)
        self.assertTrue(result["assumptions_feasible"])
        self.assertFalse(result["production_qualified"])
        self.assertEqual(result["conditional_queue_wait_ms"], 24)
        self.assertEqual(result["conditional_drain_ms"], 26)

    def test_overload_and_drain_budgets_are_separate(self):
        self.profile.update(peak_commands_per_second=1000, reply_budget_ms=10)
        result = evaluate(self.profile)
        self.assertFalse(result["checks"]["utilization"])
        self.assertFalse(result["checks"]["reply"])
        self.assertTrue(result["checks"]["queue_wait"])

    def test_invalid_numeric_values_fail_closed(self):
        for value in (True, 0, -1, float("nan"), float("inf")):
            with self.subTest(value=value):
                self.profile["assumed_service_bound_ms"] = value
                with self.assertRaises(ValueError):
                    evaluate(self.profile)

    def test_fractional_and_oversize_bursts_are_rejected(self):
        for value in (1.5, 65537):
            self.profile["ordinary_burst"] = value
            with self.assertRaises(ValueError):
                evaluate(self.profile)

    def test_unknown_field_is_not_silently_ignored(self):
        self.profile["activate"] = True
        with self.assertRaises(ValueError):
            evaluate(self.profile)


if __name__ == "__main__":
    unittest.main()
