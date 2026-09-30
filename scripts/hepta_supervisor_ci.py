"""Fixed supervisor CI commands and candidate-bound execution receipts.

Reuse hepta_ci_exec; do not create another process runner or turn CI evidence
into production authority. Historical IMPLEMENTATION_MAP.sourceBase is retained.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

if __package__:
    from .hepta_supervisor_evidence import read_regular, strict_json, validate_transcript
else:
    from hepta_supervisor_evidence import read_regular, strict_json, validate_transcript

PACKAGE = "codex-hepta-supervisor"
TEST = ["just", "test", "--locked", "-p", PACKAGE]
SERIAL = [
    "--retries", "0", "--test-threads=1", "--status-level", "all",
    "--final-status-level", "none", "--success-output", "never", "--no-fail-fast",
]
PLANS = {
    "format": (0, ["cargo", "fmt", "--manifest-path", "codex-rs/Cargo.toml",
                   "--package", PACKAGE, "--", "--check"]),
    "default": (29, [*TEST, "--lib", *SERIAL]),
    "default-products": (9, [*TEST, "--no-default-features", "--bin", "hepta-supervisord",
                             "--test", "default_authority_denied",
                             "--test", "daemon_product", *SERIAL]),
    "production": (29, [*TEST, "--lib", "--features", "production-authority", *SERIAL]),
    "qualification-lib": (5, [*TEST, "--features", "qualification", "--lib", *SERIAL]),
    "hol-256": (1, [*TEST, "--features", "qualification",
                    "--test", "supervisor_hol_qualification", *SERIAL]),
    "sigkill": (1, [*TEST, "--features", "qualification",
                    "--test", "sigkill_crash_matrix", *SERIAL]),
    "authority-distribution": (4, [*TEST, "--features", "production-authority",
                                   "--test", "authority_distribution", *SERIAL]),
    "products": (19, [*TEST, "--features", "production-authority",
                       "--bin", "hepta-supervisord", "--test", "authority_recovery",
                       "--test", "daemon_product", "--test", "paired_process_product",
                       "--test", "writer_handoff_production", *SERIAL]),
    "lint-default": (0, ["cargo", "clippy", "--manifest-path", "codex-rs/Cargo.toml",
                         "--locked", "-p", PACKAGE, "--no-deps", "--lib",
                         "--bin", "hepta-supervisord", "--test", "default_authority_denied",
                         "--test", "daemon_product", "--no-default-features",
                         "--", "-D", "warnings"]),
    "lint": (0, ["cargo", "clippy", "--manifest-path", "codex-rs/Cargo.toml",
                 "--locked", "-p", PACKAGE, "--no-deps", "--all-targets",
                 "--features", "production-authority", "--", "-D", "warnings"]),
}
# Test identity includes the nextest binary ID, not just the unqualified name.
LIBRARY_REQUIREMENTS = (
    "daemon::owner::tests::contender_does_not_rewrite_or_chmod_live_owner_file",
    "daemon::owner::tests::symlink_and_hardlink_targets_are_never_truncated",
    "daemon::owner::tests::owner_release_keeps_the_same_lock_inode",
    "daemon::owner::tests::directory_is_not_a_lock_and_is_not_chmodded",
    "daemon::execution::tests::cancelled_waiter_retains_writer_and_capacity_until_blocking_work_finishes",
    "daemon::execution::tests::owner_panic_poison_cancels_daemon_and_prevents_successor_work",
    "daemon::execution::tests::cancellation_releases_ticker_wait_without_starting_more_work",
    "daemon::execution::tests::queued_request_gets_owner_capacity_before_a_later_tick",
    "daemon::read_view::tests::all_256_observations_are_addressable_and_roster_limits_remain_exact",
    "daemon::read_view::tests::expired_and_future_dated_observations_fail_closed_for_every_cached_read",
    "daemon::read_view::tests::invalidation_never_serves_the_preceding_successful_view",
    "daemon::read_view::tests::live_release_and_production_evidence_never_comes_from_observation_cache",
    "daemon::read_view::tests::recovery_required_view_is_reachable_but_not_ready",
    "daemon::shutdown_tests::shutdown_drains_accepted_connection_before_owner_can_be_replaced",
    "daemon::shutdown_tests::dropping_server_future_aborts_and_reaps_idle_connections",
    "restart_state::tests::public_recovery_preserves_matrix_attempts_without_overwriting_main_projection",
    "restart_state::tests::repeated_public_recovery_cannot_buy_a_fresh_matrix_restart_budget",
    "restart_state::tests::foreign_companion_journal_is_a_fatal_startup_error",
    "restart_state::tests::clock_rollback_is_normalized_durably_without_erasing_main_budget",
    "restart_state::tests::expired_matrix_window_is_cleared_durably",
    "restart_state::tests::staged_matrix_recovery_reapplies_backoff_once_without_touching_main_state",
    "restart_state::tests::staged_exhaustion_blocks_replacement_even_without_a_live_companion",
    "matrix::tick::tests::poll_error_retains_exact_companion_and_invalidates_stale_health",
    "matrix::tick::tests::failed_stop_is_not_an_acknowledged_phase_and_is_retried",
    "matrix::tick::tests::failed_kill_retains_stopping_phase_and_is_retried",
    "matrix::tick::tests::generation_mismatch_kill_error_does_not_drop_unfenced_owner",
    "matrix::tick::tests::exited_companion_is_retained_until_exact_durable_lease_cleanup",
    "matrix::tick::tests::deferred_stop_survives_driver_failure_until_retry_succeeds",
    "matrix::tick::tests::deferred_companion_stop_retries_the_unacknowledged_signal",
)
KEY_REQUIREMENTS = (
    "key_tests::public_key_accepts_raw_and_bounded_hex_without_rewriting_the_file",
    "key_tests::public_key_rejects_relative_path_before_filesystem_access",
    "key_tests::public_key_rejects_sparse_oversize_without_unbounded_allocation",
    "key_tests::public_key_rejects_links_and_writable_authority_material",
    "key_tests::public_key_rejects_fifo_without_waiting_for_a_writer",
    "key_tests::public_key_rejects_malformed_hex_and_wrong_lengths",
)
AUTHORITY_REQUIREMENTS = (
    "recovery_request_signs_both_explicit_outcomes_and_round_trips",
    "correctly_signed_substitutions_do_not_match_the_observed_recovery_context",
    "recovery_verification_rejects_wrong_key_expiry_and_future_issuance",
    "recomputing_the_checksum_cannot_forge_a_different_outcome",
    "recovery_json_rejects_missing_bindings_unknown_fields_and_operation_confusion",
    "recovery_signing_rejects_invalid_epochs_generations_and_time_windows",
    "real_offline_signer_binary_emits_a_verifiable_recovery_decision",
    "signer_binary_never_signs_without_explicit_acknowledgement",
    "key_file_boundary_rejects_symlinks_permissions_and_non_regular_inputs",
)
DAEMON_REQUIREMENTS = (
    "product_binary_is_single_instance_owner_only_and_bad_frames_are_isolated",
)
REQUIRED_BINARY_TESTS = {
    "default": {PACKAGE: LIBRARY_REQUIREMENTS},
    "production": {PACKAGE: LIBRARY_REQUIREMENTS},
    "default-products": {
        f"{PACKAGE}::bin/hepta-supervisord": KEY_REQUIREMENTS,
        f"{PACKAGE}::daemon_product": DAEMON_REQUIREMENTS,
        f"{PACKAGE}::default_authority_denied": (
            "default_library_refuses_runtime_verifier_before_opening_fleet",
            "default_daemon_refuses_valid_verifier_configuration_before_fleet_mutation",
        ),
    },
    "qualification-lib": {
        PACKAGE: (
            "durability_qualification_tests::disk_full_and_fsync_fail_before_signed_intent_publication",
            "durability_qualification_tests::rename_failure_preserves_predecessor_and_directory_sync_is_ambiguous_but_valid",
            "durability_qualification_tests::release_transaction_and_restart_record_never_report_success_without_durability",
            "durability_qualification_tests::lease_write_hard_link_and_directory_sync_faults_are_fail_closed",
            "durability_qualification_tests::truncated_lease_restart_intent_and_transaction_are_rejected",
        ),
    },
    "hol-256": {
        f"{PACKAGE}::supervisor_hol_qualification": (
            "qualifies_256_instances_fault_waves_and_owner_lock_hol",
        ),
    },
    "sigkill": {
        f"{PACKAGE}::sigkill_crash_matrix": (
            "actual_sigkill_preserves_lease_restart_intent_and_transaction",
        ),
    },
    "authority-distribution": {
        f"{PACKAGE}::authority_distribution": (
            "pinned_bundle_rotation_rejects_predecessor_and_accepts_current_signer",
            "wrong_signer_stale_grant_and_authority_epoch_rollover_fail_closed",
            "fleet_revocation_is_observed_from_the_current_policy_owner",
            "product_caller_rejects_wrong_authority_bundle_pin",
        ),
    },
    "products": {
        f"{PACKAGE}::bin/hepta-supervisord": KEY_REQUIREMENTS,
        f"{PACKAGE}::authority_recovery": AUTHORITY_REQUIREMENTS,
        f"{PACKAGE}::daemon_product": DAEMON_REQUIREMENTS,
        f"{PACKAGE}::paired_process_product": (
            "two_real_pairs_restart_one_without_peer_pid_churn",
            "five_real_pairs_adopt_all_ten_children_and_isolate_one_matrix_crash",
        ),
        f"{PACKAGE}::writer_handoff_production": (
            "recovered_handoff_physically_fences_old_writer_before_successor_admission",
        ),
    },
}
# Compatibility inventory for consumers; qualification uses the bound pairs above.
REQUIRED_TESTS = {
    name: tuple(test for tests in binaries.values() for test in tests)
    for name, binaries in REQUIRED_BINARY_TESTS.items()
}
CONTEXT_FIELDS = (
    "source_sha", "base_sha", "tested_sha", "lane", "run_id", "run_attempt",
)
CONTEXT_ENV = (
    "SOURCE_SHA", "BASE_SHA", "TESTED_SHA", "HEPTA_CI_LANE",
    "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT",
)
BINDING_PATHS = (
    "codex-rs", "docs/modules/runtime.supervisor", "scripts/hepta_ci_exec.py",
    "scripts/hepta_supervisor_ci.py", "scripts/hepta_supervisor_evidence.py",
    "scripts/test_hepta_supervisor_ci.py", "scripts/test_hepta_supervisor_evidence.py",
    "scripts/test_hepta_supervisor_workflow.py",
    "scripts/hepta_agentd_product_prerequisite.py", "justfile", ".github/actions",
    ".github/workflows/hepta-supervisor-qualification.yml",
    ".github/workflows/blocking-ci.yml", ".github/workflows/hepta-architecture-convergence.yml",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_record(
    name: str, data: dict, context: dict, git_identity: dict, log: bytes,
    count_tests: Callable[[str], tuple[int, int]],
) -> dict:
    minimum, command = PLANS[name]
    require(type(data.get("schema_version")) is int and data["schema_version"] == 1,
            "record schema")
    require(data.get("status") == "passed", f"{name}: not passed")
    for field in ("returncode", "command_exit_code", "exit_code", "observed_failed_tests"):
        require(type(data.get(field)) is int and data[field] == 0, f"{name}: {field}")
    for field in ("timed_out", "output_limit_exceeded"):
        require(data.get(field) is False, f"{name}: {field}")
    for field in CONTEXT_FIELDS:
        require(data.get(field) == context[field], f"{name}: context {field}")
    require(data.get("command") == command, f"{name}: unreviewed command")
    require(type(data.get("minimum_tests")) is int and data["minimum_tests"] == minimum,
            f"{name}: minimum tests")
    for phase in ("before", "after"):
        snapshot = data.get(phase)
        require(type(snapshot) is dict and snapshot.get("dirty") is False,
                f"{name}: {phase} must have an explicit clean Git identity")
    require(data.get("before") == git_identity and data.get("after") == git_identity,
            f"{name}: Git identity changed")
    require(git_identity.get("dirty") is False, f"{name}: dirty checkout")
    require(type(data.get("log_bytes")) is int and data["log_bytes"] == len(log),
            f"{name}: log length")
    require(data.get("log_sha256") == hashlib.sha256(log).hexdigest(), f"{name}: log digest")
    passed, failed = count_tests(log.decode("utf-8", errors="strict"))
    require(type(data.get("observed_passed_tests")) is int
            and data["observed_passed_tests"] == passed, f"{name}: test count differs from log")
    require(passed >= minimum and failed == 0, f"{name}: missing or failed tests")
    if name in REQUIRED_BINARY_TESTS:
        return validate_transcript(log, REQUIRED_BINARY_TESTS[name], passed)
    require(passed == 0, f"{name}: unexpected test transcript in non-test plan")
    return {"passed_tests": 0, "skipped_tests": 0, "required_tests": 0}


def context_from_env() -> dict:
    context = {field: os.environ.get(env, "")
               for field, env in zip(CONTEXT_FIELDS, CONTEXT_ENV, strict=True)}
    for field in ("source_sha", "base_sha", "tested_sha"):
        require(re.fullmatch(r"[0-9a-f]{40}", context[field]) is not None, f"invalid {field}")
        require(context[field] != "0" * 40, f"null {field}")
    require(context["lane"] in ("source-head", "base-merge"), "invalid lane")
    for field in ("run_id", "run_attempt"):
        require(re.fullmatch(r"[1-9][0-9]*", context[field]) is not None, f"invalid {field}")
    return context


def assemble(records: Path, output: Path) -> None:
    if __package__:
        from .hepta_ci_exec import identity, observed_test_counts
    else:
        from hepta_ci_exec import identity, observed_test_counts
    context = context_from_env()
    git_identity = identity()
    require(git_identity["commit"] == context["tested_sha"] and git_identity["dirty"] is False,
            "not the clean tested candidate")
    root = Path(subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"], text=True,
    ).strip()).resolve()
    require(Path.cwd().resolve() == root, "run qualification from repository root")
    require(output.is_absolute() and not output.resolve().is_relative_to(root),
            "receipt must be outside checkout")
    require(records.is_absolute() and not records.resolve().is_relative_to(root),
            "records must be outside checkout")
    if context["lane"] == "source-head":
        require(context["source_sha"] == context["tested_sha"], "wrong source head")
    else:
        require(git_identity["parents"] == [context["base_sha"], context["source_sha"]],
                "wrong merge parents")
        expected_tree = subprocess.check_output(
            ["git", "merge-tree", "--write-tree", context["base_sha"], context["source_sha"]],
            text=True,
        ).strip()
        require(git_identity["tree"] == expected_tree, "wrong merge tree")
    require({p.name for p in records.glob("*.json")} == {f"{name}.json" for name in PLANS},
            "missing or unexpected suite records")
    evidence = {}
    for name in PLANS:
        raw = read_regular(records / f"{name}.json", 256 * 1024)
        data = strict_json(raw)
        require(isinstance(data, dict), f"{name}: record must be an object")
        require(data.get("working_directory") == str(root), f"{name}: wrong working directory")
        filename = data.get("log_file", "")
        require(isinstance(filename, str) and re.fullmatch(
            re.escape(name) + r"\.json\.[0-9a-f]{32}\.log", filename,
        ) is not None, f"{name}: invalid log filename")
        log = read_regular(records / filename, 64 * 1024 * 1024)
        tests = validate_record(name, data, context, git_identity, log, observed_test_counts)
        evidence[name] = {
            "record_sha256": hashlib.sha256(raw).hexdigest(), "log_sha256": data["log_sha256"],
            "command": data["command"], **tests,
        }
    entries = subprocess.check_output(
        ["git", "ls-tree", "-r", "-z", "HEAD", "--", *BINDING_PATHS],
    ).split(b"\0")
    bindings = {}
    for entry in entries:
        if entry:
            metadata, path = entry.decode().split("\t", 1)
            mode, kind, blob = metadata.split()
            require(kind == "blob", "source binding is not a blob")
            bindings[path] = {"mode": mode, "git_blob_sha": blob}
    map_path = Path("docs/modules/runtime.supervisor/IMPLEMENTATION_MAP.json")
    implementation_map = strict_json(read_regular(map_path, 1024 * 1024))
    require(identity() == git_identity, "source changed during receipt assembly")
    receipt = {
        "schema_version": 2, "module": "runtime.supervisor",
        "qualification_scope": "fixed-supervisor-ci-plan-v2", **context, "git": git_identity,
        "runner_os": os.environ.get("RUNNER_OS"), "runner_arch": os.environ.get("RUNNER_ARCH"),
        "implementation_source_base": implementation_map.get("sourceBase"),
        "source_bindings": bindings, "execution_records": evidence,
        "scoped_execution_complete": True, "deployment_qualification_complete": False,
        "independent_acceptance_complete": False, "production_activation": False, "release": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    # A complete receipt is acknowledged only after directory publication is durable.
    fd = os.open(output.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    execute = sub.add_parser("execute")
    execute.add_argument("name", choices=PLANS)
    execute.add_argument("--records", type=Path, required=True)
    collect = sub.add_parser("assemble")
    collect.add_argument("--records", type=Path, required=True)
    collect.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.operation == "execute":
            minimum, command = PLANS[args.name]
            result = subprocess.run(
                [sys.executable, "scripts/hepta_ci_exec.py", "--output",
                 str(args.records / f"{args.name}.json"), "--minimum-tests", str(minimum),
                 "--timeout-seconds", "3600", "--", *command], check=False,
            )
            return result.returncode if result.returncode >= 0 else 128 - result.returncode
        assemble(args.records, args.output)
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"Supervisor receipt rejected: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
