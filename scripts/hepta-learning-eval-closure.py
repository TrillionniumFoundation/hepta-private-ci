#!/usr/bin/env python3
"""Closed-world source verifier for learning.eval production/recovery boundaries."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = ROOT / "codex-rs/hepta-intelligence-eval"
LIB = EVAL_ROOT / "src/lib.rs"
MAP = ROOT / "docs/modules/learning.eval/IMPLEMENTATION_MAP.json"
STATE = ROOT / "docs/modules/learning.eval/CURRENT_STATE.json"
STATUS = ROOT / "docs/modules/learning.eval/CURRENT_STATUS.md"
PRODUCTION = EVAL_ROOT / "PRODUCTION_CONTRACT.md"
RECOVERY = EVAL_ROOT / "RECOVERY_CONTRACT.md"
TARGET_ACCEPTANCE = ROOT / "docs/modules/learning.eval/TARGET_HOST_ACCEPTANCE.md"
TARGET_SCHEMA = ROOT / "docs/modules/learning.eval/TARGET_HOST_PROFILE.schema.json"
API_WORKFLOW = ROOT / ".github/workflows/hepta-learning-eval-api-boundary.yml"
LANE_WORKFLOW = ROOT / ".github/workflows/hepta-lane-e-gap-closure.yml"
BOUNDARY_SCRIPT = ROOT / "scripts/hepta-learning-eval-api-boundary.py"
STATUS_SCRIPT = ROOT / "scripts/hepta-learning-eval-status.py"
COMPILE_FAIL = ROOT / "qualification/compile-fail/learning-eval-private-api.rs"

EXPECTED_CALLERS = {
    "codex-rs/hepta-agentd/src/intelligence_evaluation.rs": (
        "RepositoryEvaluationConsumerV1::Agentd",
        "admit_repository_evaluation_v1",
    ),
    "codex-rs/hepta-intelligence/src/plasticity_product.rs": (
        "RepositoryEvaluationConsumerV1::Plasticity",
        "admit_repository_evaluation_v1",
    ),
    "codex-rs/hepta-intelligence/src/evaluated_shadow.rs": (
        "ProductQualificationReceiptV1",
        "run_evaluated_shadow_v1",
    ),
}

EXPECTED_OPERATIONS = {
    "estimate_ope",
    "estimate_cluster_intervals",
    "estimate_sequential",
    "evaluate_temporal_holdout",
    "freeze_product_evaluation_plan_v1",
    "ProductEvaluationRunnerV1::evaluate_temporal_comparison",
    "ProductEvaluationRunnerV1::qualify_and_persist",
    "AuditedProductEvaluationRunnerV1",
    "admit_repository_evaluation_v1",
    "EvaluationAttemptJournalV1",
    "ReconcilingQualificationEvidenceSinkV1",
    "FencedFinalHoldoutOwnerV1::consume",
    "LockedFileFinalHoldoutCasStoreV1",
    "LockedCheckpointFinalHoldoutCasStoreV1",
    "LockedCheckpointFinalHoldoutCasStoreV1::compact_into",
    "decide_with_signed_evidence_v2",
    "decide_with_signed_longitudinal_evidence_v3",
    "run_evaluated_shadow_v1",
}

RAW_PRIMITIVES = (
    "decide_with_signed_evidence_v2",
    "decide_with_signed_longitudinal_evidence_v3",
)


@dataclass(frozen=True)
class Finding:
    code: str
    message: str


class Findings:
    def __init__(self) -> None:
        self.items: list[Finding] = []

    def require(self, condition: bool, code: str, message: str) -> None:
        if not condition:
            self.items.append(Finding(code, message))

    def add(self, code: str, message: str) -> None:
        self.items.append(Finding(code, message))


def load_json(path: Path, findings: Findings) -> dict[str, Any]:
    if not path.is_file():
        findings.add("file_missing", f"missing {path.relative_to(ROOT)}")
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        findings.add("json_invalid", f"invalid {path.relative_to(ROOT)}: {error}")
        return {}
    if not isinstance(value, dict):
        findings.add("json_shape", f"{path.relative_to(ROOT)} must be an object")
        return {}
    return value


def read(path: Path, findings: Findings) -> str:
    if not path.is_file():
        findings.add("file_missing", f"missing {path.relative_to(ROOT)}")
        return ""
    return path.read_text(encoding="utf-8")


def require_tokens(
    text: str,
    tokens: tuple[str, ...],
    findings: Findings,
    code: str,
    source: str,
) -> None:
    for token in tokens:
        findings.require(token in text, code, f"{source} is missing {token}")


def verify_files(findings: Findings) -> None:
    required = (
        LIB,
        EVAL_ROOT / "src/repository_admission.rs",
        EVAL_ROOT / "src/evidence_sink.rs",
        EVAL_ROOT / "src/attempt_journal.rs",
        EVAL_ROOT / "src/audited_runner.rs",
        EVAL_ROOT / "src/checkpoint_holdout_file.rs",
        MAP,
        STATE,
        STATUS,
        PRODUCTION,
        RECOVERY,
        TARGET_ACCEPTANCE,
        TARGET_SCHEMA,
        API_WORKFLOW,
        LANE_WORKFLOW,
        BOUNDARY_SCRIPT,
        STATUS_SCRIPT,
        COMPILE_FAIL,
    )
    for path in required:
        findings.require(
            path.is_file(),
            "required_file_missing",
            f"missing {path.relative_to(ROOT)}",
        )


def verify_public_surface(findings: Findings) -> None:
    lib = read(LIB, findings)
    require_tokens(
        lib,
        (
            "mod attempt_journal;",
            "mod audited_runner;",
            "mod checkpoint_holdout_file;",
            "mod evidence_sink;",
            "mod repository_admission;",
            "pub(crate) use signed_evaluation::decide_with_signed_evidence_v2;",
            "pub(crate) use longitudinal_time::decide_with_signed_longitudinal_evidence_v3;",
            "pub use audited_runner::AuditedProductEvaluationRunnerV1;",
            "pub use checkpoint_holdout_file::LockedCheckpointFinalHoldoutCasStoreV1;",
            "pub use evidence_sink::ReconcilingQualificationEvidenceSinkV1;",
            "pub use repository_admission::admit_repository_evaluation_v1;",
        ),
        findings,
        "public_surface_missing",
        str(LIB.relative_to(ROOT)),
    )
    for token in (
        "pub use signed_evaluation::decide_with_signed_evidence_v2;",
        "pub use longitudinal_time::decide_with_signed_longitudinal_evidence_v3;",
    ):
        findings.require(
            token not in lib,
            "raw_primitive_public",
            f"raw decision primitive remains public: {token}",
        )

    violations: list[str] = []
    for path in (ROOT / "codex-rs").rglob("*.rs"):
        if path.is_relative_to(EVAL_ROOT):
            continue
        text = path.read_text(encoding="utf-8")
        for symbol in RAW_PRIMITIVES:
            if re.search(rf"\b{re.escape(symbol)}\b", text):
                violations.append(f"{path.relative_to(ROOT)}:{symbol}")
    findings.require(
        not violations,
        "external_raw_decision_reference",
        "external raw decision references remain: " + ", ".join(sorted(violations)),
    )

    fixture = read(COMPILE_FAIL, findings)
    for symbol in RAW_PRIMITIVES:
        findings.require(
            symbol in fixture,
            "compile_fail_fixture_incomplete",
            f"compile-fail fixture does not reference {symbol}",
        )


def verify_components(findings: Findings) -> None:
    checks = {
        EVAL_ROOT / "src/repository_admission.rs": (
            "pub enum RepositoryEvaluationConsumerV1",
            "pub struct RepositoryEvaluationAdmissionV1",
            "pub fn admit_repository_evaluation_v1(",
            "receipt_seal: Digest32",
            "AuthorityPosture::DENY_ALL",
        ),
        EVAL_ROOT / "src/evidence_sink.rs": (
            "pub trait IdempotentQualificationEvidenceSinkV1",
            "fn lookup(",
            "fn persist_once(",
            "pub struct ReconcilingQualificationEvidenceSinkV1",
            "CommitThenIndeterminate",
            "IndeterminateWithoutCommit",
        ),
        EVAL_ROOT / "src/attempt_journal.rs": (
            "pub enum EvaluationAttemptPhaseV1",
            "HoldoutConsumedWithoutTerminalReceipt",
            "HoldoutConsumptionIndeterminate",
            "PublicationIndeterminate",
            "pub trait EvaluationAttemptCasStoreV1",
            "RetryForbidden",
            "commit_before_error",
        ),
        EVAL_ROOT / "src/audited_runner.rs": (
            "pub struct AuditedProductEvaluationRunnerV1",
            "EvaluationAttemptPhaseV1::TemporalEvaluated",
            "EvaluationAttemptPhaseV1::PublicationIndeterminate",
            "ReconcilingQualificationEvidenceSinkV1",
        ),
        EVAL_ROOT / "src/checkpoint_holdout_file.rs": (
            "pub struct LockedCheckpointFinalHoldoutCasStoreV1",
            "pub struct FinalHoldoutCompactionReceiptV1",
            "pub fn compact_into(",
            "truncated_tail",
            "MAX_CHECKPOINTS",
            "maximum_checkpoint_recovery_capacity_profile",
            "CheckpointFileCasErrorV1::Rollback",
        ),
    }
    for path, tokens in checks.items():
        require_tokens(
            read(path, findings),
            tokens,
            findings,
            "component_contract_missing",
            str(path.relative_to(ROOT)),
        )


def verify_callers(findings: Findings) -> None:
    for relative, tokens in EXPECTED_CALLERS.items():
        path = ROOT / relative
        text = read(path, findings)
        require_tokens(
            text,
            tokens,
            findings,
            "caller_surface_missing",
            relative,
        )


def verify_map(findings: Findings) -> None:
    mapping = load_json(MAP, findings)
    findings.require(
        mapping.get("schema") == "hepta.module-implementation-map.v3",
        "map_schema",
        "unexpected implementation-map schema",
    )
    findings.require(
        mapping.get("module") == "learning.eval",
        "map_module",
        "implementation map does not describe learning.eval",
    )
    findings.require(
        mapping.get("productionImplementation") is False,
        "map_production_truth",
        "source map must not self-claim production implementation",
    )
    operations_raw = mapping.get("operations")
    operations = {
        row.get("operation")
        for row in operations_raw
        if isinstance(row, dict) and isinstance(row.get("operation"), str)
    } if isinstance(operations_raw, list) else set()
    findings.require(
        operations == EXPECTED_OPERATIONS,
        "map_operation_closed_world",
        f"operation inventory mismatch: expected {sorted(EXPECTED_OPERATIONS)}, got {sorted(operations)}",
    )
    if isinstance(operations_raw, list):
        for row in operations_raw:
            if not isinstance(row, dict):
                findings.add("map_operation_shape", "operation row must be an object")
                continue
            findings.require(
                row.get("authority") == "deny_all",
                "map_operation_authority",
                f"{row.get('operation')} is not deny_all",
            )
            source = row.get("sourcePath")
            findings.require(
                isinstance(source, str) and (ROOT / source).is_file(),
                "map_operation_source",
                f"missing source for {row.get('operation')}: {source}",
            )

    callers_raw = mapping.get("productCallers")
    caller_paths = {
        row.get("sourcePath")
        for row in callers_raw
        if isinstance(row, dict) and isinstance(row.get("sourcePath"), str)
    } if isinstance(callers_raw, list) else set()
    findings.require(
        caller_paths == set(EXPECTED_CALLERS),
        "map_caller_closed_world",
        f"caller inventory mismatch: expected {sorted(EXPECTED_CALLERS)}, got {sorted(caller_paths)}",
    )

    objects_raw = mapping.get("sourceObjects")
    findings.require(
        isinstance(objects_raw, list) and bool(objects_raw),
        "map_source_objects",
        "implementation map must bind tracked source objects",
    )
    if isinstance(objects_raw, list):
        paths = [row.get("path") for row in objects_raw if isinstance(row, dict)]
        findings.require(
            paths == sorted(paths) and len(paths) == len(set(paths)),
            "map_source_object_order",
            "sourceObjects must be unique and path-sorted",
        )
        for row in objects_raw:
            if not isinstance(row, dict):
                findings.add("map_source_object_shape", "source object must be an object")
                continue
            object_id = row.get("object")
            findings.require(
                isinstance(object_id, str)
                and bool(re.fullmatch(r"[0-9a-f]{40}", object_id)),
                "map_source_object_id",
                f"invalid source object for {row.get('path')}",
            )


def verify_state_and_docs(findings: Findings) -> None:
    state = load_json(STATE, findings)
    findings.require(
        state.get("schema") == "hepta.learning-eval.current-state.v1",
        "state_schema",
        "unexpected current-state schema",
    )
    source_state = state.get("sourceState")
    findings.require(
        isinstance(source_state, dict)
        and source_state.get("productionImplementation") is False,
        "state_production_truth",
        "current state must keep productionImplementation false",
    )
    external = state.get("externalEvidenceGates")
    findings.require(
        isinstance(external, dict)
        and bool(external)
        and not any(external.values()),
        "state_external_truth",
        "repository source must not self-close external evidence gates",
    )
    registered = {
        row.get("path")
        for row in state.get("repositoryConsumers", [])
        if isinstance(row, dict)
    }
    findings.require(
        registered == set(EXPECTED_CALLERS),
        "state_caller_closed_world",
        f"current-state callers mismatch: {sorted(registered)}",
    )

    status = read(STATUS, findings)
    require_tokens(
        status,
        (
            "Generated from `CURRENT_STATE.json`",
            "`rawSignedDecisionPrimitivesCratePrivate` | **implemented**",
            "`productionImplementation` | **open**",
            "`targetHostAuthentication` | **no**",
            "`release` | **no**",
        ),
        findings,
        "generated_status_missing",
        str(STATUS.relative_to(ROOT)),
    )

    production = read(PRODUCTION, findings)
    recovery = read(RECOVERY, findings)
    acceptance = read(TARGET_ACCEPTANCE, findings)
    require_tokens(
        production,
        (
            "AuditedProductEvaluationRunnerV1",
            "admit_repository_evaluation_v1",
            "EvaluationAttemptJournalV1",
            "IdempotentQualificationEvidenceSinkV1",
            "LockedCheckpointFinalHoldoutCasStoreV1",
            "DENY_ALL",
        ),
        findings,
        "production_contract_missing",
        str(PRODUCTION.relative_to(ROOT)),
    )
    require_tokens(
        recovery,
        (
            "HoldoutConsumptionIndeterminate",
            "PublicationIndeterminate",
            "accepted-or-unknown",
            "compaction",
            "retry-forbidden",
        ),
        findings,
        "recovery_contract_missing",
        str(RECOVERY.relative_to(ROOT)),
    )
    require_tokens(
        acceptance,
        (
            "linearizable CAS",
            "real future-calendar windows",
            "independent semantic acceptance",
            "productionImplementation = false",
            "release = false",
        ),
        findings,
        "target_acceptance_missing",
        str(TARGET_ACCEPTANCE.relative_to(ROOT)),
    )

    schema = load_json(TARGET_SCHEMA, findings)
    findings.require(
        schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema",
        "target_schema_draft",
        "target-host schema must use JSON Schema 2020-12",
    )
    required = schema.get("required")
    findings.require(
        isinstance(required, list)
        and {"host", "source", "authority", "namespaces", "independentGates"}
        <= set(required),
        "target_schema_required",
        "target-host schema is missing required acceptance sections",
    )


def verify_workflows(findings: Findings) -> None:
    api = read(API_WORKFLOW, findings)
    lane = read(LANE_WORKFLOW, findings)
    require_tokens(
        api,
        (
            "ref: ${{ env.SOURCE_SHA }}",
            "scripts/hepta-learning-eval-status.py verify",
            "scripts/hepta-learning-eval-api-boundary.py verify",
            "scripts/hepta-learning-eval-api-boundary.py compile-fail",
            "fault-injection.log",
            "maximum_checkpoint_recovery_capacity_profile",
            "checkpoint-capacity.log",
            "resilience.json",
            "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
            "actions/attest-build-provenance@4d101475d8b20a2381f78447822ac1eab6504dd8",
        ),
        findings,
        "api_workflow_missing",
        str(API_WORKFLOW.relative_to(ROOT)),
    )
    require_tokens(
        lane,
        (
            "rust-closure:",
            "synthetic-merge:",
            "learning-eval-qualification:",
            "--fail-under-lines 85",
            "signed_qualification_e2e",
            "evaluated_shadow",
            "scripts/hepta-learning-eval-evidence.py emit",
            "scripts/hepta-learning-eval-evidence.py verify",
        ),
        findings,
        "lane_workflow_missing",
        str(LANE_WORKFLOW.relative_to(ROOT)),
    )


def verify() -> Findings:
    findings = Findings()
    verify_files(findings)
    verify_public_surface(findings)
    verify_components(findings)
    verify_callers(findings)
    verify_map(findings)
    verify_state_and_docs(findings)
    verify_workflows(findings)
    return findings


def self_test() -> Findings:
    findings = Findings()
    findings.require(
        EXPECTED_CALLERS
        == {
            "codex-rs/hepta-agentd/src/intelligence_evaluation.rs": (
                "RepositoryEvaluationConsumerV1::Agentd",
                "admit_repository_evaluation_v1",
            ),
            "codex-rs/hepta-intelligence/src/plasticity_product.rs": (
                "RepositoryEvaluationConsumerV1::Plasticity",
                "admit_repository_evaluation_v1",
            ),
            "codex-rs/hepta-intelligence/src/evaluated_shadow.rs": (
                "ProductQualificationReceiptV1",
                "run_evaluated_shadow_v1",
            ),
        },
        "self_test_callers",
        "caller closed world changed unexpectedly",
    )
    findings.require(
        "decide_with_signed_evidence_v2" in RAW_PRIMITIVES,
        "self_test_raw_v2",
        "raw V2 primitive missing from deny list",
    )
    findings.require(
        "decide_with_signed_longitudinal_evidence_v3" in RAW_PRIMITIVES,
        "self_test_raw_v3",
        "raw V3 primitive missing from deny list",
    )
    return findings


def emit(findings: Findings) -> int:
    payload = {
        "schema": "hepta.learning-eval.source-closure.v1",
        "status": "pass" if not findings.items else "fail",
        "findings": [finding.__dict__ for finding in findings.items],
        "expectedOperations": sorted(EXPECTED_OPERATIONS),
        "expectedCallers": sorted(EXPECTED_CALLERS),
        "externalAuthority": "deny_all",
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if not findings.items else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "self-test"))
    args = parser.parse_args()
    return emit(verify() if args.command == "verify" else self_test())


if __name__ == "__main__":
    sys.exit(main())
