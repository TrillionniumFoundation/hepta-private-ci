#!/usr/bin/env python3
"""Read-only dual-lane execution over a previously bound Git candidate.

The receipt binds source/base/tested commit and tree identities, the workflow and
runner identity, the complete command/log record, the pinned toolchain, and a
canonical digest of every evidence payload file produced before the signed
receipt. The source checkout is revalidated before and after every command.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys
from typing import Any

import context_compiler_candidate as candidate
import context_compiler_named_evidence as named_evidence

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def observed_tests(log: str | Iterable[str], *, runner: str) -> int:
    """Count expected-runner summaries, excluding nested libtest output in nextest."""
    lines = (
        ANSI.sub("", line).rstrip("\r\n")
        for line in (log.splitlines() if isinstance(log, str) else log)
    )
    if runner == "nextest":
        summaries = []
        for line in lines:
            if re.match(r"^\s*Summary\b", line):
                summaries.append(line)
                if len(summaries) > 1:
                    raise ValueError("ambiguous nextest summary")
        if len(summaries) != 1:
            raise ValueError("expected exactly one nextest summary")
        match = re.fullmatch(
            r"\s*Summary\s+\[[^\]\r\n]+\]\s+(?P<run>\d+) tests? run: "
            r"(?P<passed>\d+) passed"
            r"(?: \(\d+ (?:flaky|slow|leaky)(?:, \d+ (?:flaky|slow|leaky))*\))?"
            r"(?:, (?P<failed>\d+) failed(?: \(\d+ (?:slow|due to being leaky)(?:, \d+ (?:slow|due to being leaky))*\))?)?"
            r"(?:, (?P<timed_out>\d+) timed out)?"
            r"(?:, \d+ skipped)?\s*",
            summaries[0],
        )
        if match is None:
            raise ValueError("malformed nextest summary")
        if sum(
            int(match.group(key) or 0) for key in ("passed", "failed", "timed_out")
        ) != int(match.group("run")):
            raise ValueError("inconsistent nextest totals")
        return int(match.group("passed"))
    if runner != "libtest":
        raise ValueError("unknown test runner")
    total = 0
    found = False
    for line in lines:
        if not line.startswith("test result:"):
            continue
        found = True
        match = re.fullmatch(
            r"test result: (?:ok|FAILED)\. (?P<passed>\d+) passed; "
            r"\d+ failed; \d+ ignored; \d+ measured; \d+ filtered out; "
            r"finished in \d+(?:\.\d+)?s\s*",
            line,
        )
        if match is None:
            raise ValueError("malformed libtest summary")
        total += int(match.group("passed"))
    if not found:
        raise ValueError("missing libtest summary")
    return total


def bind_test_count(log: str | Iterable[str], spec: dict, result: dict) -> None:
    """Fail closed on absent/ambiguous runner evidence and preserve command failure."""
    result.update(
        {"minimumTests": spec["minimumTests"], "testRunner": spec["testRunner"]}
    )
    try:
        count = observed_tests(log, runner=spec["testRunner"])
    except (OSError, ValueError, UnicodeError):
        result.update(
            {"testsObserved": 0, "testCountEvidenceFailure": True, "succeeded": False}
        )
        return
    result["testsObserved"] = count
    result["succeeded"] = result["succeeded"] and count >= spec["minimumTests"]


def specs(legacy):
    commands = []
    for original in legacy.command_specs():
        spec = dict(original)
        spec["argv"] = list(original["argv"])
        if spec["argv"][:2] == ["cargo", "test"]:
            spec["argv"][:2] = ["just", "test"]
            spec["minimumTests"] = 1
        commands.append(spec)

    stream_regression_names = [
        "client::provider_policy_tests::completed_is_hidden_until_exact_terminal_is_acknowledged",
        "client::provider_policy_tests::terminal_failure_suppresses_completed_and_last_response",
        "client::provider_policy_tests::consumer_drop_records_partial_indeterminate_terminal",
        "client::provider_policy_tests::unauthorized_stream_error_records_rejected_before_downstream_error",
        "client::provider_policy_tests::eof_records_partial_indeterminate_terminal",
        "client::provider_policy_tests::terminal_acknowledgement_wait_is_not_consumer_timeout_driven",
        "client::tests::dropped_response_stream_traces_cancelled_partial_output",
        "client::tests::response_stream_records_last_model_feedback_ids",
        "client::tests::ephemeral_unauthorized_and_stream_errors_are_redacted",
        "client::tests::dropped_backpressured_response_stream_traces_cancelled_partial_output",
    ]

    # These selectors exercise the actual provider-body slots, not only the
    # context compiler crate in isolation.
    commands[2:2] = [
        {
            "name": "core-compaction-admission-diagnostic",
            "cwd": legacy.CODEX_RS,
            "argv": [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-core",
                "--lib",
                "session::tests::compaction_admission_tests::compact_after_turn_complete_rejects_while_terminalization_pending",
            ],
            "minimumTests": 1,
            "requiredNativeTests": [
                "session::tests::compaction_admission_tests::compact_after_turn_complete_rejects_while_terminalization_pending",
            ],
        },
        {
            "name": "core-response-stream-regressions",
            "cwd": legacy.CODEX_RS,
            "argv": [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-core",
                "--lib",
                "-E",
                " | ".join(f"test({name})" for name in stream_regression_names),
            ],
            "minimumTests": len(stream_regression_names),
            "requiredNativeTests": stream_regression_names,
        },
        {
            "name": "core-websocket-connection-identity-regression",
            "cwd": legacy.CODEX_RS,
            "argv": [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-core",
                "--lib",
                "client::tests::websocket_connection_identity_binds_provider_and_stable_handshake_semantics",
            ],
            "minimumTests": 1,
            "requiredNativeTests": [
                "client::tests::websocket_connection_identity_binds_provider_and_stable_handshake_semantics",
            ],
        },
        {
            "name": "agent-protocol-effect-wire-regression",
            "cwd": legacy.CODEX_RS,
            "argv": [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-agent-protocol",
                "--lib",
                "tests::automation_effect_wire_round_trip_is_strict_and_bounded",
            ],
            "minimumTests": 1,
            "requiredNativeTests": [
                "tests::automation_effect_wire_round_trip_is_strict_and_bounded",
            ],
        },
        {
            "name": "typed-slot-regressions",
            "cwd": legacy.CODEX_RS,
            "argv": [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-api",
                "--lib",
                "context_slot",
            ],
            "minimumTests": 11,
        },
        {
            "name": "exact-body-regressions",
            "cwd": legacy.CODEX_RS,
            "argv": [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-prompt-extension",
                "--lib",
                "exact_body",
            ],
            "minimumTests": 8,
        },
        {
            "name": "v3-product-regressions",
            "cwd": legacy.CODEX_RS,
            "argv": [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-intelligence",
                "prompt_product_v3",
            ],
            "minimumTests": 4,
        },
        {
            "name": "crash-recovery-regressions",
            "cwd": legacy.CODEX_RS,
            "argv": [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-agentd",
                "registry_race_tests",
            ],
            "minimumTests": 6,
            "requiredNativeTests": [
                "exact_context_delivery::registry_race_tests::registry_revocation_during_tokenization_refuses_the_real_owner_send_gate",
                "exact_context_delivery::registry_race_tests::expiry_during_tokenization_refuses_the_real_owner_send_gate",
                "exact_context_delivery::registry_race_tests::concurrent_preparation_cannot_reserve_two_attempts_for_one_turn",
                "exact_context_delivery::registry_race_tests::crash_reopen_reconciles_indeterminate_then_final_without_redispatch",
                "exact_context_delivery::registry_race_tests::legacy_digest_only_pre_send_remains_non_recoverable",
                "exact_context_delivery::registry_race_tests::durable_recovery_rejects_outer_identity_drift_from_archived_proof",
            ],
        },
        {
            "name": "v3-default-product-profile",
            "cwd": legacy.CODEX_RS,
            "argv": [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-prompt-registry",
                "-p",
                "codex-hepta-context-compiler",
                "-p",
                "codex-hepta-intelligence",
                "-p",
                "codex-hepta-agentd",
            ],
            "minimumTests": 5,
            "requiredNativeTests": [
                "v2::tests::recovery_archives_reject_oversized_valid_json_before_decoding",
                "wire::tests::context_wire_rejects_impossible_token_accounting_on_encode_and_decode",
                "provider_closure::tests::maximum_repeated_payload_is_rejected_without_retaining_match_offsets",
                "provider_closure::tests::repeated_prefix_search_preserves_the_unique_complete_payload",
                "provider_closure::tests::arbitrary_byte_matching_preserves_missing_unique_and_overlapping_cases",
            ],
        },
        {
            "name": "legacy-intelligence-profile",
            "cwd": legacy.CODEX_RS,
            "argv": [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-intelligence",
                "--features",
                "legacy-prompt-context-v1",
            ],
            "minimumTests": 1,
        },
        {
            "name": "legacy-agentd-profile",
            "cwd": legacy.CODEX_RS,
            "argv": [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-agentd",
                "--features",
                "legacy-prompt-context-v1",
            ],
            "minimumTests": 1,
        },
    ]

    commands[2:2] = [
        {
            "name": "owner-lifecycle-regressions",
            "cwd": legacy.CODEX_RS,
            "argv": [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-agentd",
                "lifecycle_tests",
                "--status-level",
                "pass",
                "--success-output",
                "immediate",
            ],
            "minimumTests": 10,
            "requiredNativeTests": [
                "exact_context_delivery::registry_race_tests::lifecycle_tests::sequential_completed_turns_release_more_than_256_stages",
                "exact_context_delivery::registry_race_tests::lifecycle_tests::runtime_stage_failure_does_not_publish_an_exact_stage",
                "exact_context_delivery::registry_race_tests::lifecycle_tests::runtime_capacity_failure_does_not_consume_exact_capacity",
                "exact_context_delivery::registry_race_tests::lifecycle_tests::uncertain_runtime_publication_leaves_no_exact_authorization",
                "exact_context_delivery::registry_race_tests::lifecycle_tests::preparation_reservation_blocks_clear_without_calling_runtime",
                "exact_context_delivery::registry_race_tests::lifecycle_tests::tool_continuation_and_unknown_terminal_keep_the_stage",
                "prompt_runtime::lifecycle_tests::explicit_retirement_survives_reopen_without_raw_context",
                "prompt_runtime::lifecycle_tests::unresolved_attempt_cannot_be_retired",
                "prompt_runtime::lifecycle_tests::schema_one_cannot_smuggle_retirement_and_schema_two_rejects_orphans",
                "prompt_runtime::lifecycle_tests::new_staging_cannot_spend_an_admitted_attempts_completion_reserve",
            ],
            "requireFixtureProfile": True,
        },
        {
            "name": "owner-metrics-regressions",
            "cwd": legacy.CODEX_RS,
            "argv": [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-agentd",
                "exact_context_delivery::metrics::tests",
                "--status-level",
                "pass",
                "--success-output",
                "immediate",
            ],
            "minimumTests": 4,
            "requiredNativeTests": [
                "exact_context_delivery::metrics::tests::window_is_bounded_and_percentiles_are_nearest_rank",
                "exact_context_delivery::metrics::tests::an_unobserved_phase_is_not_a_zero_latency_claim",
                "exact_context_delivery::metrics::tests::leaving_a_failed_phase_still_records_attempted_time",
                "exact_context_delivery::metrics::tests::diagnostics_do_not_hold_a_lock_across_measured_work",
            ],
        },
        {
            "name": "owner-capacity-regressions",
            "cwd": legacy.CODEX_RS,
            "argv": [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-agentd",
                "exact_context_delivery::capacity_tests",
                "--status-level",
                "pass",
                "--success-output",
                "immediate",
            ],
            "minimumTests": 3,
            "requiredNativeTests": [
                "exact_context_delivery::capacity_tests::unknown_observations_cannot_release_the_final_reservation",
                "exact_context_delivery::capacity_tests::reserve_exhaustion_rejects_before_writing_and_does_not_poison",
                "exact_context_delivery::capacity_tests::oversized_terminal_cannot_exceed_its_reserved_record_bound",
            ],
        },
        {
            "name": "owner-storage-regressions",
            "cwd": legacy.CODEX_RS,
            "argv": [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-agentd",
                "exact_context_delivery::storage_hardening_tests",
                "--status-level",
                "pass",
            ],
            "minimumTests": 6,
            "requiredNativeTests": [
                "exact_context_delivery::storage_hardening_tests::second_writer_is_rejected_by_the_existing_owner_lock",
                "exact_context_delivery::storage_hardening_tests::state_and_next_symlinks_fail_closed_without_poisoning_unrelated_capacity",
                "exact_context_delivery::storage_hardening_tests::permissive_or_hard_linked_state_files_are_rejected",
                "exact_context_delivery::storage_hardening_tests::root_replacement_fences_the_owner_even_after_path_restoration",
                "exact_context_delivery::storage_hardening_tests::lock_links_and_symlink_ancestors_cannot_redirect_the_owner",
                "exact_context_delivery::storage_hardening_tests::replacing_the_lock_fences_the_pinned_owner",
            ],
        },
        {
            "name": "owner-diagnostic-regressions",
            "cwd": legacy.CODEX_RS,
            "argv": [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-agentd",
                "prompt_runtime::errors::tests",
                "--status-level",
                "pass",
            ],
            "minimumTests": 2,
            "requiredNativeTests": [
                "prompt_runtime::errors::tests::pipeline_diagnostics_redact_dynamic_owner_and_adapter_details",
                "prompt_runtime::errors::tests::public_exact_diagnostic_preserves_recovery_action_without_exposing_internal_error",
            ],
        },
        {
            "name": "named-evidence-parser-regressions",
            "cwd": legacy.ROOT,
            "argv": [
                "python3",
                "-B",
                "-m",
                "unittest",
                "discover",
                "-s",
                "scripts",
                "-p",
                "test_context_compiler_named_evidence.py",
                "-v",
            ],
        },
        {
            "name": "qualification-recorder-regressions",
            "cwd": legacy.ROOT,
            "argv": [
                "python3",
                "-B",
                "-m",
                "unittest",
                "discover",
                "-s",
                "scripts",
                "-p",
                "test_context_compiler_execution*.py",
                "-v",
            ],
        },
    ]
    for spec in commands:
        if spec.get("minimumTests") is not None:
            # The repository's `just test` recipe invokes cargo nextest run.
            # Bind this from the command, not from possibly truncated stdout.
            if spec["argv"][:2] != ["just", "test"]:
                raise ValueError("test count requires an explicit runner contract")
            spec["testRunner"] = "nextest"
    return commands


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def evidence_payload(output: Path, receipt_path: Path) -> dict[str, Any]:
    """Return a canonical manifest/digest without creating a self-reference."""
    files: list[dict[str, Any]] = []
    for path in sorted(output.rglob("*")):
        if not path.is_file() or path == receipt_path or path.name.endswith(".tmp"):
            continue
        relative = path.relative_to(output).as_posix()
        files.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "schema": "hepta.context-compiler-evidence-payload.v1",
        "files": files,
        "canonicalSha256": hashlib.sha256(canonical).hexdigest(),
    }


def environment_identity() -> dict[str, Any]:
    keys = (
        "GITHUB_REPOSITORY",
        "GITHUB_WORKFLOW",
        "GITHUB_WORKFLOW_REF",
        "GITHUB_WORKFLOW_SHA",
        "GITHUB_RUN_ID",
        "GITHUB_RUN_ATTEMPT",
        "CARGO_PROFILE_DEV_DEBUG",
        "CARGO_INCREMENTAL",
        "CARGO_BUILD_JOBS",
        "GITHUB_JOB",
        "GITHUB_EVENT_NAME",
        "GITHUB_REF",
        "GITHUB_SHA",
        "GITHUB_ACTOR_ID",
        "RUNNER_NAME",
        "RUNNER_OS",
        "RUNNER_ARCH",
        "RUNNER_ENVIRONMENT",
        "QUALIFICATION_WORKFLOW_REF",
        "QUALIFICATION_WORKFLOW_SHA",
        "QUALIFICATION_RUN_ID",
        "QUALIFICATION_RUN_ATTEMPT",
        "QUALIFICATION_RUNNER_IMAGE",
        "QUALIFICATION_RUNNER_OS",
        "QUALIFICATION_RUNNER_ARCH",
    )
    return {
        "environment": {key: os.environ.get(key) for key in keys},
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
    }


def main() -> int:
    import context_compiler_qualification as legacy

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-record", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    root = legacy.ROOT.resolve()
    output = args.output_dir.resolve()
    if output == root or root in output.parents:
        parser.error("execution evidence must be outside the checkout")
    output.mkdir(parents=True, exist_ok=True)

    record_document = json.loads(args.candidate_record.read_text(encoding="utf-8"))
    digest = record_document.pop("recordSha256", None)
    expected = hashlib.sha256(
        json.dumps(record_document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if digest != expected:
        parser.error("candidate record digest mismatch")

    source_tree = candidate.git(
        root, "rev-parse", f"{record_document['sourceHeadSha']}^{{tree}}"
    )
    base_tree = candidate.git(
        root, "rev-parse", f"{record_document['baseSha']}^{{tree}}"
    )
    immutable_identity = {
        "sourceCommit": record_document["sourceHeadSha"],
        "sourceTree": source_tree,
        "baseCommit": record_document["baseSha"],
        "baseTree": base_tree,
        "testedCommit": record_document["testedHeadSha"],
        "testedTree": record_document["testedTreeSha"],
        "orderedParents": record_document["parents"],
        "lane": record_document["lane"],
    }

    receipt = {
        "schema": "hepta.context-compiler-dual-lane-execution.v2",
        "candidate": record_document,
        "immutableIdentity": immutable_identity,
        "executionEnvironment": environment_identity(),
        "status": "running",
        "commands": [],
        "independentAcceptance": False,
        "activation": False,
        "release": False,
    }
    receipt_path = output / "context-compiler-qualification-receipt.json"
    failure = None
    failure_context = None
    phase = "verify_initial_candidate"
    active_command = None
    command_specs = specs(legacy)
    try:
        candidate.verify(root, record_document)
        phase = "write_initial_receipt"
        legacy.write_receipt(receipt_path, receipt)
        for index, spec in enumerate(command_specs, start=1):
            active_command = spec["name"]
            phase = "verify_before_command"
            candidate.verify(root, record_document)
            log = output / "logs" / f"{index:02d}-{spec['name']}.log"
            phase = "execute_command"
            result = legacy.run_command(spec, log)
            phase = "bind_command_evidence"
            minimum = spec.get("minimumTests")
            if minimum is not None:
                # Stream the whole bounded-line log so an earlier summary cannot
                # disappear outside a tail window and make ambiguity look valid.
                bind_test_count(named_evidence.bounded_lines(log), spec, result)
            if spec.get("requiredNativeTests"):
                try:
                    named = named_evidence.bind_named_tests(
                        log, spec["requiredNativeTests"]
                    )
                    result.update(named)
                    result["succeeded"] = (
                        result["succeeded"] and named["namedNativeTestsPassed"]
                    )
                    if spec.get("requireFixtureProfile"):
                        profile = named_evidence.fixture_profile(log)
                        result["ownerFixtureProfile"] = profile
                        result["succeeded"] = (
                            result["succeeded"] and profile is not None
                        )
                except (OSError, ValueError, TypeError, UnicodeError) as error:
                    result["namedEvidenceFailure"] = type(error).__name__
                    result["succeeded"] = False
            receipt["commands"].append(result)
            phase = "verify_after_command"
            candidate.verify(root, record_document)
            phase = "write_partial_receipt"
            receipt.pop("receiptSha256", None)
            legacy.write_receipt(receipt_path, receipt)
        active_command = None
        phase = "verify_final_candidate"
        candidate.verify(root, record_document)
    except (Exception, KeyboardInterrupt) as error:
        failure = type(error).__name__
        # Only stable source-defined reasons are exported. Exception text may
        # contain subprocess output or paths and is not receipt-safe evidence.
        reason = "qualification_interrupted"
        if phase.startswith("verify_"):
            reason = {
                "candidate worktree is not clean": "candidate_worktree_dirty",
                "tested commit changed": "candidate_commit_changed",
                "tested tree changed": "candidate_tree_changed",
                "candidate parent identity changed": "candidate_parents_changed",
            }.get(str(error), "candidate_verification_rejected")
        failure_context = {
            "phase": phase,
            "command": active_command,
            "reasonCode": reason,
        }

    receipt.pop("receiptSha256", None)
    receipt["failureClass"] = failure
    receipt["failureContext"] = failure_context
    receipt["status"] = (
        "passed"
        if (
            failure is None
            and len(receipt["commands"]) == len(command_specs)
            and all(
                item["succeeded"] or not item["required"]
                for item in receipt["commands"]
            )
        )
        else "failed"
    )
    state = json.loads(legacy.MANIFEST.read_text(encoding="utf-8"))
    receipt["consumerExecution"] = named_evidence.consumer_projection(
        state.get("consumerExecution", []), receipt["commands"], immutable_identity
    )
    receipt["toolchain"] = {
        name: legacy.tool_version(argv)
        for name, argv in {
            "git": ["git", "--version"],
            "python": [sys.executable, "--version"],
            "rustc": ["rustc", "-Vv"],
            "cargo": ["cargo", "--version"],
            "just": ["just", "--version"],
            "nextest": ["cargo", "nextest", "--version"],
            "cargoDeny": ["cargo", "deny", "--version"],
            "bazel": ["bazel", "--version"],
        }.items()
    }
    receipt["createdAt"] = legacy.utc_now()
    receipt["manifestCanonicalSha256"] = legacy.canonical_manifest_sha256()
    # Hash every command log, the candidate record, and any partial evidence
    # before serializing the final signed receipt. The outer Actions artifact
    # additionally retains a full-file manifest including this receipt.
    receipt["evidencePayload"] = evidence_payload(output, receipt_path)
    legacy.write_receipt(receipt_path, receipt)
    print(f"qualification {receipt['status']}: {receipt_path}")
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
