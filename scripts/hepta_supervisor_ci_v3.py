#!/usr/bin/env python3
"""Current runtime.supervisor CI plan layered on the stable receipt engine."""

from __future__ import annotations

from dataclasses import dataclass

if __package__:
    from . import hepta_supervisor_ci as base
else:
    import hepta_supervisor_ci as base


CURRENT_LIBRARY_REQUIREMENTS = (
    *base.LIBRARY_REQUIREMENTS,
    "daemon::execution::tests::tick_projection_refresh_is_coalesced_at_the_fixed_interval",
)
CURRENT_KEY_REQUIREMENTS = (
    "key_tests::lifecycle_only_options_require_exact_absolute_fleet_root",
    "key_tests::pinned_bundle_options_load_verifier_without_mutating_material",
    "key_tests::legacy_six_field_verifier_tuple_is_rejected",
    "key_tests::authority_bundle_and_digest_are_an_atomic_pair",
    "key_tests::duplicate_and_unknown_flags_are_rejected",
    "key_tests::relative_fleet_root_is_rejected_before_daemon_start",
)
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
    binding_paths: tuple[str, ...]


def current_plan() -> CurrentPlan:
    serial = base.SERIAL
    test = base.TEST
    plans = {
        name: (minimum, command.copy())
        for name, (minimum, command) in base.PLANS.items()
    }
    plans.update(
        {
            "status": (0, ["python3", "scripts/hepta_supervisor_status.py", "check"]),
            "validator-tests": (
                0,
                [
                    "python3",
                    "-m",
                    "unittest",
                    "-v",
                    "scripts.test_hepta_supervisor_status",
                    "scripts.test_hepta_supervisor_external_receipt",
                    "scripts.test_hepta_supervisor_ci_v3",
                    "scripts.test_hepta_supervisor_workflow",
                    "scripts.test_runtime_supervisor_materialize",
                ],
            ),
            "verifier-artifact": (
                0,
                ["python3", "scripts/hepta_supervisor_artifact_gate.py"],
            ),
            "default": (30, [*test, "--lib", *serial]),
            "production": (
                30,
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
        f"{base.PACKAGE}::daemon_product": base.DAEMON_REQUIREMENTS,
        f"{base.PACKAGE}::default_authority_denied": (
            "default_library_refuses_runtime_verifier_before_opening_fleet",
            "default_daemon_refuses_pinned_bundle_before_fleet_mutation",
        ),
    }
    required_binary_tests["products"][f"{base.PACKAGE}::bin/hepta-supervisord"] = (
        CURRENT_KEY_REQUIREMENTS
    )
    required_tests = {
        name: tuple(test_name for tests in binaries.values() for test_name in tests)
        for name, binaries in required_binary_tests.items()
    }
    return CurrentPlan(
        plans, required_binary_tests, required_tests, CURRENT_BINDING_PATHS
    )


def apply_current_plan() -> None:
    plan = current_plan()
    base.PLANS.clear()
    base.PLANS.update(plan.plans)
    base.REQUIRED_BINARY_TESTS.clear()
    base.REQUIRED_BINARY_TESTS.update(plan.required_binary_tests)
    base.REQUIRED_TESTS.clear()
    base.REQUIRED_TESTS.update(plan.required_tests)
    base.BINDING_PATHS = plan.binding_paths


def main() -> int:
    apply_current_plan()
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
