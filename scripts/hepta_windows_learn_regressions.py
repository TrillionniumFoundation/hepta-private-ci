#!/usr/bin/env python3
"""Run exact Windows LEARN regressions once and retain source-bound native evidence."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from hepta_ci_exec import identity, observed_test_counts
from hepta_ci_junit import NoDoctypeTreeBuilder, collect

# Public, exact case inventory. Changes require native nextest-list confirmation.
# The original 19 Agentd + 2 reader cases remain a separately assessed group.
CASE_LIST = {
    "original_windows_21": {
        "codex-hepta-agentd": [
            "circuit_cell::tests::credit_tests::signed_tests::signed_credit_rejects_cross_owner_ledger_episode_before_any_append",
            "circuit_task::source::tests::ordinary_source_publishes_original_circuit_result_and_reopens_exact_inputs",
            "circuit_task::source::tests::ordinary_source_rejects_rebound_record_dispatch_source_and_torn_history",
            "circuit_task::source::tests::ordinary_source_withdrawal_and_uncertain_withdrawal_survive_reopen",
            "circuit_task::source::tests::ordinary_source_lost_admission_ack_remains_pending_and_completed_ack_is_read_only",
            "circuit_task::source::tests::ordinary_source_input_and_result_ack_loss_never_repeat_committed_inference",
            "neuron_cell_evaluation::tests::actual_file_owners_compute_sign_and_publish_only_bound_comparison",
            "neuron_cell_evaluation::tests::changed_costs_or_unclosed_owner_cannot_reuse_a_frozen_comparison",
            "neuron_cell_evaluation::tests::different_task_and_unknown_holdout_release_remain_fail_closed",
            "neuron_cell_evaluation::tests::missing_or_unknown_costs_refuse_gain_while_unrequested_energy_stays_unknown",
            "neuron_cell_evaluation::tests::original_owner::original_evaluator_signs_actual_execution_once_and_reopens_exact_bytes",
            "neuron_cell_evaluation::tests::original_owner::original_evaluator_uncertain_claim_never_resigns_and_complete_ack_reads_original",
            "neuron_cell_evaluation::tests::readback::changed_cell_journals_and_foreign_product_plan_never_claim_execution",
            "neuron_cell_evaluation::tests::readback::changed_learning_profile_is_refused_before_claim_or_holdout_contact",
            "neuron_cell_evaluation::tests::readback::completed_cell_execution_reopens_with_original_evaluator",
            "neuron_cell_evaluation::tests::readback::missing_cell_execution_readback_never_claims_or_releases",
            "neuron_cell_evaluation::tests::readback::pending_cell_execution_readback_never_reissues_work",
            "neuron_cell_evaluation::tests::same_snapshot_but_changed_journal_cut_is_rejected_before_provider",
            "neuron_cell_evaluation::tests::unfair_or_missing_training_declarations_never_consume_holdout",
        ],
        "codex-hepta-intelligence-eval": [
            "qualification_file_observation::tests::original_handle_bytes_detect_equal_length_changes_and_retain_lock_and_cursor",
            "qualification_file_observation::tests::bounded_original_handle_reads_restore_cursor_after_io_error",
        ],
    },
    "ledger_current_7": {
        "codex-hepta-learning-ledger": [
            "durable::current_tests::current_reads_complete_original_bytes_and_preserves_cursor",
            "durable::current_tests::current_rejects_a_different_valid_same_length_ledger",
            "durable::current_tests::current_refuses_truncation_short_tail_extra_tail_and_header_corruption_without_repair",
            "witness::current_tests::current_reread_preserves_original_cursor_bytes_and_append_owner",
            "witness::current_tests::current_refuses_physical_length_changes_without_repair_or_rearm",
            "witness::current_tests::current_detects_rehashed_history_even_with_unchanged_latest_frontier",
            "witness::current_tests::recovered_current_detects_same_length_corruption_and_valid_frontier_substitution",
        ]
    },
    "original_owner_current_4": {
        "codex-hepta-intelligence-eval": [
            "product_execution_file::tests::current::current_reread_preserves_bytes_cursor_and_original_append_owner",
            "product_execution_file::tests::current::current_rejects_same_length_corruption_and_cannot_be_rearmed",
            "product_execution_file::tests::current::current_rejects_rehashed_valid_same_length_replacement",
            "product_execution_file::tests::current::current_refuses_length_changes_without_repair",
        ]
    },
    "dataset_materialization": {
        "codex-hepta-agentd": [
            "cell_q24_dataset::tests::original_task_and_signed_cut_materialize_exact_q24_without_writes_or_new_claims",
            "cell_q24_dataset::tests::source_identity_signed_freeze_and_ledger_domain_cannot_be_rebound",
            "cell_q24_dataset::tests::nonterminal_nonrepresentable_and_out_of_range_targets_are_never_clipped_or_filled",
            "cell_q24_dataset::tests::current_uses_internal_time_and_rechecks_expiry_after_physical_reads",
        ]
    },
}

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
TERMINAL = re.compile(
    r"^\s*(PASS|FAIL|TIMEOUT|EXECFAIL|LEAK|SKIP)\s+\[[^\]\n]+\]\s+"
    r"(?:\(\s*\d+/\d+\)\s+)?(\S+)\s+(\S+)\s*$",
    re.MULTILINE,
)
NATIVE_TARGET = "x86_64-pc-windows-msvc"
MAXIMUM_REPORT_BYTES = 64 * 1024 * 1024


def expected_groups() -> dict[str, list[tuple[str, str]]]:
    original = CASE_LIST["original_windows_21"]
    if {package: len(names) for package, names in original.items()} != {
        "codex-hepta-agentd": 19,
        "codex-hepta-intelligence-eval": 2,
    }:
        raise ValueError("the original Windows 21-case group changed size")
    groups = {
        group: [
            (package, name) for package, names in packages.items() for name in names
        ]
        for group, packages in CASE_LIST.items()
    }
    cases = [case for group in groups.values() for case in group]
    if not all(groups.values()) or len(set(cases)) != len(cases):
        raise ValueError(
            "case inventory is empty or has duplicate package/name identities"
        )
    return groups


def command_for(groups: dict[str, list[tuple[str, str]]]) -> list[str]:
    cases = [case for group in groups.values() for case in group]
    packages = sorted({package for package, _ in cases})
    filters = [
        "(package(="
        + package
        + ") & ("
        + " | ".join("test(=" + name + ")" for owner, name in cases if owner == package)
        + "))"
        for package in packages
    ]
    command = ["just", "test", "--locked", "--target", NATIVE_TARGET]
    for package in packages:
        command.extend(["-p", package])
    return command + [
        "--lib",
        "-E",
        " | ".join(filters),
        "--test-threads",
        "1",
        "--no-tests",
        "fail",
        "--retries",
        "0",
    ]


def assess_log(text: str, groups: dict[str, list[tuple[str, str]]]) -> dict:
    text = ANSI.sub("", text)
    rows = TERMINAL.findall(text)
    expected = Counter(case for group in groups.values() for case in group)
    actual = Counter((package, name) for _, package, name in rows)
    passed, failed = observed_test_counts(text)
    starts = re.findall(r"Starting (\d+) tests? across", text)
    selected = int(starts[-1]) if starts else None
    coverage = {}
    for group, cases in groups.items():
        named = [
            (status, (package, name))
            for status, package, name in rows
            if (package, name) in cases
        ]
        coverage[group] = {
            "expected_count": len(cases),
            "observed_pass_rows": sum(status == "PASS" for status, _ in named),
            "exact_pass_coverage": (
                Counter(case for _, case in named) == Counter(cases)
                and all(status == "PASS" for status, _ in named)
            ),
        }
    return {
        "selected_count": selected,
        "observed_passed_tests": passed,
        "observed_failed_tests": failed,
        "exact_pass_coverage": (
            selected == sum(expected.values())
            and actual == expected
            and all(status == "PASS" for status, _, _ in rows)
            and passed == selected
            and failed == 0
        ),
        "groups": coverage,
        "terminal_rows": rows,
    }


def assess_junit(data: bytes, groups: dict[str, list[tuple[str, str]]]) -> dict:
    if len(data) > MAXIMUM_REPORT_BYTES:
        raise ValueError("JUnit exceeds its byte bound")
    root = ET.fromstring(data, parser=ET.XMLParser(target=NoDoctypeTreeBuilder()))
    if root.tag not in ("testsuite", "testsuites"):
        raise ValueError("unexpected JUnit root")
    cases = list(root.iter("testcase"))
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    suite_owners = {
        id(case): suite.get("name")
        for suite in suites
        for case in suite.findall("testcase")
    }
    negative = (
        "failure",
        "error",
        "skipped",
        "rerunFailure",
        "rerunError",
        "flakyFailure",
        "flakyError",
    )
    expected = Counter(case for group in groups.values() for case in group)
    # Pinned nextest 0.9.103 uses its stable lib binary ID (the package name)
    # for both suite.name and testcase.classname. No stress run is selected.
    native_suites = (
        len(suites) == len(list(root.iter("testsuite")))
        and Counter(suite.get("name") for suite in suites)
        == Counter({package for package, _ in expected})
        and len(suite_owners) == len(cases)
    )
    coverage = {}
    for group, identities in groups.items():
        observed = [
            case
            for case in cases
            if (case.get("classname"), case.get("name")) in identities
        ]
        coverage[group] = {
            "expected_count": len(identities),
            "observed_testcases": len(observed),
            "exact_pass_coverage": (
                Counter((case.get("classname"), case.get("name")) for case in observed)
                == Counter(identities)
                and all(
                    suite_owners.get(id(case)) == case.get("classname")
                    for case in observed
                )
                and not any(
                    case.find(tag) is not None for case in observed for tag in negative
                )
            ),
        }
    return {
        "total_testcases": len(cases),
        "native_suite_identity": native_suites,
        "exact_pass_coverage": (
            native_suites
            and Counter((case.get("classname"), case.get("name")) for case in cases)
            == expected
            and all(
                suite_owners.get(id(case)) == case.get("classname") for case in cases
            )
            and not any(
                case.find(tag) is not None for case in cases for tag in negative
            )
        ),
        "groups": coverage,
    }


def write_json(path: Path, value: dict, *, replace: bool = False) -> None:
    pending = path.with_suffix(".pending") if replace else path
    with pending.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    if replace:
        pending.replace(path)


def run(expected_head: str, output: Path) -> int:
    if sys.platform != "win32" or os.name != "nt":
        raise ValueError(
            "native Windows is required; no other host can issue this result"
        )
    if re.fullmatch(r"[0-9a-f]{40}", expected_head) is None:
        raise ValueError("expected head must be one full commit SHA")
    root = Path(__file__).resolve().parents[1]
    output = output.resolve()
    if output.is_relative_to(root):
        raise ValueError("execution evidence must remain outside the source checkout")
    groups = expected_groups()
    command = command_for(groups)
    output.mkdir(parents=True, exist_ok=False)
    os.chdir(root / "codex-rs")
    os.environ["SOURCE_SHA"] = expected_head
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    receipt_path = output / "receipt.json"
    execution_path = output / "execution.json"
    receipt = {
        "schema": "hepta.windows-learn-native-regressions.v1",
        "status": "running",
        "source_sha": expected_head,
        "expected_cases": CASE_LIST,
        "build_target": NATIVE_TARGET,
        "cargo_build_target": os.environ.get("CARGO_BUILD_TARGET"),
        "expected_test_count": sum(len(cases) for cases in groups.values()),
        "test_retries": 0,
        "native_platform": platform.platform(),
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "job": os.environ.get("GITHUB_JOB"),
    }
    write_json(receipt_path, receipt)
    record = {
        "schema_version": 1,
        "kind": "native-command-execution",
        "source_sha": expected_head,
        "tested_sha": expected_head,
        "base_sha": os.environ.get("BASE_SHA", ""),
        "lane": "source-head",
        "command": command,
        "working_directory": str(Path.cwd()),
        "build_target": receipt["build_target"],
        "cargo_build_target": receipt["cargo_build_target"],
        "run_id": receipt["run_id"],
        "run_attempt": receipt["run_attempt"],
        "job": receipt["job"],
        "status": "running",
        "command_exit_code": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "supervision": "Existing Windows Actions job timeout; no POSIX process-group claim.",
    }
    write_json(execution_path, record)
    started = time.monotonic()
    native_junit = None
    exit_code = 1
    try:
        record["before"] = identity()
        if record["before"]["dirty"] or record["before"]["commit"] != expected_head:
            raise ValueError("checkout differs from the exact clean source")
        compiler = subprocess.check_output(
            ["rustc", "--version", "--verbose"], text=True
        )
        if receipt["cargo_build_target"] != NATIVE_TARGET:
            raise ValueError(
                "CARGO_BUILD_TARGET must select the native Windows MSVC target"
            )
        if f"host: {NATIVE_TARGET}" not in compiler.splitlines():
            raise ValueError("the compiler is not the native Windows MSVC host")
        (output / "compiler.txt").write_text(compiler, encoding="utf-8")
        metadata = json.loads(
            subprocess.check_output(
                ["cargo", "metadata", "--locked", "--no-deps", "--format-version=1"],
                text=True,
            )
        )
        # Nextest 0.9.103 stores profile reports under workspace store.dir,
        # independently of the Cargo --target artifact subdirectory.
        native_junit = (
            Path(metadata["workspace_root"]) / "target/nextest/local/junit.xml"
        )
        record["cargo_target_directory"] = metadata["target_directory"]
        record["native_junit_source_path"] = str(native_junit)
        native_junit.unlink(missing_ok=True)
        log = output / "native.log"
        record["log_file"] = log.name
        with log.open("xb") as stream:
            completed = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT)
            stream.flush()
            os.fsync(stream.fileno())
        record["command_exit_code"] = completed.returncode
        if log.stat().st_size > MAXIMUM_REPORT_BYTES:
            raise ValueError("native log exceeds its observation bound")
        data = log.read_bytes()
        record["log_bytes"] = len(data)
        record["log_sha256"] = hashlib.sha256(data).hexdigest()
        assessment = assess_log(data.decode("utf-8", errors="replace"), groups)
        receipt["log_coverage"] = assessment
        record["observed_passed_tests"] = assessment["observed_passed_tests"]
        record["observed_failed_tests"] = assessment["observed_failed_tests"]
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
        record["after"] = identity()
        if completed.returncode or not assessment["exact_pass_coverage"]:
            raise ValueError("native command did not pass every exact named case once")
        if record["after"] != record["before"]:
            raise ValueError("source identity changed during native execution")
        record["status"] = "passed"
        exit_code = 0
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as error:
        record["status"] = "failed"
        record["error"] = str(error)
    finally:
        record["finished_at"] = datetime.now(timezone.utc).isoformat()
        record["elapsed_seconds"] = time.monotonic() - started
        record["exit_code"] = exit_code
        write_json(execution_path, record, replace=True)

    retained = output / "native-junit.xml"
    collection_exit = 1
    try:
        if native_junit is None:
            raise ValueError("native command produced no JUnit path")
        collection_exit = collect(execution_path, native_junit, retained)
        if retained.exists():
            receipt["junit_coverage"] = assess_junit(retained.read_bytes(), groups)
        if collection_exit or not receipt.get("junit_coverage", {}).get(
            "exact_pass_coverage"
        ):
            raise ValueError(
                "fresh native JUnit did not cover the exact case inventory"
            )
        receipt["status"] = "passed"
        exit_code = 0
    except (OSError, ValueError, ET.ParseError) as error:
        receipt["status"] = "failed"
        receipt["error"] = str(error)
        exit_code = 1
    receipt["junit_collection_exit_code"] = collection_exit
    receipt["execution_sha256"] = hashlib.sha256(
        execution_path.read_bytes()
    ).hexdigest()
    receipt["exit_code"] = exit_code
    write_json(receipt_path, receipt, replace=True)
    print(json.dumps(receipt, sort_keys=True), flush=True)
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        return run(args.expected_head, args.output)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f"Windows native regressions not dispatched: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
