from __future__ import annotations

import unittest
from pathlib import Path
import re
from unittest.mock import patch

from scripts import hepta_supervisor_ci as base
from scripts.hepta_supervisor_ci_v3 import MINIMUM_VALIDATOR_TESTS
from scripts.hepta_supervisor_ci_v3 import VALIDATOR_TEST_MODULES
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

    def test_python_validator_plan_requires_every_reviewed_case(self):
        required = self.plan.required_python_tests["validator-tests"]
        self.assertGreaterEqual(len(required), MINIMUM_VALIDATOR_TESTS)
        self.assertEqual(self.plan.plans["validator-tests"][0], len(required))
        self.assertEqual(required, base.unittest_test_ids(VALIDATOR_TEST_MODULES))
        self.assertEqual(
            self.plan.plans["validator-tests"][1][4:], list(VALIDATOR_TEST_MODULES)
        )
        self.assertNotIn("validator-tests", self.plan.required_binary_tests)
        self.assertIn("scripts.test_hepta_supervisor_ci", VALIDATOR_TEST_MODULES)
        suite = unittest.TestLoader().loadTestsFromNames(VALIDATOR_TEST_MODULES)

        def identities(tests):
            for test in tests:
                if isinstance(test, unittest.TestSuite):
                    yield from identities(test)
                else:
                    yield test.id()

        self.assertEqual(required, tuple(identities(suite)))

    def test_python_validator_plan_rejects_missing_suite_coverage(self):
        with (
            patch.object(base, "unittest_test_ids", return_value=()),
            self.assertRaisesRegex(ValueError, "lost required coverage"),
        ):
            current_plan()

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

    def test_both_daemon_lanes_bind_existing_current_option_tests(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "codex-rs/hepta-supervisor/src/main_key_tests.rs"
        ).read_text()
        actual = {
            f"key_tests::{name}" for name in re.findall(r"#\[test\]\s+fn (\w+)", source)
        }
        for lane in ("default-products", "products"):
            with self.subTest(lane=lane):
                self.assertEqual(
                    set(
                        self.plan.required_binary_tests[lane][
                            "codex-hepta-supervisor::bin/hepta-supervisord"
                        ]
                    ),
                    actual,
                )


if __name__ == "__main__":
    unittest.main()
