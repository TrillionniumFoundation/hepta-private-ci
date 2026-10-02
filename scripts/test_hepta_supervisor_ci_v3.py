import hashlib
import shlex
import unittest
from pathlib import Path
import re
from unittest.mock import patch

from scripts import hepta_supervisor_ci as base
from scripts.hepta_ci_exec import observed_test_counts
from scripts import test_hepta_supervisor_ci as ci_fixtures
from scripts.test_hepta_supervisor_evidence import transcript
from scripts.hepta_supervisor_ci_v3 import MINIMUM_VALIDATOR_TESTS
from scripts.hepta_supervisor_ci_v3 import VALIDATOR_TEST_MODULES
from scripts.hepta_supervisor_ci_v3 import current_plan


class SupervisorCurrentPlanTests(unittest.TestCase):
    def setUp(self):
        self.plan = current_plan()

    def validate_lane(self, lane, binaries):
        fixture = ci_fixtures.ReceiptTests()
        fixture.setUp()
        log = transcript(binaries)
        record = {
            **fixture.record,
            "command": self.plan.plans[lane][1],
            "minimum_tests": self.plan.plans[lane][0],
            "observed_passed_tests": sum(len(tests) for tests in binaries.values()),
            "log_bytes": len(log),
            "log_sha256": hashlib.sha256(log).hexdigest(),
        }
        with (
            patch.dict(base.PLANS, self.plan.plans, clear=True),
            patch.dict(
                base.REQUIRED_BINARY_TESTS, self.plan.required_binary_tests, clear=True
            ),
        ):
            return base.validate_record(
                lane,
                record,
                fixture.context,
                fixture.identity,
                log,
                observed_test_counts,
            )

    def source_test_names(self, relative):
        root = Path(__file__).resolve().parents[1]
        source = (root / relative).read_text()
        names = tuple(
            re.findall(r"#\[(?:tokio::)?test[^\]]*\]\s+(?:async )?fn (\w+)", source)
        )
        self.assertTrue(names, relative)
        return names

    def test_fleet_library_receipts_require_each_source_publication_repair(self):
        canonical = (
            "workspace_sweep_agrees_with_pairwise_oracle_for_nested_and_sibling_paths"
        )
        self.assertIn(
            canonical,
            self.source_test_names("codex-rs/hepta-fleet/src/registry_tests.rs"),
        )
        required = (
            tuple(
                f"release::{module}::{name}"
                for file, module in (
                    ("release_copy_tests.rs", "copy_tests"),
                    ("release_publish_tests.rs", "publish_tests"),
                )
                for name in self.source_test_names("codex-rs/hepta-fleet/src/" + file)
            )
            + (f"registry::tests::{canonical}",)
            + tuple(
                f"regular_file::tests::{name}"
                for name in self.source_test_names(
                    "codex-rs/hepta-fleet/src/regular_file_tests.rs"
                )
            )
        )
        fleet_binary = "codex-hepta-fleet"
        self.assertEqual(
            required, self.plan.required_binary_tests["fleet-library"][fleet_binary]
        )
        binaries = {fleet_binary: required}
        evidence = self.validate_lane("fleet-library", binaries)
        self.assertEqual(evidence["required_tests"], len(required))
        for name in required:
            for replacement in ("missing", "prefix", "binary"):
                altered = {
                    fleet_binary: tuple(
                        test if test != name else "unreviewed_publication_case"
                        for test in required
                    )
                }
                if replacement == "prefix":
                    altered[fleet_binary] = tuple(
                        test if test != name else name + "_unreviewed_prefix"
                        for test in required
                    )
                elif replacement == "binary":
                    altered[fleet_binary] = tuple(
                        test for test in required if test != name
                    )
                    altered[base.PACKAGE] = (name,)
                with (
                    self.subTest(missing=name, replacement=replacement),
                    self.assertRaises(ValueError),
                ):
                    self.validate_lane("fleet-library", altered)

    def test_supervisor_library_receipts_cannot_credit_fleet_passes(self):
        fleet_binaries = self.plan.required_binary_tests["fleet-library"]
        fleet_name = next(iter(fleet_binaries.values()))[0]
        for lane in ("default", "production", "qualification-lib"):
            binaries = self.plan.required_binary_tests[lane]
            altered = {binary: tests[1:] for binary, tests in binaries.items()}
            altered["codex-hepta-fleet"] = (fleet_name,)
            with self.subTest(lane=lane), self.assertRaises(ValueError):
                self.validate_lane(lane, altered)

    def test_receipts_reject_each_missing_or_prefixed_current_repair_success(self):
        # Derive protected cases from the actual repair test modules. The
        # transcript and aggregate count stay valid after replacing a PASS;
        # only exact mandatory identity can reject the weaker receipt.
        critical = []
        resolution = "signed_explicit_rollback_source_restoration_can_recover_without_new_dispatch"
        self.assertIn(
            resolution,
            self.source_test_names(
                "codex-rs/hepta-supervisor/src/release_signed_recovery_tests.rs"
            ),
        )
        critical.append(
            "supervisor::tests::release_retry_tests::signed_recovery::" + resolution
        )
        cached = (
            "cached_catalog_start_is_readmitted_before_any_lifecycle_or_process_effect"
        )
        self.assertIn(
            cached,
            self.source_test_names(
                "codex-rs/hepta-supervisor/src/release_admission_tests.rs"
            ),
        )
        critical.append("supervisor::tests::release_retry_tests::admission::" + cached)
        process_fault = "process_recovery_fault_does_not_hide_signed_recovery_required"
        self.assertIn(
            process_fault,
            self.source_test_names("codex-rs/hepta-supervisor/src/supervisor_tests.rs"),
        )
        critical.append("supervisor::tests::" + process_fault)
        for file, namespace in (
            (
                "signed_effect_boundary_tests.rs",
                "daemon::authority_tests::effect_boundary_tests",
            ),
            (
                "daemon_emergency_kill_tests.rs",
                "daemon::authority_tests::emergency_kill_tests",
            ),
            (
                "signed_constructor_replay_tests.rs",
                "supervisor::tests::release_retry_tests::signed_recovery::constructor_replay",
            ),
            (
                "signed_constructor_containment_tests.rs",
                "supervisor::tests::release_retry_tests::signed_recovery::constructor_replay::containment",
            ),
            (
                "signed_constructor_preparation_tests.rs",
                "supervisor::tests::release_retry_tests::signed_recovery::constructor_replay::preparation",
            ),
            ("daemon_read_projection_tests.rs", "daemon::read_view::projection_tests"),
            (
                "automatic_restart_event_tests.rs",
                "supervisor::tests::automatic_restart_event_tests",
            ),
            (
                "tick_control_fault_tests.rs",
                "supervisor::tests::tick_control_fault_tests",
            ),
            (
                "tick_control_deadline_tests.rs",
                "supervisor::tests::tick_control_fault_tests::deadline_tests",
            ),
            (
                "tick_control_budget_tests.rs",
                "supervisor::tests::tick_control_fault_tests::deadline_tests::budget_tests",
            ),
            (
                "tick_matrix_fault_tests.rs",
                "supervisor::tests::tick_control_fault_tests::matrix_fault_tests",
            ),
            (
                "tick_pending_deadline_tests.rs",
                "supervisor::tests::tick_control_fault_tests::pending_deadline_tests",
            ),
            ("matrix_control_order_tests.rs", "matrix::tick::tests::control_order"),
            ("daemon_startup_tests.rs", "daemon::startup_tests"),
            (
                "constructor_recovery_probe_tests.rs",
                "supervisor::recovery_probe::tests",
            ),
            (
                "constructor_absence_recovery_tests.rs",
                "supervisor::tests::constructor_absence_recovery_tests",
            ),
            ("unix_peer_identity_tests.rs", "unix::peer_identity_tests"),
            ("unix_control_io_tests.rs", "unix::control_io::tests"),
            ("authority_bundle_open_tests.rs", "authority_bundle::open_tests"),
            ("regular_file_io_tests.rs", "regular_file_io::tests"),
            ("directory_io_tests.rs", "directory_io::tests"),
            ("matrix_binding_io_tests.rs", "matrix::binding_io_tests"),
            (
                "constructor_hydration_tests.rs",
                "supervisor::constructor_hydration::tests",
            ),
            (
                "constructor_hydration_recovery_tests.rs",
                "supervisor::tests::constructor_hydration_recovery_tests",
            ),
            ("control_intent_write_tests.rs", "control_intent::write_tests"),
        ):
            critical.extend(
                f"{namespace}::{name}"
                for name in self.source_test_names(
                    "codex-rs/hepta-supervisor/src/" + file
                )
            )
        for lane in ("default", "production", "qualification-lib"):
            binaries = self.plan.required_binary_tests[lane]
            self.validate_lane(lane, binaries)
            for name in critical:
                for replacement in ("missing", "prefix", "binary"):
                    if replacement == "binary":
                        altered = {
                            binary: tuple(test for test in tests if test != name)
                            for binary, tests in binaries.items()
                        }
                        altered[f"{base.PACKAGE}::unreviewed_binary"] = (name,)
                    else:
                        substitute = (
                            "unreviewed_repair_case"
                            if replacement == "missing"
                            else name + "_unreviewed_prefix"
                        )
                        altered = {
                            binary: tuple(
                                substitute if test == name else test for test in tests
                            )
                            for binary, tests in binaries.items()
                        }
                    with (
                        self.subTest(lane=lane, missing=name, replacement=replacement),
                        self.assertRaises(ValueError),
                    ):
                        self.validate_lane(lane, altered)

    def test_product_receipts_require_exact_restart_projection_and_roster_pairs(self):
        pairs = []
        for target in (
            "restart_budget",
            "restart_budget_recovery",
            "robrix_control_projection",
        ):
            pairs.extend(
                (f"{base.PACKAGE}::{target}", name)
                for name in self.source_test_names(
                    f"codex-rs/hepta-supervisor/tests/{target}.rs"
                )
            )
        roster = "product_binary_serves_the_complete_256_agent_roster"
        self.assertIn(
            roster,
            self.source_test_names("codex-rs/hepta-supervisor/tests/daemon_product.rs"),
        )
        pairs.append((f"{base.PACKAGE}::daemon_product", roster))
        for lane in ("default-products", "products"):
            binaries = self.plan.required_binary_tests[lane]
            self.validate_lane(lane, binaries)
            for binary, name in pairs:
                for substitute_binary in (binary, f"{base.PACKAGE}::unreviewed_binary"):
                    altered = {
                        key: tuple(
                            test for test in tests if key != binary or test != name
                        )
                        for key, tests in binaries.items()
                    }
                    substitute_name = (
                        "unreviewed_missing_case"
                        if substitute_binary == binary
                        else name
                    )
                    altered[substitute_binary] = (
                        *altered.get(substitute_binary, ()),
                        substitute_name,
                    )
                    with (
                        self.subTest(
                            lane=lane,
                            binary=binary,
                            missing=name,
                            replacement=substitute_binary,
                        ),
                        self.assertRaises(ValueError),
                    ):
                        self.validate_lane(lane, altered)

    def test_deep_qualification_executes_all_restart_and_projection_targets(self):
        root = Path(__file__).resolve().parents[1]
        text = (
            root / ".github/workflows/runtime-supervisor-deep-qualification.yml"
        ).read_text()
        step = text.split(
            "      - name: Restart budget and Robrix projection regressions\n", 1
        )[1].split("      - name:", 1)[0]
        command = shlex.split(
            " ".join(step.split("        run: >-\n", 1)[1].splitlines())
        )
        self.assertEqual(command[:5], ["just", "test", "--locked", "-p", base.PACKAGE])
        self.assertEqual(
            command[command.index("--features") + 1],
            "qualification,offline-authority-tools",
        )
        self.assertEqual(command[command.index("--retries") + 1], "0")
        targets = [
            command[index + 1]
            for index, argument in enumerate(command)
            if argument == "--test"
        ]
        self.assertEqual(
            targets,
            ["restart_budget", "restart_budget_recovery", "robrix_control_projection"],
        )
        self.assertNotIn("--no-fail-fast", command)

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
            f"key_tests::{name}"
            for name in re.findall(
                r"#\[(?:tokio::)?test[^\]]*\]\s+(?:async )?fn (\w+)", source
            )
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
