#!/usr/bin/env python3
"""Validate conservative lexical source truth for learning.eval."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from hepta_rust_identifiers import contains_rust_identifier, rust_code_tokens

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "docs/modules/learning.eval/CURRENT_STATUS.json"
MODEL = ROOT / "scripts/learning_eval_status_model.json"
MAP = ROOT / "docs/modules/learning.eval/IMPLEMENTATION_MAP.json"
EVAL_ROOT = ROOT / "codex-rs/hepta-intelligence-eval"
# Fixed owned roots prevent a partial or stale implementation map from omitting
# executable source, build inputs, fixtures or newly added files from observation.
SOURCE_IDENTITY_ROOTS = ("codex-rs/hepta-intelligence-eval",)
FALSE_CLAIMS = {
    "productionImplementation",
    "targetHostQualified",
    "independentAcceptance",
    "activation",
    "release",
}
TRUE_SOURCE = {
    "checkpointTailRecoveryImplemented",
    "consumerBoundAdmissionComposed",
    "durableAttemptJournalImplemented",
    "lifecycleCapacityReservationImplemented",
    "multiOutcomeTypedArchiveImplemented",
    "nearCapacityFileRegressionImplemented",
    "publicationReconciliationImplemented",
    "rootActivatedRecoveryTrustImplemented",
    "sequentialClusterConfidenceImplemented",
    "temporalCrossFitExecutorImplemented",
    "typedArchiveInternalReverificationImplemented",
    "verifiedCompactionImplemented",
}
REQUIRED_SYMBOLS = {
    "RecordedProductEvaluationRunnerV1::evaluate_temporal_comparison",
    "RecordedProductEvaluationRunnerV1::qualify_and_persist",
    "RecordedProductEvaluationRunnerV1::qualify_and_persist_with_artifacts",
    "admit_signed_eligibility_v2",
    "ReconciledProductQualificationSinkV1::persist",
    "LockedFileProductEvaluationAttemptJournalV1",
    "AttemptCapacity::project",
    "LockedFileProductEvaluationAttemptJournalV1::create_with_qualification_limits",
    "LockedFileProductEvaluationAttemptJournalV1::recover_with_qualification_limits",
    "LockedFileProductEvaluationAttemptJournalV1::checkpoint_into",
    "LockedFileProductEvaluationAttemptJournalV1::recover_with_checkpoint",
    "AnchoredProductEvaluationAttemptJournalV1::recover_with_checkpoint",
    "RecordedProductEvaluationRunnerV1::reconcile_pending_page",
    "Archive::persist",
    "qualification_archive::recover",
    "RecordedProductEvaluationRunnerV1::qualify_and_persist_on_selected_host",
    "RecordedProductEvaluationRunnerV1::qualify_outcomes_and_persist_on_selected_host",
    "RecordedProductEvaluationRunnerV1::recover_selected_host_qualification",
    "RecordedProductEvaluationRunnerV1::recover_selected_host_outcome_qualification",
    "RecordedProductEvaluationRunnerV1::recover_selected_host_pending_page",
    "RecoveryTrustFrontierV1::admit",
    "CrossFoldPlanV1::execute_temporal_cross_fit_v1",
    "SequentialPlan::estimate_cluster_intervals_v1",
    "LockedFileFinalHoldoutCasStoreV1::compact_into",
    "decide_with_signed_evidence_v2",
    "decide_with_signed_longitudinal_evidence_v3",
}
REQUIRED_TOKENS = {
    "codex-rs/hepta-intelligence-eval/src/qualification_archive.rs": [
        "No decoder callback",
        "QualificationArtifactsPersisted",
    ],
    "codex-rs/hepta-intelligence-eval/src/selected_host_recovery_controller.rs": [
        "recover_selected_host_pending_page",
        "ActivatedLearningTrustV1",
        "selected-host recovery trust regressed",
        "PublicationPending",
    ],
    "codex-rs/hepta-intelligence-eval/src/attempt_capacity.rs": [
        "struct AttemptCapacity",
        "fn project",
        "pending_page",
    ],
    "codex-rs/hepta-intelligence-eval/src/attempt_checkpoint.rs": [
        "checkpoint_into",
        "recover_with_checkpoint",
        "checkpoint_binding",
    ],
    "codex-rs/hepta-intelligence-eval/tests/near_capacity.rs": [
        "create_with_qualification_limits",
        "recover_with_qualification_limits",
        "near_capacity_rejects_new_admission_but_reserved_attempt_reaches_terminal",
    ],
    "codex-rs/hepta-intelligence-eval/src/temporal_cross_fit.rs": [
        "execute_temporal_cross_fit_v1",
        "cross-fit held-out decision reuse",
        "cross-fit preregistered output",
    ],
    "codex-rs/hepta-intelligence-eval/src/sequential_confidence.rs": [
        "estimate_cluster_intervals_v1",
        "ConfidenceEnvelope",
        "InsufficientClusters",
    ],
    "codex-rs/hepta-agentd/src/intelligence_outcome_evaluation.rs": [
        "consume_outcome_qualification_v1",
        "use_attestation",
        "current_owner",
    ],
    "codex-rs/hepta-intelligence-eval/tests/cold_recovery_e2e.rs": [
        "cold_process_recovery_uses_only_persisted_inputs_and_current_trust",
    ],
    "codex-rs/hepta-intelligence-eval/tests/long_running_profile.rs": [
        "checkpoint_into",
        "recover_with_checkpoint",
        "HEPTA_LEARNING_EVAL_SOAK_ATTEMPTS",
    ],
    "codex-rs/hepta-intelligence-eval/PRODUCTION_CONTRACT.md": [
        "QualificationArtifactsPersisted",
        "execute_temporal_cross_fit_v1",
        "estimate_cluster_intervals_v1",
        "recover_with_checkpoint",
    ],
    "codex-rs/hepta-intelligence-eval/RECOVERY_CONTRACT.md": [
        "Canonical typed qualification archive",
        "Independently anchored checkpoints and tail replay",
        "Persistent recovery controller",
    ],
    "codex-rs/hepta-intelligence-eval/RECOVERY_TRUST_CAPACITY_CONTRACT.md": [
        "Per-attempt current trust at recovery use",
        "Full-lifecycle capacity and qualification limits",
        "External gates remain false",
    ],
    "codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md": [
        "execute_temporal_cross_fit_v1",
        "estimate_cluster_intervals_v1",
        "recover_with_checkpoint",
        "CURRENT_STATUS.json",
    ],
    "docs/modules/learning.eval/RECOVERY_AMENDMENT_20260928.md": [
        "a43cbc5c167f9acfb8130c108693623641662ff0",
        "28672",
        "External gates remain false",
    ],
}
REQUIRED_CODE_CALLS = {
    "codex-rs/hepta-intelligence-eval/src/qualification_archive.rs": [
        "archive.verify(verifier, now)",
    ],
    "codex-rs/hepta-intelligence-eval/src/selected_host_recovery_controller.rs": [
        "cursor.save(Some(&id))",
    ],
}


def canonical(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        text=True,
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def require_tokens() -> None:
    for relative, tokens in REQUIRED_TOKENS.items():
        path = ROOT / relative
        if not path.is_file():
            raise SystemExit(f"missing required path: {relative}")
        text = path.read_text(encoding="utf-8")
        for token in tokens:
            if token not in text:
                raise SystemExit(f"{relative}: missing {token!r}")
    for relative, calls in REQUIRED_CODE_CALLS.items():
        path = ROOT / relative
        if not path.is_file():
            raise SystemExit(f"missing required path: {relative}")
        tokens = rust_code_tokens(path.read_text(encoding="utf-8"))
        for call in calls:
            expected = rust_code_tokens(call)
            if not any(
                tokens[index : index + len(expected)] == expected
                and (index == 0 or tokens[index - 1] not in (".", ":"))
                for index in range(len(tokens) - len(expected) + 1)
            ):
                raise SystemExit(f"{relative}: missing code call {call!r}")


def external_references(symbol: str) -> list[str]:
    results: list[str] = []
    for path in sorted((ROOT / "codex-rs").rglob("*.rs")):
        if EVAL_ROOT in path.parents or "/tests/" in path.as_posix():
            continue
        if path.name.endswith(("_tests.rs", "_test_support.rs")):
            continue
        if contains_rust_identifier(path.read_text(encoding="utf-8"), symbol):
            results.append(path.relative_to(ROOT).as_posix())
    return results


def validate_map(model: dict) -> None:
    value = json.loads(MAP.read_text(encoding="utf-8"))
    if (
        value.get("schema") != "hepta.module-implementation-map.v3"
        or value.get("module") != "learning.eval"
    ):
        raise SystemExit("implementation-map identity drift")
    rows = value.get("operations", [])
    symbols = [row.get("nativeSymbol") for row in rows]
    missing = REQUIRED_SYMBOLS - set(symbols)
    if missing or len(symbols) != len(set(symbols)):
        raise SystemExit(f"implementation-map operation drift: {sorted(missing)}")
    checked_paths: set[str] = set()
    for row in rows:
        path = row.get("sourcePath")
        file = ROOT / str(path)
        token = str(row.get("nativeSymbol")).rsplit("::", 1)[-1]
        if not file.is_file() or token not in file.read_text(encoding="utf-8"):
            raise SystemExit(f"mapped source/symbol absent: {path}::{token}")
        checked_paths.add(str(path))
        for test in row.get("tests", []):
            if not (ROOT / test).is_file():
                raise SystemExit(f"mapped test absent: {test}")
            checked_paths.add(test)
    if value.get("productCallers") != model["sourceFacts"]["callers"]:
        raise SystemExit("caller inventory drift")
    if value.get("repositoryControlledGaps") != model["repositoryControlledGaps"]:
        raise SystemExit("open-obligation inventory drift")
    boundary = value.get("claimBoundary", {})
    if any(boundary.get(key) is not True for key in TRUE_SOURCE):
        raise SystemExit("source claim-boundary drift")
    if any(boundary.get(key) is not False for key in FALSE_CLAIMS):
        raise SystemExit("external claim self-issued")
    source = value.get("sourceBase", {})
    commit, tree = source.get("commit", ""), source.get("tree", "")
    if (
        len(commit) != 40
        or git("rev-parse", f"{commit}^{{tree}}").stdout.strip() != tree
    ):
        raise SystemExit("source observation identity drift")
    git("merge-base", "--is-ancestor", commit, "HEAD")
    for caller in model["sourceFacts"]["callers"]:
        checked_paths.add(caller["sourcePath"])
    observed_paths = sorted(checked_paths | set(SOURCE_IDENTITY_ROOTS))
    changed = sorted(
        set(
            filter(
                None,
                git(
                    "diff",
                    "--no-ext-diff",
                    "--name-only",
                    "-z",
                    commit,
                    "--",
                    *observed_paths,
                ).stdout.split("\0"),
            )
        )
    )
    if changed:
        raise SystemExit(
            "owned or mapped source changed after observation: " + ", ".join(changed)
        )
    untracked = sorted(
        set(
            filter(
                None,
                git(
                    "ls-files",
                    "--others",
                    "--exclude-standard",
                    "-z",
                    "--",
                    *observed_paths,
                ).stdout.split("\0"),
            )
        )
    )
    if untracked:
        raise SystemExit(
            "untracked owned or mapped source lacks observation: "
            + ", ".join(untracked)
        )


def validate() -> dict:
    require_tokens()
    model = json.loads(MODEL.read_text(encoding="utf-8"))
    if model.get("schema") != "hepta.learning-eval.current-status.v1":
        raise SystemExit("status-model identity drift")
    if any(model["claims"].get(key) is not False for key in FALSE_CLAIMS):
        raise SystemExit("status model self-issued an external claim")
    validate_map(model)
    lib = (EVAL_ROOT / "src/lib.rs").read_text(encoding="utf-8")
    for symbol, module in (
        ("decide_with_signed_evidence_v2", "signed_evaluation"),
        ("decide_with_signed_longitudinal_evidence_v3", "longitudinal_time"),
    ):
        if f"pub use {module}::{symbol};" in lib or external_references(symbol):
            raise SystemExit(f"external low-level decision ingress: {symbol}")
    raw = external_references("ProductEvaluationRunnerV1")
    if raw:
        raise SystemExit(f"external raw product runner references: {raw}")
    return model


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("write", "verify", "print"))
    args = parser.parse_args()
    if args.command == "verify":
        for pattern in (
            "test_hepta_rust_identifiers.py",
            "test_hepta_learning_eval_projection.py",
            "test_hepta_learning_eval_status.py",
        ):
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    str(ROOT / "scripts"),
                    "-p",
                    pattern,
                ],
                check=True,
            )
    output = canonical(validate())
    if args.command == "print":
        print(output, end="")
    elif args.command == "write":
        STATUS.write_text(output, encoding="utf-8")
        print(json.dumps({"written": str(STATUS.relative_to(ROOT))}))
    elif not STATUS.is_file() or STATUS.read_text(encoding="utf-8") != output:
        raise SystemExit(
            "learning.eval status is stale; run scripts/hepta-learning-eval-status.py write"
        )
    else:
        print(
            json.dumps(
                {
                    "status": "ok",
                    "evidenceClass": "lexical_source_inventory",
                    "documentsChecked": 6,
                }
            )
        )


if __name__ == "__main__":
    main()
