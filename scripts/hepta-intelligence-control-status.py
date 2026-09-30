#!/usr/bin/env python3
"""Validate reviewed intelligence mappings and emit exact execution projections.

Tracked JSON is a source/test contract, not a cache of branch or CI status.
Symbol presence proves only source presence. A passing projection additionally
requires every named real command record, its unchanged log, exact checkout
identity, and observed passes for the explicitly mapped tests. Product E2E,
independent acceptance and deployment are never inferred from package tests.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs/modules/intelligence.control"
NAMES = ("IMPLEMENTATION_MAP.json", "TEST_TRACEABILITY.json")
PLACEHOLDER = "CI_EXACT_HEAD"
REQUIRED_TESTS = {
    "raw_candidate_order_does_not_change_canonical_identity",
    "malicious_selected_candidate_outside_legal_set_is_rejected",
    "zero_propensity_selection_is_rejected",
    "running_generation_differs_from_spawn_and_is_admitted",
    "forged_generation_or_fence_is_rejected_before_mutation",
    "worker_timeout_is_visible_while_active_and_after_late_completion",
    "stage_failure_classes_remain_separate",
    "run_phase_dwell_accumulates_exact_transitions",
    "same_phase_idempotent_replay_does_not_reset_dwell",
    "operation_ids_are_kind_separated_and_stable",
    "evidence_payload_rejects_role_substitution",
    "persisted_evidence_binding_rejects_signed_identity_substitution",
    "persisted_principal_binding_rejects_key_and_credential_substitution",
    "exact_destination_observation_binds_controller_identity",
    "learning_runtime_policy_is_bounded",
    "final_gate_rehashes_every_envelope_dependency",
    "final_gate_rejects_positive_propensity_substitution",
    "membership_gate_rejects_mutated_legal_support",
    "replay_verification_uses_current_time_not_frozen_event_time",
    "learning_clock_rollback_is_not_normalized_into_old_time",
    "recovery_and_dispatch_each_receive_a_bounded_share",
    "single_slot_alternates_instead_of_starving_new_work",
    "unsettled_cursor_visits_poison_prefix_and_later_scopes",
    "unused_claim_deferral_preserves_identity_and_fences_old_claim",
    "post_dispatch_claim_cannot_be_deferred_for_reexecution",
    "independent_watchdog_observes_detached_work",
    "explicit_hard_timeout_terminates_a_real_child_process",
    "actual_stage_outputs_fill_templates_but_reject_substitution",
    "utility_universe_rejects_foreign_and_missing_candidates",
    "guard_rejects_rollback_and_same_epoch_drift_and_survives_reopen",
}
REQUIRED_OPERATIONS = {
    "build_legal_candidates",
    "prepare_intelligence_run",
    "decide_boundary",
    "assemble_context",
    "validate_current_snapshot",
    "validate_canonical_outcome_v1",
    "AgentdIntelligenceRunIdentityV1::from_run_start",
    "AgentRunCoordinator::start_bound_run",
    "append_intelligence_decision_v1",
    "append_intelligence_outcome_v1",
    "AgentdIntelligenceLearningHostV1::reconcile_unsettled",
}
COMMANDS = {
    "fmt.json": ["cargo", "fmt", "--all", "--", "--check"],
    "intelligence-tests.json": [
        "cargo",
        "test",
        "--locked",
        "-p",
        "codex-hepta-intelligence",
    ],
    "ledger-tests.json": [
        "cargo",
        "test",
        "--locked",
        "-p",
        "codex-hepta-learning-ledger",
    ],
    "native-tests.json": [
        "cargo",
        "test",
        "--locked",
        "-p",
        "codex-hepta-infer-worker-host",
        "--lib",
    ],
    "operations-tests.json": [
        "cargo",
        "test",
        "--locked",
        "-p",
        "codex-hepta-operations",
    ],
    "agentd-default-tests.json": [
        "cargo",
        "test",
        "--locked",
        "-p",
        "codex-hepta-agentd",
        "--lib",
    ],
    "agentd-qualification-tests.json": [
        "cargo",
        "test",
        "--locked",
        "-p",
        "codex-hepta-agentd",
        "--lib",
        "--features",
        "qualification-legacy-learning-write",
    ],
    "agentd-all-targets.json": [
        "cargo",
        "check",
        "--locked",
        "-p",
        "codex-hepta-agentd",
        "--all-targets",
    ],
    "clippy.json": [
        "cargo",
        "clippy",
        "--locked",
        "-p",
        "codex-hepta-intelligence",
        "-p",
        "codex-hepta-agentd",
        "-p",
        "codex-hepta-operations",
        "--all-targets",
        "--",
        "-D",
        "warnings",
    ],
}
PACKAGE_RECORDS = {
    "codex-hepta-intelligence": "intelligence-tests.json",
    "codex-hepta-agentd": "agentd-default-tests.json",
    "codex-hepta-operations": "operations-tests.json",
    "codex-hepta-learning-ledger": "ledger-tests.json",
    "codex-hepta-infer-worker-host": "native-tests.json",
}
FALSE_CLAIMS = (
    "nativeBuildVerified",
    "defaultBinaryProfileComposed",
    "realProcessProviderE2E",
    "targetHostQualified",
    "independentAcceptance",
    "activation",
    "release",
    "allRequirementsClosed",
)
ANSI = re.compile(r"\x1b\[[0-9;]*m")
EXEC_SPEC = importlib.util.spec_from_file_location(
    "hepta_ci_exec", Path(__file__).with_name("hepta_ci_exec.py")
)
assert EXEC_SPEC is not None and EXEC_SPEC.loader is not None
EXEC = importlib.util.module_from_spec(EXEC_SPEC)
EXEC_SPEC.loader.exec_module(EXEC)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def load_json(path: Path) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON field: {key}")
            result[key] = value
        return result

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def source_text(relative: str) -> str:
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():
        raise ValueError(f"unavailable source: {relative}")
    git("ls-files", "--error-unmatch", "--", relative)
    return path.read_text(encoding="utf-8")


def validate_declarations() -> tuple[dict[str, Any], dict[str, Any]]:
    implementation, trace = (load_json(DOCS / name) for name in NAMES)
    if (
        implementation.get("schema")
        != "hepta.intelligence-control-source-declaration.v1"
        or type(implementation.get("schemaVersion")) is not int
        or implementation["schemaVersion"] != 1
    ):
        raise ValueError("unsupported intelligence source declaration schema")
    for value in (implementation, trace):
        identity = value["sourceIdentity"]
        if (
            identity["policy"] != "ci_exact_head_artifact_v2"
            or identity["commitMustEqualCheckoutHead"] is not True
            or identity["commit"] != PLACEHOLDER
            or identity["lane"] != "tracked"
            or identity["executionStatus"] != "pending"
        ):
            raise ValueError(
                "tracked mappings cannot retain a mutable candidate or a pass"
            )
        if value["module"] != "intelligence.control":
            raise ValueError("wrong module mapping")
    status = implementation["statusMatrix"]
    for field in FALSE_CLAIMS:
        if status.get(field) is not False:
            raise ValueError(f"this source-only mapping cannot establish {field}")
    if status["exactHeadExecuted"] or status["syntheticMergeExecuted"]:
        raise ValueError("tracked execution claims must remain pending")
    for field in (
        "nativeExecutionProved",
        "realProcessProviderE2E",
        "targetHostQualified",
        "activation",
        "release",
    ):
        if trace["claimBoundary"].get(field) is not False:
            raise ValueError(f"tracked source declarations cannot establish {field}")
    paths: set[str] = set()
    for binding in implementation["sourceBindings"]:
        text = source_text(binding["sourcePath"])
        paths.add(binding["sourcePath"])
        for symbol in binding["symbols"]:
            if symbol not in text:
                raise ValueError(
                    f"missing source symbol {symbol}: {binding['sourcePath']}"
                )
    operations = {row["operation"] for row in implementation["canonicalOperations"]}
    if not REQUIRED_OPERATIONS.issubset(operations):
        raise ValueError("required canonical operation mapping omitted")
    default_tests = trace["ordinaryProductTests"]
    qualification = trace["qualificationOnlyTests"]
    seen: set[tuple[str, str]] = set()
    for test in default_tests + qualification:
        text = source_text(test["sourcePath"])
        key = (test["sourcePath"], test["name"])
        if key in seen or test["package"] not in PACKAGE_RECORDS:
            raise ValueError(f"duplicate or unknown package test: {key}")
        seen.add(key)
        pattern = re.compile(
            r"(?P<attrs>(?:\s*#\[[^\n]+\]\s*)+)(?:async\s+)?fn\s+"
            + re.escape(test["name"])
            + r"\s*\(",
            re.MULTILINE,
        )
        matches = list(pattern.finditer(text))
        if (
            len(matches) != 1
            or "test" not in matches[0]["attrs"]
            or "ignore" in matches[0]["attrs"]
        ):
            raise ValueError(f"missing, ambiguous or ignored mapped test: {key}")
        if test["executionStatus"] != "pending":
            raise ValueError("source declarations are not test executions")
    default_names = {row["name"] for row in default_tests}
    if not REQUIRED_TESTS.issubset(default_names):
        raise ValueError(
            f"required default regressions omitted: {sorted(REQUIRED_TESTS - default_names)}"
        )
    all_names = {row["name"] for row in default_tests + qualification}
    requirements = {row["id"]: row for row in trace["requirements"]}
    for row in trace["requirements"]:
        if not row["tests"] or not set(row["tests"]).issubset(all_names):
            raise ValueError(f"invalid requirement-to-test mapping: {row['id']}")
    for operation in implementation["canonicalOperations"]:
        if operation["sourcePath"] not in paths or not operation["requirements"]:
            raise ValueError(f"unbound operation: {operation['operation']}")
        if not set(operation["requirements"]).issubset(requirements):
            raise ValueError("unknown operation requirement")
    return implementation, trace


def checkout_identity(head: str) -> dict[str, Any]:
    if re.fullmatch(r"[0-9a-f]{40}", head) is None:
        raise ValueError("invalid tested commit")
    return {
        "commit": head,
        "tree": git("rev-parse", f"{head}^{{tree}}"),
        "parents": git("show", "-s", "--format=%P", head).split(),
        "dirty": False,
    }


def validate_command_record(
    path: Path,
    command: list[str],
    head: str,
    lane: str,
    *,
    expected_identity: dict[str, Any] | None = None,
    expected_directory: str | None = None,
    expected_invocation: dict[str, str | None] | None = None,
) -> tuple[dict[str, Any], str]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("command record missing or symlinked")
    record = load_json(path)
    if type(record.get("schema_version")) is not int or record["schema_version"] != 1:
        raise ValueError("unsupported command record schema")
    if (
        record.get("command") != command
        or record.get("tested_sha") != head
        or record.get("lane") != lane
    ):
        raise ValueError(f"command/source/lane mismatch: {path.name}")
    if record.get("status") != "passed" or any(
        type(record.get(key)) is not int or record[key] != 0
        for key in ("command_exit_code", "exit_code")
    ):
        raise ValueError(f"command did not pass: {path.name}")
    if (
        record.get("timed_out") is not False
        or record.get("output_limit_exceeded") is not False
    ):
        raise ValueError(f"incomplete command: {path.name}")
    before, after = record.get("before"), record.get("after")
    expected = (
        expected_identity if expected_identity is not None else checkout_identity(head)
    )
    if (
        expected.get("commit") != head
        or not isinstance(before, dict)
        or not isinstance(after, dict)
        or before.get("dirty") is not False
        or after.get("dirty") is not False
        or before != after
        or before != expected
    ):
        raise ValueError(f"dirty or changed checkout: {path.name}")
    directory = expected_directory or str((ROOT / "codex-rs").resolve())
    if record.get("working_directory") != directory:
        raise ValueError(f"wrong command working directory: {path.name}")
    invocation = (
        expected_invocation
        if expected_invocation is not None
        else {
            field: os.environ.get(env)
            for field, env in (
                ("run_id", "GITHUB_RUN_ID"),
                ("run_attempt", "GITHUB_RUN_ATTEMPT"),
                ("job", "GITHUB_JOB"),
            )
        }
    )
    if any(record.get(key) != value for key, value in invocation.items()):
        raise ValueError(f"wrong command invocation: {path.name}")
    if lane == "source-head" and record.get("source_sha") != head:
        raise ValueError("wrong source head")
    if lane == "base-merge":
        if any(
            re.fullmatch(r"[0-9a-f]{40}", record.get(key, "")) is None
            for key in ("base_sha", "source_sha")
        ):
            raise ValueError("invalid merge parent commit")
        if before.get("parents") != [record["base_sha"], record["source_sha"]]:
            raise ValueError("wrong merge parents")
        tree = git(
            "merge-tree", "--write-tree", record["base_sha"], record["source_sha"]
        )
        if record.get("recomputed_merge_tree") != tree or before["tree"] != tree:
            raise ValueError("wrong recomputed merge tree")
    elif lane != "source-head":
        raise ValueError("unknown execution lane")
    log_name = record.get("log_file")
    if not isinstance(log_name, str) or Path(log_name).name != log_name:
        raise ValueError("invalid command log path")
    log = path.parent / log_name
    if log.is_symlink() or not log.is_file():
        raise ValueError("command log missing or symlinked")
    if log.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("command log exceeds the execution bound")
    raw = log.read_bytes()
    if (
        type(record.get("log_bytes")) is not int
        or len(raw) != record["log_bytes"]
        or hashlib.sha256(raw).hexdigest() != record.get("log_sha256")
    ):
        raise ValueError("command log digest mismatch")
    text = ANSI.sub("", raw.decode("utf-8", errors="replace"))
    passed, failed = EXEC.observed_test_counts(text)
    if any(
        type(record.get(key)) is not int or record[key] != count
        for key, count in (
            ("observed_passed_tests", passed),
            ("observed_failed_tests", failed),
        )
    ):
        raise ValueError("command test counts differ from the retained log")
    if failed or (command[1] == "test" and passed < 1):
        raise ValueError("no actual passing test summary")
    return record, text


def observed_test_name(text: str, name: str) -> str:
    passed = set(
        re.findall(r"^test\s+([A-Za-z0-9_:]+)\s+\.\.\.\s+ok\s*$", text, re.MULTILINE)
    )
    matches = {
        value for value in passed if value == name or value.endswith("::" + name)
    }
    if len(matches) != 1:
        raise ValueError(f"mapped test not uniquely observed passing: {name}")
    return next(iter(matches))


def project_execution(
    implementation: dict[str, Any],
    trace: dict[str, Any],
    head: str,
    lane: str,
    status: str,
    records: Path | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    implementation, trace = copy.deepcopy(implementation), copy.deepcopy(trace)
    identity = {
        "policy": "ci_exact_head_artifact_v2",
        "commit": head,
        "lane": lane,
        "executionStatus": status,
        "commitMustEqualCheckoutHead": True,
    }
    for value in (implementation, trace):
        value["sourceIdentity"] = identity.copy()
    if status == "passed":
        if records is None:
            raise ValueError("a pass requires the real command-record directory")
        executed = {
            name: validate_command_record(records / name, command, head, lane)
            for name, command in COMMANDS.items()
        }
        for rows, legacy in (
            (trace["ordinaryProductTests"], False),
            (trace["qualificationOnlyTests"], True),
        ):
            for test in rows:
                record_name = (
                    "agentd-qualification-tests.json"
                    if legacy
                    else PACKAGE_RECORDS[test["package"]]
                )
                record, text = executed[record_name]
                test["observedTestName"] = observed_test_name(text, test["name"])
                test["executionStatus"] = "passed"
                test["commandRecord"] = record_name
                test["logSha256"] = record["log_sha256"]
        matrix = implementation["statusMatrix"]
        matrix["exactHeadExecuted"] = lane == "source-head"
        matrix["syntheticMergeExecuted"] = lane == "base-merge"
    for binding in implementation["sourceBindings"]:
        binding["sourceBlob"] = git("rev-parse", f"{head}:{binding['sourcePath']}")
    # Source binding and package execution never assert completion of the open
    # product, authority, file-system, performance or independent-evidence gaps.
    return implementation, trace


def write_pair(directory: Path, values: tuple[dict[str, Any], dict[str, Any]]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, value in zip(NAMES, values):
        (directory / name).write_text(
            json.dumps(value, indent=2) + "\n", encoding="utf-8"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-head")
    parser.add_argument(
        "--execution-status", choices=("pending", "passed", "failed"), default="pending"
    )
    parser.add_argument(
        "--lane", choices=("tracked", "source-head", "base-merge"), default="tracked"
    )
    parser.add_argument("--command-records", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--write-tracked", action="store_true")
    parser.add_argument("--check-tracked", action="store_true")
    args = parser.parse_args()
    values = validate_declarations()
    if args.lane != "tracked":
        head = (
            args.source_head or os.environ.get("TESTED_SHA") or git("rev-parse", "HEAD")
        )
        if head != git("rev-parse", "HEAD") or git(
            "status", "--porcelain", "--untracked-files=normal"
        ):
            raise ValueError(
                "execution projection requires the unchanged exact checkout"
            )
        records = args.command_records
        values = project_execution(
            *values, head, args.lane, args.execution_status, records
        )
    elif args.execution_status != "pending":
        raise ValueError("tracked mappings cannot claim execution")
    if args.write_tracked:
        if args.lane != "tracked":
            raise ValueError(
                "exact execution artifacts cannot overwrite tracked declarations"
            )
        write_pair(DOCS, values)
    if args.output_dir:
        if args.output_dir.resolve().is_relative_to(ROOT):
            raise ValueError("execution artifacts must be outside the source checkout")
        write_pair(args.output_dir, values)
    if not (args.check_tracked or args.write_tracked or args.output_dir):
        print(
            json.dumps(
                {"implementation": values[0], "traceability": values[1]}, indent=2
            )
        )


if __name__ == "__main__":
    try:
        main()
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.CalledProcessError,
    ) as error:
        raise SystemExit(f"intelligence mapping rejected: {error}") from error
