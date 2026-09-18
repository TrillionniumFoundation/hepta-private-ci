#!/usr/bin/env python3
"""Read-only closed-world verifier for the Lane E implementation candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from hepta_workflow_commands import workflow_commands
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json"
TRACE_PATH = ROOT / "qualification/lane-e/TEST_TRACEABILITY.json"
WORKFLOW_PATH = ROOT / ".github/workflows/hepta-lane-e-gap-closure.yml"
PRODUCTION_CONTRACT_PATH = ROOT / "codex-rs/hepta-intelligence-eval/PRODUCTION_CONTRACT.md"
EVIDENCE_ADMISSION_PATH = ROOT / "codex-rs/hepta-intelligence-eval/EVIDENCE_ADMISSION.md"
NATIVE_MAPPING_PATH = ROOT / "codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md"
EVAL_LIB_PATH = ROOT / "codex-rs/hepta-intelligence-eval/src/lib.rs"
EVALUATED_SHADOW_PATH = ROOT / "codex-rs/hepta-intelligence/src/evaluated_shadow.rs"
TEMPORARY_WORKFLOW_PATH = (
    ROOT / ".github/workflows/hepta-lane-e-materialize-generated.yml"
)

EXPECTED_MODULES = {
    "learning.ledger",
    "learning.operator",
    "learning.eval",
    "learning.artifacts",
}
EXPECTED_CASES = {
    *(f"LEDGER-{index:02d}" for index in range(1, 5)),
    *(f"OP-{index:02d}" for index in range(1, 5)),
    *(f"EVAL-{index:02d}" for index in range(1, 5)),
    *(f"ART-{index:02d}" for index in range(1, 5)),
}
EXPECTED_EXTERNAL_GATES = {f"RDY-EXT-{index:03d}" for index in range(1, 10)}
EXPECTED_OPERATIONS = {
    "learning.ledger": {
        "verify_independent_roles",
        "validate_authenticated_outcome",
        "validate_candidate_set_completeness",
        "finalize_credit_batch",
        "freeze_dataset",
        "append_shadow_decision",
    },
    "learning.artifacts": {
        "validate_artifact_manifest_v2",
        "DatasetWithdrawalRegistry::append",
        "validate_registry_head_witness",
        "validate_artifact_lifecycle_transition",
        "load_pinned_candidate",
    },
    "learning.operator": {
        "build_targets",
        "validate_applicability_certificate",
        "build_sensor_core",
        "evaluate_bellman_reference",
        "admit_operator_regularity",
        "fit_transition_model",
        "predict_transition",
    },
    "learning.eval": {
        "estimate_ope",
        "estimate_sequential",
        "freeze_cross_fold_plan_v2",
        "FencedFinalHoldoutJournalV2::consume",
        "decide_with_signed_evidence_v2",
        "decide_with_signed_longitudinal_evidence_v3",
    },
}
EXPECTED_CRATES = {
    "codex-hepta-learning-ledger",
    "codex-hepta-learning-artifacts",
    "codex-hepta-bellman-operator",
    "codex-hepta-intelligence-eval",
    "codex-hepta-shadow-qualification",
}


@dataclass(frozen=True)
class Finding:
    code: str
    message: str


class Findings:
    def __init__(self) -> None:
        self.items: list[Finding] = []

    def add(self, code: str, message: str) -> None:
        self.items.append(Finding(code=code, message=message))

    def require(self, condition: bool, code: str, message: str) -> None:
        if not condition:
            self.add(code, message)


def load_json(path: Path, findings: Findings) -> dict[str, Any]:
    if not path.is_file():
        findings.add(
            "missing_file", f"missing required JSON file: {path.relative_to(ROOT)}"
        )
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        findings.add(
            "invalid_json",
            f"cannot parse {path.relative_to(ROOT)}: {error}",
        )
        return {}
    if not isinstance(value, dict):
        findings.add("invalid_json_root", f"{path.relative_to(ROOT)} must be an object")
        return {}
    return value


def relative_path(value: object, findings: Findings, context: str) -> Path | None:
    if not isinstance(value, str) or not value or value.startswith(("/", "../")):
        findings.add(
            "invalid_path", f"{context} has invalid repository path: {value!r}"
        )
        return None
    path = Path(value)
    if ".." in path.parts:
        findings.add("invalid_path", f"{context} escapes the repository: {value!r}")
        return None
    return ROOT / path


def verify_symbol(source: str, native_symbol: str) -> bool:
    parts = native_symbol.split("::")
    function = parts[-1]
    if not re.search(rf"\b(?:pub\s+)?fn\s+{re.escape(function)}\s*\(", source):
        return False
    if len(parts) >= 2 and parts[-2][:1].isupper():
        owner = parts[-2]
        return bool(
            re.search(rf"\b(?:struct|enum|type)\s+{re.escape(owner)}\b", source)
            and re.search(rf"\bimpl\s+{re.escape(owner)}\b", source)
        )
    return True


def verify_matrix(
    matrix: dict[str, Any], findings: Findings
) -> dict[str, dict[str, Any]]:
    findings.require(
        matrix.get("schema") == "hepta.lane-e-implementation-matrix.v1",
        "matrix_schema",
        "unexpected Lane E matrix schema",
    )
    findings.require(
        matrix.get("authorityDelta") == "none",
        "authority_delta",
        "Lane E candidate must not grant new authority",
    )
    findings.require(
        matrix.get("capabilityClosureState") == "external_evidence_required",
        "capability_truth_boundary",
        "capability closure must remain external-evidence-required",
    )

    modules_raw = matrix.get("modules")
    if not isinstance(modules_raw, list):
        findings.add("matrix_modules", "matrix modules must be an array")
        return {}
    modules: dict[str, dict[str, Any]] = {}
    for item in modules_raw:
        if not isinstance(item, dict) or not isinstance(item.get("module"), str):
            findings.add(
                "matrix_module_record", "matrix contains an invalid module record"
            )
            continue
        module = item["module"]
        if module in modules:
            findings.add("duplicate_module", f"duplicate module in matrix: {module}")
            continue
        modules[module] = item

    findings.require(
        set(modules) == EXPECTED_MODULES,
        "module_closed_world",
        f"matrix modules must be exactly {sorted(EXPECTED_MODULES)}",
    )
    for module, item in modules.items():
        for key in ("sourceRoot", "stableGuide", "dossier", "nativeMapping"):
            path = relative_path(item.get(key), findings, f"{module}.{key}")
            if path is not None:
                findings.require(
                    path.exists(),
                    "missing_matrix_path",
                    f"{module}.{key} does not exist: {path.relative_to(ROOT)}",
                )
        if module == "learning.eval":
            contract_path = relative_path(
                item.get("productionContract"),
                findings,
                "learning.eval.productionContract",
            )
            if contract_path is not None:
                findings.require(
                    contract_path == PRODUCTION_CONTRACT_PATH and contract_path.is_file(),
                    "production_contract_matrix_binding",
                    "learning.eval must bind the canonical production contract",
                )
            findings.require(
                item.get("implementationState") == "source_implemented",
                "learning_eval_source_state",
                "learning.eval source implementation must be recorded separately from CI",
            )
            findings.require(
                item.get("qualificationState")
                == "exact_head_and_synthetic_merge_evidence_required",
                "learning_eval_qualification_state",
                "learning.eval dynamic qualification evidence state is missing",
            )
        findings.require(
            item.get("remainingRepositoryGaps") == [],
            "repository_gap_open",
            f"{module} still lists a repository-controlled gap",
        )
        external = item.get("remainingExternalEvidence")
        findings.require(
            isinstance(external, list) and bool(external),
            "external_evidence_missing",
            f"{module} must truthfully retain applicable external evidence",
        )

        operations_raw = item.get("operations")
        if not isinstance(operations_raw, list):
            findings.add("operations_missing", f"{module} has no operations array")
            continue
        operations: dict[str, dict[str, Any]] = {}
        for operation in operations_raw:
            if not isinstance(operation, dict) or not isinstance(
                operation.get("operation"), str
            ):
                findings.add("invalid_operation", f"{module} has an invalid operation")
                continue
            operations[operation["operation"]] = operation
        findings.require(
            set(operations) == EXPECTED_OPERATIONS[module],
            "operation_closed_world",
            f"{module} operation set differs from the required closed world",
        )
        for operation_name, operation in operations.items():
            source_path = relative_path(
                operation.get("source"), findings, f"{module}.{operation_name}.source"
            )
            symbol = operation.get("nativeSymbol")
            if source_path is None or not source_path.is_file():
                findings.add(
                    "operation_source_missing",
                    f"missing source for {module}.{operation_name}",
                )
                continue
            if not isinstance(symbol, str):
                findings.add(
                    "native_symbol_missing",
                    f"missing native symbol for {module}.{operation_name}",
                )
                continue
            source = source_path.read_text(encoding="utf-8")
            findings.require(
                verify_symbol(source, symbol),
                "native_symbol_unresolved",
                f"cannot resolve {symbol} in {source_path.relative_to(ROOT)}",
            )
            findings.require(
                operation.get("status") in {"implemented", "implemented_existing"},
                "operation_not_implemented",
                f"{module}.{operation_name} is not source-implemented",
            )

    external_raw = matrix.get("externalGates")
    external: dict[str, dict[str, Any]] = {}
    if isinstance(external_raw, list):
        for item in external_raw:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                external[item["id"]] = item
    findings.require(
        set(external) == EXPECTED_EXTERNAL_GATES,
        "external_gate_closed_world",
        "external gate set must contain RDY-EXT-001 through RDY-EXT-009 exactly",
    )
    for gate_id, item in external.items():
        findings.require(
            item.get("repositoryMaySelfCertify") is False,
            "external_gate_self_certified",
            f"{gate_id} may not be self-certified by repository source",
        )
        state = item.get("state")
        findings.require(
            isinstance(state, str)
            and ("open" in state or "required" in state)
            and "closed" not in state,
            "external_gate_false_closure",
            f"{gate_id} must remain open or evidence-required: {state!r}",
        )

    cross = matrix.get("crossCrateQualification")
    if not isinstance(cross, dict):
        findings.add(
            "cross_crate_missing", "cross-crate qualification record is missing"
        )
    else:
        path = relative_path(
            cross.get("source"), findings, "crossCrateQualification.source"
        )
        test = cross.get("test")
        if path is not None and path.is_file() and isinstance(test, str):
            text = path.read_text(encoding="utf-8")
            findings.require(
                bool(re.search(rf"\bfn\s+{re.escape(test)}\s*\(", text)),
                "cross_crate_test_missing",
                f"cross-crate test function is missing: {test}",
            )
        else:
            findings.add("cross_crate_source", "cross-crate test source is missing")
    return modules


def verify_traceability(
    trace: dict[str, Any], modules: dict[str, dict[str, Any]], findings: Findings
) -> None:
    findings.require(
        trace.get("schema") == "hepta.lane-e-test-traceability.v1",
        "trace_schema",
        "unexpected Lane E traceability schema",
    )
    cases_raw = trace.get("cases")
    if not isinstance(cases_raw, list):
        findings.add("trace_cases", "traceability cases must be an array")
        return
    cases: dict[str, dict[str, Any]] = {}
    for item in cases_raw:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            findings.add("invalid_case", "traceability contains an invalid case")
            continue
        case_id = item["id"]
        if case_id in cases:
            findings.add("duplicate_case", f"duplicate case: {case_id}")
            continue
        cases[case_id] = item
    findings.require(
        set(cases) == EXPECTED_CASES,
        "case_closed_world",
        f"traceability cases must be exactly {sorted(EXPECTED_CASES)}",
    )

    source_cache: dict[Path, str] = {}
    dossier_cache: dict[Path, str] = {}
    for case_id, case in cases.items():
        module = case.get("module")
        findings.require(
            module in EXPECTED_MODULES,
            "case_module",
            f"{case_id} has invalid module {module!r}",
        )
        if module in modules:
            dossier = relative_path(
                modules[module].get("dossier"), findings, f"{case_id}.dossier"
            )
            if dossier is not None and dossier.is_file():
                dossier_text = dossier_cache.setdefault(
                    dossier, dossier.read_text(encoding="utf-8")
                )
                findings.require(
                    case_id in dossier_text,
                    "dossier_case_missing",
                    f"{case_id} is absent from {dossier.relative_to(ROOT)}",
                )
        tests = case.get("tests")
        if not isinstance(tests, list) or not tests:
            findings.add("case_tests_missing", f"{case_id} has no mapped native tests")
            continue
        for index, test in enumerate(tests):
            context = f"{case_id}.tests[{index}]"
            if not isinstance(test, dict):
                findings.add("invalid_test_mapping", f"{context} is not an object")
                continue
            source_path = relative_path(
                test.get("source"), findings, f"{context}.source"
            )
            function = test.get("function")
            if source_path is None or not source_path.is_file():
                findings.add("test_source_missing", f"{context} source is missing")
                continue
            if not isinstance(function, str):
                findings.add("test_function_missing", f"{context} function is missing")
                continue
            source_text = source_cache.setdefault(
                source_path, source_path.read_text(encoding="utf-8")
            )
            findings.require(
                bool(re.search(rf"\bfn\s+{re.escape(function)}\s*\(", source_text)),
                "test_function_unresolved",
                f"{function} is absent from {source_path.relative_to(ROOT)}",
            )
        findings.require(
            case.get("status") == "native_test_mapped",
            "case_status",
            f"{case_id} is not marked native_test_mapped",
        )

    cross_raw = trace.get("crossCrateCases")
    findings.require(
        isinstance(cross_raw, list) and len(cross_raw) == 1,
        "cross_case_count",
        "exactly one Lane E cross-crate case is required",
    )
    if isinstance(cross_raw, list):
        for item in cross_raw:
            if not isinstance(item, dict):
                findings.add("invalid_cross_case", "invalid cross-crate case")
                continue
            source_path = relative_path(
                item.get("source"), findings, "crossCase.source"
            )
            function = item.get("function")
            if (
                source_path is not None
                and source_path.is_file()
                and isinstance(function, str)
            ):
                text = source_path.read_text(encoding="utf-8")
                findings.require(
                    bool(re.search(rf"\bfn\s+{re.escape(function)}\s*\(", text)),
                    "cross_case_unresolved",
                    f"cross-crate function is missing: {function}",
                )

    # Product-boundary tests are tracked separately from the Lane E causal
    # chain: they exercise a real non-Rust consumer and an injected fault.
    # Keeping this as an explicit trace prevents a passing unit test from being
    # mistaken for cross-language product evidence.
    boundary_raw = trace.get("productBoundaryCases")
    findings.require(
        isinstance(boundary_raw, list) and len(boundary_raw) == 1,
        "product_boundary_case_count",
        "exactly one product-boundary case is required",
    )
    if isinstance(boundary_raw, list):
        for item in boundary_raw:
            if not isinstance(item, dict):
                findings.add("invalid_boundary_case", "invalid product-boundary case")
                continue
            source_path = relative_path(
                item.get("source"), findings, "productBoundaryCase.source"
            )
            function = item.get("function")
            if source_path is None or not source_path.is_file():
                findings.add(
                    "boundary_source_missing", "product-boundary source is missing"
                )
                continue
            findings.require(
                isinstance(function, str),
                "boundary_function_missing",
                "product-boundary function is missing",
            )
            if isinstance(function, str):
                text = source_path.read_text(encoding="utf-8")
                findings.require(
                    bool(re.search(rf"\bfn\s+{re.escape(function)}\s*\(", text)),
                    "boundary_function_unresolved",
                    f"product-boundary function is missing: {function}",
                )


def verify_authority_posture(findings: Findings) -> None:
    sources = [
        ROOT / "codex-rs/hepta-learning-ledger/src/causal_v2.rs",
        ROOT / "codex-rs/hepta-learning-artifacts/src/closure_v2.rs",
        ROOT / "codex-rs/hepta-bellman-operator/src/reference.rs",
        ROOT / "codex-rs/hepta-bellman-operator/src/world_model.rs",
        ROOT / "codex-rs/hepta-intelligence-eval/src/closure.rs",
    ]
    for path in sources:
        if not path.is_file():
            findings.add(
                "authority_source_missing", f"missing {path.relative_to(ROOT)}"
            )
            continue
        text = path.read_text(encoding="utf-8")
        findings.require(
            "AuthorityPosture::DENY_ALL" in text,
            "deny_all_missing",
            f"{path.relative_to(ROOT)} does not explicitly emit DENY_ALL authority",
        )


def verify_production_contract(findings: Findings) -> None:
    for path in (
        PRODUCTION_CONTRACT_PATH,
        EVIDENCE_ADMISSION_PATH,
        NATIVE_MAPPING_PATH,
        EVAL_LIB_PATH,
        EVALUATED_SHADOW_PATH,
    ):
        findings.require(
            path.is_file(),
            "production_contract_path_missing",
            f"missing production-boundary source: {path.relative_to(ROOT)}",
        )
    if not all(
        path.is_file()
        for path in (
            PRODUCTION_CONTRACT_PATH,
            EVIDENCE_ADMISSION_PATH,
            NATIVE_MAPPING_PATH,
            EVAL_LIB_PATH,
            EVALUATED_SHADOW_PATH,
        )
    ):
        return

    contract = PRODUCTION_CONTRACT_PATH.read_text(encoding="utf-8")
    for token in (
        "Trusted-only / legacy",
        "Production-required",
        "decide_with_signed_evidence_v2",
        "decide_with_signed_longitudinal_evidence_v3",
        "FencedFinalHoldoutJournalV2",
        "transactional compare-and-swap authority",
        "AuthorityPosture::DENY_ALL",
    ):
        findings.require(
            token in contract,
            "production_contract_incomplete",
            f"production contract is missing required token: {token}",
        )

    lib = EVAL_LIB_PATH.read_text(encoding="utf-8")
    findings.require(
        not re.search(r"\bpub\s+fn\s+evaluate\s*\(", lib),
        "legacy_default_public_api",
        "weak evaluate() must not be a default public function",
    )
    findings.require(
        'feature = "legacy-inprocess-eval"' in lib
        and "evaluate_legacy_inprocess_v1" in lib,
        "legacy_feature_boundary_missing",
        "legacy evaluator must be explicit and feature-gated",
    )

    evaluated_shadow = EVALUATED_SHADOW_PATH.read_text(encoding="utf-8")
    findings.require(
        "decide_with_signed_evidence_v2" in evaluated_shadow,
        "signed_ingress_missing",
        "evaluated shadow must admit external evaluation through signed V2",
    )

    allowed_direct_roots = (
        ROOT / "codex-rs/hepta-intelligence-eval",
        ROOT / "codex-rs/hepta-shadow-qualification",
    )
    direct_pattern = re.compile(r"\bdecide_independently(?:_v2)?\s*\(")
    for rust_path in (ROOT / "codex-rs").rglob("*.rs"):
        if any(root == rust_path or root in rust_path.parents for root in allowed_direct_roots):
            continue
        try:
            text = rust_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if direct_pattern.search(text):
            findings.add(
                "unsigned_production_ingress",
                "direct structural evaluator call outside trusted/qualification roots: "
                + str(rust_path.relative_to(ROOT)),
            )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def qualification_input_digest() -> str:
    paths = [
        PRODUCTION_CONTRACT_PATH,
        EVIDENCE_ADMISSION_PATH,
        NATIVE_MAPPING_PATH,
        MATRIX_PATH,
        TRACE_PATH,
        WORKFLOW_PATH,
        Path(__file__).resolve(),
    ]
    eval_root = ROOT / "codex-rs/hepta-intelligence-eval"
    paths.extend(
        path
        for path in eval_root.rglob("*")
        if path.is_file()
        and path.suffix in {".rs", ".toml", ".md"}
    )
    digest = hashlib.sha256()
    for path in sorted(set(paths), key=lambda value: str(value.relative_to(ROOT))):
        relative = str(path.relative_to(ROOT)).encode("utf-8")
        raw = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def git_value(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()


def write_receipt(kind: str, expected_sha: str, output: Path) -> None:
    if kind not in {"source-head", "synthetic-merge"}:
        raise ValueError(f"unsupported receipt kind: {kind}")
    actual_sha = git_value("rev-parse", "HEAD")
    if actual_sha != expected_sha:
        raise ValueError(f"expected {expected_sha}, got {actual_sha}")
    tree_sha = git_value("rev-parse", "HEAD^{tree}")
    issued = int(time.time())
    identity = {
        "repository": os.environ.get("GITHUB_REPOSITORY", ""),
        "workflowRef": os.environ.get("GITHUB_WORKFLOW_REF", ""),
        "workflow": os.environ.get("GITHUB_WORKFLOW", ""),
        "runId": os.environ.get("GITHUB_RUN_ID", ""),
        "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
        "actor": os.environ.get("GITHUB_ACTOR", ""),
        "serverUrl": os.environ.get("GITHUB_SERVER_URL", ""),
    }
    identity_bytes = json.dumps(
        identity, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    receipt = {
        "schema": "hepta.lane-e-qualification-receipt.v1",
        "schemaVersion": 1,
        "kind": kind,
        "commitSha": actual_sha,
        "treeSha": tree_sha,
        "sourceSha": os.environ.get("SOURCE_SHA", actual_sha),
        "baseSha": os.environ.get("BASE_SHA", ""),
        "mergeCommitSha": os.environ.get("MERGE_COMMIT", "")
        if kind == "synthetic-merge"
        else "",
        "mergeTreeSha": os.environ.get("MERGE_TREE", "")
        if kind == "synthetic-merge"
        else "",
        "issuedAtUnix": issued,
        "expiresAtUnix": issued + 90 * 24 * 60 * 60,
        "attesterIdentity": identity,
        "attesterIdentityDigest": hashlib.sha256(identity_bytes).hexdigest(),
        "signatureProfile": "github_actions_workflow_identity_not_cryptographic_signature",
        "productionContractSha256": sha256_file(PRODUCTION_CONTRACT_PATH),
        "evidenceAdmissionSha256": sha256_file(EVIDENCE_ADMISSION_PATH),
        "nativeMappingSha256": sha256_file(NATIVE_MAPPING_PATH),
        "traceabilitySha256": sha256_file(TRACE_PATH),
        "implementationMatrixSha256": sha256_file(MATRIX_PATH),
        "qualificationInputSha256": qualification_input_digest(),
        "coverageArtifactSha256": (
            sha256_file(ROOT / ".hepta-evidence/learning-eval-source.lcov")
            if (ROOT / ".hepta-evidence/learning-eval-source.lcov").is_file()
            else ""
        ),
        "evidenceProfile": [
            "locked_all_target_compilation",
            "owner_regression_tests",
            "signed_evaluated_shadow_end_to_end",
            "durable_holdout_reopen_replay_stress",
            "cross_crate_causal_chain",
            "cross_language_wire_fault",
            "strict_clippy_rustfmt_clean_tree",
        ],
        "claims": {
            "repositorySourceClosureEvidence": True,
            "independentAcceptance": False,
            "longitudinalEfficacy": False,
            "promotionOrReleaseAuthority": False,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def verify_receipt(kind: str, expected_sha: str, input_path: Path) -> None:
    value = json.loads(input_path.read_text(encoding="utf-8"))
    if value.get("schema") != "hepta.lane-e-qualification-receipt.v1":
        raise ValueError("unexpected receipt schema")
    if value.get("kind") != kind:
        raise ValueError("receipt kind mismatch")
    if value.get("commitSha") != expected_sha:
        raise ValueError("receipt commit mismatch")
    if value.get("treeSha") != git_value("rev-parse", "HEAD^{tree}"):
        raise ValueError("receipt tree mismatch")
    expected = {
        "productionContractSha256": sha256_file(PRODUCTION_CONTRACT_PATH),
        "evidenceAdmissionSha256": sha256_file(EVIDENCE_ADMISSION_PATH),
        "nativeMappingSha256": sha256_file(NATIVE_MAPPING_PATH),
        "traceabilitySha256": sha256_file(TRACE_PATH),
        "implementationMatrixSha256": sha256_file(MATRIX_PATH),
        "qualificationInputSha256": qualification_input_digest(),
    }
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            raise ValueError(f"receipt {key} mismatch")
    claims = value.get("claims")
    if not isinstance(claims, dict) or claims.get("repositorySourceClosureEvidence") is not True:
        raise ValueError("source-closure claim missing")
    for key in (
        "independentAcceptance",
        "longitudinalEfficacy",
        "promotionOrReleaseAuthority",
    ):
        if claims.get(key) is not False:
            raise ValueError(f"receipt overclaims {key}")


def verify_workflow(findings: Findings) -> None:
    findings.require(
        WORKFLOW_PATH.is_file(),
        "workflow_missing",
        "Lane E exact-head workflow is missing",
    )
    if not WORKFLOW_PATH.is_file():
        return
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    commands = workflow_commands(text)
    test_commands = [
        command
        for command in commands
        if command[:2] in (["cargo", "test"], ["just", "test"])
        and "--locked" in command
    ]
    for crate in EXPECTED_CRATES:
        findings.require(
            any(
                any(
                    command[index : index + 2] in (["-p", crate], ["--package", crate])
                    for index in range(len(command) - 1)
                )
                for command in test_commands
            ),
            "workflow_crate_missing",
            f"workflow does not execute locked tests for {crate}",
        )
    for subcommand in ("check", "clippy"):
        findings.require(
            any(
                command[:2] == ["cargo", subcommand] and "--locked" in command
                for command in commands
            ),
            "workflow_gate_missing",
            f"workflow is missing cargo {subcommand} --locked",
        )
    findings.require(
        any(command[:2] == ["cargo", "fmt"] for command in commands),
        "workflow_gate_missing",
        "workflow is missing cargo fmt",
    )
    findings.require(
        any(
            command[:3] == ["python3", "scripts/hepta-lane-e-closure.py", "verify"]
            for command in commands
        ),
        "workflow_gate_missing",
        "workflow is missing source closure verification",
    )
    findings.require(
        any(
            "lane_e_causal_candidate_chain_is_digest_bound_and_deny_all" in command
            and any(
                command[index : index + 2] == ["-p", "codex-hepta-shadow-qualification"]
                for index in range(len(command) - 1)
            )
            for command in test_commands
        ),
        "workflow_gate_missing",
        "workflow is missing the cross-crate causal regression",
    )
    findings.require(
        any(
            "cross_language_wire_fault" in command
            and any(
                command[index : index + 2] == ["-p", "codex-hepta-shadow-qualification"]
                for index in range(len(command) - 1)
            )
            for command in test_commands
        ),
        "workflow_gate_missing",
        "workflow is missing the cross-language payload-fault regression",
    )
    findings.require(
        bool(re.search(r"^  synthetic-merge:\s*$", text, re.MULTILINE)),
        "workflow_gate_missing",
        "workflow is missing synthetic-merge job",
    )
    findings.require(
        "cargo llvm-cov" in text,
        "workflow_gate_missing",
        "workflow is missing learning.eval coverage evidence",
    )
    findings.require(
        "durable_holdout_reopen_replay_stress" in text,
        "workflow_gate_missing",
        "workflow is missing durable holdout stress audit",
    )
    findings.require(
        "evaluated_shadow" in text and "-p codex-hepta-intelligence" in text,
        "workflow_gate_missing",
        "workflow is missing signed evaluated-shadow end-to-end tests",
    )
    findings.require(
        "hepta-lane-e-qualification-" in text
        and "actions/upload-artifact@" in text
        and "receipt --kind source-head" in text
        and "receipt --kind synthetic-merge" in text,
        "workflow_gate_missing",
        "workflow must retain exact-source and synthetic-merge qualification receipts",
    )
    findings.require(
        not TEMPORARY_WORKFLOW_PATH.exists(),
        "temporary_workflow_present",
        "temporary generated-file materializer must not remain in the candidate",
    )


def run_self_test() -> list[Finding]:
    findings = Findings()
    findings.require(
        verify_symbol(
            "pub struct Demo; impl Demo { pub fn execute(&self) {} }",
            "crate::Demo::execute",
        ),
        "self_test_method",
        "method symbol resolver failed",
    )
    findings.require(
        verify_symbol("pub fn execute() {}", "crate::execute"),
        "self_test_function",
        "free-function symbol resolver failed",
    )
    findings.require(
        not verify_symbol("pub fn another() {}", "crate::execute"),
        "self_test_false_positive",
        "symbol resolver accepted a missing function",
    )
    return findings.items


def verify() -> Findings:
    findings = Findings()
    matrix = load_json(MATRIX_PATH, findings)
    trace = load_json(TRACE_PATH, findings)
    modules = verify_matrix(matrix, findings)
    verify_traceability(trace, modules, findings)
    verify_authority_posture(findings)
    verify_production_contract(findings)
    verify_workflow(findings)
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("verify", "self-test", "receipt", "receipt-verify"),
        nargs="?",
        default="verify",
    )
    parser.add_argument("--kind", choices=("source-head", "synthetic-merge"))
    parser.add_argument("--expected-sha")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--input", type=Path)
    args = parser.parse_args()
    if args.command in {"receipt", "receipt-verify"}:
        if not args.kind or not args.expected_sha:
            parser.error("--kind and --expected-sha are required for receipt commands")
        if args.command == "receipt":
            if args.output is None:
                parser.error("--output is required for receipt")
            write_receipt(args.kind, args.expected_sha, args.output)
        else:
            if args.input is None:
                parser.error("--input is required for receipt-verify")
            verify_receipt(args.kind, args.expected_sha, args.input)
        print(
            json.dumps(
                {
                    "schema": "hepta.lane-e-receipt-command.v1",
                    "command": args.command,
                    "kind": args.kind,
                    "expectedSha": args.expected_sha,
                    "ok": True,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "self-test":
        findings = run_self_test()
    else:
        findings = verify().items
    output = {
        "schema": "hepta.lane-e-closure-verification.v1",
        "command": args.command,
        "ok": not findings,
        "findingCount": len(findings),
        "findings": [finding.__dict__ for finding in findings],
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
