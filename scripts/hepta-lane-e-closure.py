#!/usr/bin/env python3
"""Canonical Lane E CLI: frozen source checks plus one active workflow contract.

The source-check core is retained byte-for-byte to make this extraction auditable.
Its legacy composite verify/main/workflow functions are not entry points here.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

import hepta_lane_e_source_checks as checks
from hepta_workflow_commands import workflow_commands


# Finite source additions already registered in the baseline matrix and dossier.
# Do not derive expectations from the candidate being checked.
checks.EXPECTED_CASES = checks.EXPECTED_CASES | {"OP-05", "OP-06"}
checks.EXPECTED_OPERATIONS["learning.operator"] = (
    checks.EXPECTED_OPERATIONS["learning.operator"] | {
        "validate_applicability_with_signed_evidence_v2",
        "admit_operator_regularity_with_signed_evidence_v2",
        "verify_tabular_operator_plan_v2",
        "fit_tabular_operator_verified_v2",
        "verify_world_model_dataset_v2",
        "fit_transition_model_verified_v2",
    }
)


def verify_workflow(findings: checks.Findings) -> None:
    path = checks.WORKFLOW_PATH
    findings.require(path.is_file(), "workflow_missing", "Lane E exact-head workflow is missing")
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    commands = workflow_commands(text)
    tests = [command for command in commands
             if command[:2] in (["cargo", "test"], ["just", "test"]) and "--locked" in command]
    for crate in checks.EXPECTED_CRATES:
        findings.require(
            any(any(command[index:index + 2] in (["-p", crate], ["--package", crate])
                    for index in range(len(command) - 1)) for command in tests),
            "workflow_crate_missing", f"workflow does not execute locked tests for {crate}")
    for subcommand in ("check", "clippy"):
        findings.require(
            any(command[:2] == ["cargo", subcommand] and "--locked" in command for command in commands),
            "workflow_gate_missing", f"workflow is missing locked cargo {subcommand}")
    findings.require(any(command[:2] == ["cargo", "fmt"] for command in commands),
                     "workflow_gate_missing", "workflow is missing cargo fmt")
    findings.require(any(command[:3] == ["python3", "scripts/hepta-lane-e-closure.py", "verify"] for command in commands),
                     "workflow_gate_missing", "workflow is missing source closure verification")
    for function in ("lane_e_causal_candidate_chain_is_digest_bound_and_deny_all", "cross_language_wire_fault"):
        findings.require(
            any(function in command and any(command[index:index + 2] == ["-p", "codex-hepta-shadow-qualification"]
                                             for index in range(len(command) - 1)) for command in tests),
            "workflow_gate_missing", f"workflow does not execute {function}")
    findings.require(bool(re.search(r"^  synthetic-merge:\s*$", text, re.MULTILINE)),
                     "workflow_gate_missing", "workflow is missing synthetic-merge job")
    # One version of each executable pin. The former gate required both coverage
    # 0.9.0 and 0.9.1 and two different attestation SHAs from one workflow.
    required_tokens = (
        "learning-eval-qualification:",
        "cargo-llvm-cov@0.9.0",
        "fenced_holdout",
        "qualification.json",
        "actions/attest-build-provenance@4d101475d8b20a2381f78447822ac1eab6504dd8",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
        "trusted-inprocess-eval",
        "--test operator_claim",
        "decide_with_signed_evidence_v2",
        "FencedFinalHoldoutOwnerV1",
        "ProductEvaluationRunnerV1",
        "evaluated_shadow",
        "--fail-under-lines 85",
        "signed_qualification_e2e",
        "--features trusted-inprocess-eval",
        "scripts/hepta-learning-eval-evidence.py emit",
        "scripts/hepta-learning-eval-evidence.py verify",
        "id-token: write",
        "attestations: write",
        "Adversarial qualification stress",
        "Strict merged Lane E lint",
        "--coverage .hepta-evidence/learning-eval/coverage.json",
        "--stress .hepta-evidence/learning-eval/stress.json",
        "--stress-log .hepta-evidence/learning-eval/stress.log",
        "--runtime-log .hepta-evidence/learning-eval/runtime-e2e.log",
        "github.event.before",
    )
    for token in required_tokens:
        findings.require(token in text, "workflow_gate_missing",
                         f"workflow is missing qualification control: {token}")
    findings.require(not checks.TEMPORARY_WORKFLOW_PATH.exists(), "temporary_workflow_present",
                     "temporary generated-file materializer must not remain in the candidate")


def verify() -> checks.Findings:
    findings = checks.Findings()
    matrix = checks.load_json(checks.MATRIX_PATH, findings)
    trace = checks.load_json(checks.TRACE_PATH, findings)
    modules = checks.verify_matrix(matrix, findings)
    checks.verify_traceability(trace, modules, findings)
    checks.verify_learning_eval_production_boundary(findings)
    checks.verify_product_writer_exclusivity(findings)
    checks.verify_authority_posture(findings)
    verify_workflow(findings)
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("verify", "self-test"), nargs="?", default="verify")
    args = parser.parse_args()
    findings = checks.run_self_test() if args.command == "self-test" else verify().items
    print(json.dumps({"schema": "hepta.lane-e-closure-verification.v1", "command": args.command,
                      "ok": not findings, "findingCount": len(findings),
                      "findings": [finding.__dict__ for finding in findings]}, indent=2, sort_keys=True))
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
