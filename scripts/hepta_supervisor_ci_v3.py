#!/usr/bin/env python3
"""Current runtime.supervisor CI plan layered on the stable receipt engine."""

from dataclasses import dataclass

if __package__:
    from . import hepta_supervisor_ci as base
else:
    import hepta_supervisor_ci as base


CURRENT_REPAIR_LIBRARY_REQUIREMENTS = (
    "directory_io::tests::fifo_swap_after_directory_observation_is_rejected_before_watchdog_release",
    "regular_file_io::tests::fifo_key_and_request_paths_are_rejected_before_watchdog_release",
    "regular_file_io::tests::read_bound_is_enforced_after_opened_file_grows",
    "matrix::binding_io_tests::fifo_swap_after_binding_metadata_is_rejected_before_watchdog_release",
    "daemon::authority_tests::effect_boundary_tests::signature_and_preflight_rejections_preserve_zero_publication_and_delivery",
    "daemon::authority_tests::effect_boundary_tests::queued_publication_failure_after_drain_is_indeterminate_and_quarantined",
    "daemon::authority_tests::effect_boundary_tests::prepared_directory_sync_failure_is_indeterminate_without_claiming_process_delivery",
    "supervisor::tests::release_retry_tests::signed_recovery::signed_explicit_rollback_source_restoration_can_recover_without_new_dispatch",
    "supervisor::tests::release_retry_tests::signed_recovery::constructor_replay::signed_prepared_release_publication_never_exposes_unsigned_authority",
    "supervisor::tests::release_retry_tests::signed_recovery::constructor_replay::legacy_unsigned_prepared_with_signed_denial_never_replays_or_dispatches",
    "supervisor::tests::release_retry_tests::signed_recovery::constructor_replay::quarantined_main_and_matrix_exit_admit_no_new_restart_claims",
    "supervisor::tests::release_retry_tests::signed_recovery::constructor_replay::exact_terminal_signed_witness_and_unsigned_history_recover_without_false_denial",
    "supervisor::tests::release_retry_tests::signed_recovery::constructor_replay::containment::signed_denial_containment_faults_retain_both_owners_and_retry_once",
    "supervisor::tests::release_retry_tests::signed_recovery::constructor_replay::preparation::signed_denial_before_idle_hydration_preserves_matrix_budget_bytes",
    "supervisor::tests::release_retry_tests::signed_recovery::constructor_replay::preparation::signed_denial_preserves_independent_matrix_binding_diagnostics_without_hydration",
    "supervisor::tests::release_retry_tests::signed_recovery::constructor_replay::preparation::ownerless_signed_denial_reports_corrupt_persisted_catalog_without_budget_normalization",
    "supervisor::tests::process_recovery_fault_does_not_hide_signed_recovery_required",
    "authority_bundle::open_tests::fifo_swap_after_regular_metadata_is_rejected_before_watchdog_release",
    "supervisor::tests::tick_control_fault_tests::pending_deadline_tests::failed_initial_drain_escalates_through_corrupt_fleet_at_original_deadlines",
    "supervisor::tests::tick_control_fault_tests::pending_deadline_tests::failed_initial_stop_escalates_through_corrupt_fleet_at_original_deadline",
    "supervisor::tests::tick_control_fault_tests::pending_deadline_tests::fresh_stop_retains_monotonic_deadline_while_matrix_defers_main_control",
    "supervisor::tests::tick_control_fault_tests::pending_deadline_tests::failed_initial_kill_retries_through_corrupt_fleet_without_signalling_stale_owner",
    "supervisor::tests::tick_control_fault_tests::matrix_fault_tests::direct_companion_kill_failure_survives_main_and_matrix_poll_failures",
    "supervisor::tests::tick_control_fault_tests::matrix_fault_tests::direct_companion_kill_failure_survives_exact_exit_lease_cleanup_failure",
    "supervisor::tests::tick_control_fault_tests::matrix_fault_tests::stored_matrix_exit_blocks_graceful_resignal_until_exact_cleanup",
    "supervisor::tests::tick_control_fault_tests::matrix_fault_tests::deferred_drain_exit_does_not_admit_automatic_restart_before_matrix_cleanup",
    "supervisor::tests::tick_control_fault_tests::deadline_tests::budget_tests::recovery_rejects_unrepresentable_drain_budget_before_driver_acquisition",
    "supervisor::tests::tick_control_fault_tests::deadline_tests::budget_tests::drain_rejects_unrepresentable_total_deadline_without_side_effects",
    "supervisor::tests::tick_control_fault_tests::deadline_tests::acknowledged_drain_deadlines_escalate_despite_persistent_poll_errors",
    "supervisor::tests::tick_control_fault_tests::deadline_tests::acknowledged_stop_deadline_kills_despite_persistent_poll_errors",
    "supervisor::tests::tick_control_fault_tests::deadline_tests::expired_drain_signal_and_poll_faults_retain_owner_and_original_budget",
    "supervisor::tests::tick_control_fault_tests::deadline_tests::expired_phase_preserves_a_stronger_pending_kill",
    "supervisor::tests::tick_control_fault_tests::deadline_tests::acknowledged_stop_escalates_before_corrupt_fleet_observation",
    "unix::control_io::tests::same_peer_complete_frame_preserves_first_newline_and_request",
    "unix::control_io::tests::successful_partial_reads_cannot_renew_the_whole_exchange_deadline",
    "unix::control_io::tests::mismatched_peer_is_rejected_before_any_request_byte",
    "unix::control_io::tests::reply_byte_bound_and_incomplete_eof_preserve_caller_validation",
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
    "matrix::tick::tests::control_order::emergency_kill_signals_main_before_matrix_and_retains_unresolved_control",
    "matrix::tick::tests::control_order::emergency_kill_keeps_main_first_when_main_signal_fails",
    "matrix::tick::tests::control_order::emergency_kill_keeps_main_first_when_matrix_signal_fails",
    "matrix::tick::tests::control_order::emergency_kill_keeps_main_first_when_registry_and_intent_preparation_fail",
    "daemon::startup_tests::losing_daemon_does_not_migrate_legacy_fleet_directories",
    "daemon::startup_tests::losing_daemon_does_not_chmod_existing_matrix_directories",
    "daemon::startup_tests::registry_open_failure_releases_startup_owner_without_serving",
    "daemon::startup_tests::startup_rejects_symlink_fleet_geometry_before_creating_an_external_lock",
    "supervisor::recovery_probe::tests::only_absent_evidence_below_a_physical_parent_skips_recovery",
    "supervisor::recovery_probe::tests::each_restart_witness_and_any_release_file_preserves_validation",
    "supervisor::recovery_probe::tests::dangling_symlink_fifo_and_symlink_parent_are_never_absence",
    "supervisor::tests::constructor_absence_recovery_tests::constructor_cancels_orphan_lineage_without_a_restart_budget",
    "supervisor::tests::constructor_absence_recovery_tests::constructor_restores_pending_budget_without_control_or_lineage",
    "supervisor::tests::constructor_absence_recovery_tests::constructor_keeps_terminal_release_transaction_in_owner_metadata",
    "supervisor::constructor_hydration::tests::initial_idle_record_survives_complete_fleet_revalidation",
    "supervisor::constructor_hydration::tests::empty_observation_does_not_read_an_unrelated_corrupt_fleet",
    "supervisor::constructor_hydration::tests::empty_release_cas_generation_change_cannot_hide_behind_absent_run_witnesses",
    "supervisor::constructor_hydration::tests::observed_idle_record_still_requires_unrelated_agent_global_validation",
    "supervisor::constructor_hydration::tests::every_new_durable_witness_forces_fresh_recovery_without_changing_the_fleet_record",
    "supervisor::constructor_hydration::tests::missing_observed_agent_forces_fresh_recovery",
    "supervisor::constructor_hydration::tests::missing_or_non_directory_run_parent_is_never_an_idle_observation",
    "supervisor::constructor_hydration::tests::symlink_parent_and_special_file_witnesses_are_never_absence",
    "supervisor::tests::constructor_hydration_recovery_tests::final_fleet_error_retains_and_fences_previously_owned_main_and_matrix",
    "supervisor::tests::constructor_hydration_recovery_tests::changed_observation_never_readopts_an_already_owned_pair",
    "supervisor::tests::constructor_hydration_recovery_tests::generation_only_release_change_runs_fresh_fallback_and_updates_snapshot",
    "supervisor::tests::constructor_hydration_recovery_tests::new_corrupt_signed_witness_runs_fresh_validation_and_denies_recovery",
    "supervisor::tests::release_retry_tests::admission::cached_catalog_start_is_readmitted_before_any_lifecycle_or_process_effect",
    "unix::peer_identity_tests::kernel_peer_identity_accepts_the_actual_socket_pair_process",
    "unix::peer_identity_tests::kernel_peer_identity_rejects_a_different_live_process_and_invalid_pid",
    "unix::peer_identity_tests::forged_agentd_health_cannot_adopt_or_signal_an_unrelated_child",
    "unix::peer_identity_tests::forged_matrix_health_cannot_adopt_or_signal_an_unrelated_child",
    "unix::peer_identity_tests::drain_never_sends_a_frame_to_a_socket_owned_by_another_process",
    "control_intent::write_tests::repeated_real_control_rename_failures_leave_no_new_staging_files",
    "control_intent::write_tests::control_publication_fault_cuts_clean_staging_and_preserve_acknowledgement_errors",
)
CURRENT_LIBRARY_REQUIREMENTS = (
    *base.LIBRARY_REQUIREMENTS,
    "daemon::execution::tests::tick_projection_refresh_is_coalesced_at_the_fixed_interval",
    *CURRENT_REPAIR_LIBRARY_REQUIREMENTS,
)
FLEET_PACKAGE = "codex-hepta-fleet"
CURRENT_FLEET_LIBRARY_REQUIREMENTS = (
    "release::copy_tests::readonly_source_is_copied_synced_and_preserved_on_duplicate_install",
    "release::publish_tests::interrupted_directory_seal_cannot_admit_or_overwrite_the_release",
    "registry::tests::workspace_sweep_agrees_with_pairwise_oracle_for_nested_and_sibling_paths",
    "regular_file::tests::registry_fifo_swap_after_metadata_is_rejected_without_watchdog_release",
    "regular_file::tests::catalog_fifo_swap_after_metadata_is_rejected_without_watchdog_release",
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
            "fleet-library": (
                len(CURRENT_FLEET_LIBRARY_REQUIREMENTS),
                [
                    "just",
                    "test",
                    "--locked",
                    "-p",
                    FLEET_PACKAGE,
                    "--lib",
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
                    "--profile",
                    "hepta-supervisor-qualification",
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
    required_binary_tests["fleet-library"] = {
        FLEET_PACKAGE: CURRENT_FLEET_LIBRARY_REQUIREMENTS
    }
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
    paired_binary = f"{base.PACKAGE}::paired_process_product"
    required_binary_tests["products"][paired_binary] = (
        *required_binary_tests["products"][paired_binary],
        "protocol_tests::paired_child_methods_and_exact_drain_use_real_protocol_validation",
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
