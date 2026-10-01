#!/usr/bin/env python3
"""Current runtime.supervisor CI plan layered on the stable receipt engine."""

from __future__ import annotations

from dataclasses import dataclass

if __package__:
    from . import hepta_supervisor_ci as base
else:
    import hepta_supervisor_ci as base


CURRENT_REPAIR_LIBRARY_REQUIREMENTS = (
    "daemon::read_view::projection_tests::epoch_and_invalidation_discard_all_reuse_preimages",
    "daemon::read_view::projection_tests::external_fleet_cas_and_removal_change_only_the_affected_projection",
    "daemon::read_view::projection_tests::failed_ownership_capture_invalidates_then_rebuilds_every_agent",
    "daemon::read_view::projection_tests::health_without_revision_change_is_dirty_but_diagnostic_rings_are_not",
    "daemon::read_view::projection_tests::lease_readiness_is_recaptured_even_when_every_status_is_reused",
    "daemon::read_view::projection_tests::matrix_and_hidden_cas_metadata_changes_cannot_reuse_an_old_status",
    "daemon::read_view::projection_tests::poisoned_view_never_reuses_or_serves_prior_contents",
    "daemon::read_view::projection_tests::unchanged_capture_reuses_every_agent_but_refreshes_capture_time",
    "supervisor::tests::automatic_restart_event_tests::automatic_restart_cleanup_retry_preserves_one_admission_and_charge",
    "supervisor::tests::automatic_restart_event_tests::automatic_restart_admission_io_failure_is_a_fault_without_success_event",
    "supervisor::tests::automatic_restart_event_tests::automatic_restart_admission_and_main_cleanup_faults_are_both_reported",
    "supervisor::tests::automatic_restart_event_tests::automatic_restart_admission_and_companion_cleanup_faults_are_both_reported",
    "supervisor::tests::tick_control_fault_tests::main_signal_error_survives_poll_failure_without_duplicate_report",
    "supervisor::tests::tick_control_fault_tests::first_companion_signal_error_survives_poll_failure_and_successful_retry",
    "supervisor::tests::tick_control_fault_tests::first_companion_signal_error_survives_main_control_failure",
    "supervisor::tests::tick_control_fault_tests::companion_signal_error_survives_exact_main_exit_cleanup_failure",
    "supervisor::tests::tick_control_fault_tests::already_fenced_termination_error_survives_poll_failure",
)
CURRENT_LIBRARY_REQUIREMENTS = (
    *base.LIBRARY_REQUIREMENTS,
    "daemon::execution::tests::tick_projection_refresh_is_coalesced_at_the_fixed_interval",
    *CURRENT_REPAIR_LIBRARY_REQUIREMENTS,
)
CURRENT_INTEGRATION_REQUIREMENTS = {
    "restart_budget": (
        "unexpected_agent_crashes_back_off_and_stop_after_three_restarts",
    ),
    "restart_budget_recovery": (
        "restart_budget_survives_repeated_supervisord_recovery",
    ),
    "robrix_control_projection": (
        "robrix_control_v2_generated_projection_and_cross_parser_corpus",
        "writer_reproduces_the_tracked_artifact_set_byte_for_byte",
        "artifact_parity_rejects_late_byte_and_file_set_changes_with_bounded_diagnostics",
    ),
}
CURRENT_DAEMON_REQUIREMENTS = (
    *base.DAEMON_REQUIREMENTS,
    "product_binary_serves_the_complete_256_agent_roster",
)
CURRENT_KEY_REQUIREMENTS = (
    "key_tests::lifecycle_only_options_require_exact_absolute_fleet_root",
    "key_tests::pinned_bundle_options_load_verifier_without_mutating_material",
    "key_tests::legacy_six_field_verifier_tuple_is_rejected",
    "key_tests::authority_bundle_and_digest_are_an_atomic_pair",
    "key_tests::duplicate_and_unknown_flags_are_rejected",
    "key_tests::relative_fleet_root_is_rejected_before_daemon_start",
)
VALIDATOR_TEST_MODULES = (
    "scripts.test_hepta_supervisor_status",
    "scripts.test_hepta_supervisor_external_receipt",
    "scripts.test_hepta_supervisor_ci",
    "scripts.test_hepta_supervisor_ci_v3",
    "scripts.test_hepta_supervisor_workflow",
    "scripts.test_runtime_supervisor_materialize",
)
MINIMUM_VALIDATOR_TESTS = 31
CURRENT_BINDING_PATHS = (
    *base.BINDING_PATHS,
    "scripts/hepta_supervisor_ci_v3.py",
    "scripts/hepta_supervisor_status.py",
    "scripts/hepta_supervisor_external_receipt.py",
    "scripts/hepta_supervisor_artifact_gate.py",
    "scripts/test_hepta_supervisor_ci_v3.py",
    "scripts/test_hepta_supervisor_status.py",
    "scripts/test_hepta_supervisor_external_receipt.py",
    "scripts/runtime_supervisor_six_phase_materialize.py",
    "scripts/runtime_supervisor_six_phase_followup.py",
    "scripts/test_runtime_supervisor_materialize.py",
    ".github/workflows/hepta-supervisor-recovery-check.yml",
    ".github/workflows/runtime-supervisor-target-host-qualification.yml",
    "docs/modules/runtime.supervisor/CAPABILITY_STATUS.json",
    "docs/modules/runtime.supervisor/CURRENT_STATUS.md",
    "docs/modules/runtime.supervisor/HISTORICAL_DOCUMENTS.json",
    "docs/modules/runtime.supervisor/TARGET_HOST_PROFILE.json",
    "docs/modules/runtime.supervisor/PRODUCTION_QUALIFICATION_PROFILE.json",
    "docs/modules/runtime.supervisor/PRODUCTION_BOUNDARY.md",
    "docs/modules/runtime.supervisor/TARGET_HOST_DRIVER_PROTOCOL.md",
)


@dataclass(frozen=True)
class CurrentPlan:
    plans: dict[str, tuple[int, list[str]]]
    required_binary_tests: dict[str, dict[str, tuple[str, ...]]]
    required_tests: dict[str, tuple[str, ...]]
    required_python_tests: dict[str, tuple[str, ...]]
    binding_paths: tuple[str, ...]


def current_plan() -> CurrentPlan:
    serial = base.SERIAL
    test = base.TEST
    validator_tests = base.unittest_test_ids(VALIDATOR_TEST_MODULES)
    base.require(
        len(validator_tests) >= MINIMUM_VALIDATOR_TESTS,
        "reviewed validator suite lost required coverage",
    )
    plans = {
        name: (minimum, command.copy())
        for name, (minimum, command) in base.PLANS.items()
    }
    plans.update(
        {
            "status": (0, ["python3", "scripts/hepta_supervisor_status.py", "check"]),
            "validator-tests": (
                len(validator_tests),
                [
                    "python3",
                    "-m",
                    "unittest",
                    "-v",
                    *VALIDATOR_TEST_MODULES,
                ],
            ),
            "verifier-artifact": (
                0,
                ["python3", "scripts/hepta_supervisor_artifact_gate.py"],
            ),
            "default": (len(CURRENT_LIBRARY_REQUIREMENTS), [*test, "--lib", *serial]),
            "production": (
                len(CURRENT_LIBRARY_REQUIREMENTS),
                [
                    *test,
                    "--lib",
                    "--features",
                    "production-authority",
                    *serial,
                ],
            ),
            "authority-distribution": (
                4,
                [
                    *test,
                    "--features",
                    "offline-authority-tools",
                    "--test",
                    "authority_distribution",
                    *serial,
                ],
            ),
            "products": (
                19,
                [
                    *test,
                    "--features",
                    "offline-authority-tools",
                    "--bin",
                    "hepta-supervisord",
                    "--test",
                    "authority_recovery",
                    "--test",
                    "daemon_product",
                    "--test",
                    "paired_process_product",
                    "--test",
                    "writer_handoff_production",
                    *serial,
                ],
            ),
            "lint": (
                0,
                [
                    "cargo",
                    "clippy",
                    "--manifest-path",
                    "codex-rs/Cargo.toml",
                    "--locked",
                    "-p",
                    base.PACKAGE,
                    "--no-deps",
                    "--all-targets",
                    "--features",
                    "qualification,offline-authority-tools",
                    "--",
                    "-D",
                    "warnings",
                ],
            ),
        }
    )
    required_binary_tests = {
        name: {binary: tuple(tests) for binary, tests in binaries.items()}
        for name, binaries in base.REQUIRED_BINARY_TESTS.items()
    }
    required_binary_tests["default"] = {base.PACKAGE: CURRENT_LIBRARY_REQUIREMENTS}
    required_binary_tests["production"] = {base.PACKAGE: CURRENT_LIBRARY_REQUIREMENTS}
    required_binary_tests["default-products"] = {
        f"{base.PACKAGE}::bin/hepta-supervisord": CURRENT_KEY_REQUIREMENTS,
        f"{base.PACKAGE}::daemon_product": CURRENT_DAEMON_REQUIREMENTS,
        f"{base.PACKAGE}::default_authority_denied": (
            "default_library_refuses_runtime_verifier_before_opening_fleet",
            "default_daemon_refuses_pinned_bundle_before_fleet_mutation",
        ),
    }
    required_binary_tests["products"][f"{base.PACKAGE}::bin/hepta-supervisord"] = (
        CURRENT_KEY_REQUIREMENTS
    )
    required_binary_tests["qualification-lib"][base.PACKAGE] = (
        *CURRENT_LIBRARY_REQUIREMENTS,
        *base.REQUIRED_BINARY_TESTS["qualification-lib"][base.PACKAGE],
    )
    _, command = plans["qualification-lib"]
    plans["qualification-lib"] = (
        len(required_binary_tests["qualification-lib"][base.PACKAGE]),
        command,
    )
    integration_args = [
        argument
        for target in CURRENT_INTEGRATION_REQUIREMENTS
        for argument in ("--test", target)
    ]
    additional_tests = sum(
        len(tests) for tests in CURRENT_INTEGRATION_REQUIREMENTS.values()
    )
    for lane in ("default-products", "products"):
        binaries = required_binary_tests[lane]
        binaries[f"{base.PACKAGE}::daemon_product"] = CURRENT_DAEMON_REQUIREMENTS
        binaries.update(
            {
                f"{base.PACKAGE}::{target}": tests
                for target, tests in CURRENT_INTEGRATION_REQUIREMENTS.items()
            }
        )
        minimum, command = plans[lane]
        plans[lane] = (
            max(
                minimum + additional_tests,
                sum(len(tests) for tests in binaries.values()),
            ),
            [*command[: -len(serial)], *integration_args, *serial],
        )
    required_tests = {
        name: tuple(test_name for tests in binaries.values() for test_name in tests)
        for name, binaries in required_binary_tests.items()
    }
    return CurrentPlan(
        plans,
        required_binary_tests,
        required_tests,
        {"validator-tests": validator_tests},
        CURRENT_BINDING_PATHS,
    )


def apply_current_plan() -> None:
    plan = current_plan()
    base.PLANS.clear()
    base.PLANS.update(plan.plans)
    base.REQUIRED_BINARY_TESTS.clear()
    base.REQUIRED_BINARY_TESTS.update(plan.required_binary_tests)
    base.REQUIRED_TESTS.clear()
    base.REQUIRED_TESTS.update(plan.required_tests)
    base.REQUIRED_PYTHON_TESTS.clear()
    base.REQUIRED_PYTHON_TESTS.update(plan.required_python_tests)
    base.BINDING_PATHS = plan.binding_paths


def main() -> int:
    apply_current_plan()
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
