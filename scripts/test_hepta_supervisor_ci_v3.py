from __future__ import annotations

import unittest

from scripts.hepta_supervisor_ci_v3 import current_plan


class SupervisorCurrentPlanTests(unittest.TestCase):
    def setUp(self):
        self.plan = current_plan()

    def test_current_plan_adds_truth_validators_and_verifier_artifact(self):
        self.assertTrue(
            {"status", "validator-tests", "verifier-artifact"} <= set(self.plan.plans)
        )
        self.assertEqual(
            self.plan.plans["verifier-artifact"][1],
            ["python3", "scripts/hepta_supervisor_artifact_gate.py"],
        )

    def test_daemon_and_offline_tools_have_different_feature_sets(self):
        self.assertIn(
            "offline-authority-tools", self.plan.plans["authority-distribution"][1]
        )
        self.assertIn("offline-authority-tools", self.plan.plans["products"][1])
        self.assertNotIn(
            "offline-authority-tools", self.plan.plans["default-products"][1]
        )
        self.assertIn(
            "qualification,offline-authority-tools", self.plan.plans["lint"][1]
        )

    def test_current_named_tests_bind_new_control_surface(self):
        self.assertIn(
            "daemon::execution::tests::tick_projection_refresh_is_coalesced_at_the_fixed_interval",
            self.plan.required_tests["default"],
        )
        self.assertIn(
            "key_tests::legacy_six_field_verifier_tuple_is_rejected",
            self.plan.required_tests["default-products"],
        )
        self.assertIn(
            "default_daemon_refuses_pinned_bundle_before_fleet_mutation",
            self.plan.required_tests["default-products"],
        )


if __name__ == "__main__":
    unittest.main()
