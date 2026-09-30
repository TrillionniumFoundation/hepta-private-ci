#!/usr/bin/env python3
"""Validate AuthBus qualification contracts and emit exact-candidate projections.

The committed implementation map is intentionally commit-neutral: embedding the
hash of the commit that contains the file would be self-referential. This tool
binds the checked-out immutable tree, documentation, product-callers and crash
matrix to one exact candidate without modifying tracked files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "docs/modules/auth.authbus/IMPLEMENTATION_MAP.json"
CURRENT_IMPLEMENTATION = (
    ROOT / "docs/lane-a-foundation/auth.authbus/CURRENT_IMPLEMENTATION.md"
)
CRASH_MATRIX = ROOT / "docs/modules/auth.authbus/CRASH_CONSISTENCY_MATRIX.json"
PRODUCT_CONTRACT = ROOT / "docs/modules/auth.authbus/PRODUCT_CALLER_CONTRACT.json"
ACTIVATION = ROOT / "docs/modules/auth.authbus/ACTIVATION_DECISION.md"
SECURITY_REVIEW = ROOT / "docs/modules/auth.authbus/SECURITY_REVIEW.md"
VERIFICATION_MATRIX = ROOT / "docs/modules/auth.authbus/VERIFICATION_MATRIX.md"
SLO = ROOT / "docs/modules/auth.authbus/SLO.md"
PERFORMANCE_CONTRACT = ROOT / "docs/modules/auth.authbus/PERFORMANCE_QUALIFICATION.json"
PRODUCTION_ACCEPTANCE_CONTRACT = ROOT / "docs/modules/auth.authbus/PRODUCTION_ACCEPTANCE.json"

REQUIRED_FAULTS = {
    "sqlite-before-commit-sigkill",
    "sqlite-after-commit-sigkill",
    "checkpoint-temp-written-sigkill",
    "checkpoint-file-fsync-failure",
    "checkpoint-rename-failure",
    "checkpoint-directory-fsync-failure",
    "disk-full",
    "checkpoint-content-corruption",
    "checkpoint-generation-regression",
    "active-mutation-leftover",
    "wal-corruption",
    "owner-lease-missing-or-replaced",
    "paused-owner-second-owner",
    "trusted-time-rollback",
    "backup-concurrent-with-mutation",
    "restore-old-database-with-new-checkpoint",
    "trust-material-generation-mismatch",
}

DOCS = [
    MAP_PATH,
    CURRENT_IMPLEMENTATION,
    CRASH_MATRIX,
    PRODUCT_CONTRACT,
    ACTIVATION,
    SECURITY_REVIEW,
    VERIFICATION_MATRIX,
    SLO,
    PERFORMANCE_CONTRACT,
    PRODUCTION_ACCEPTANCE_CONTRACT,
]


def run(*args: str) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def load_json(path: Path) -> dict[str, Any]:
    def unique(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"{path}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected an object")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def aggregate(entries: list[tuple[str, str]]) -> str:
    digest = hashlib.sha256()
    for name, value in sorted(entries):
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(value.encode())
        digest.update(b"\n")
    return digest.hexdigest()


def ensure_clean() -> None:
    for args in (("git", "diff", "--quiet"), ("git", "diff", "--cached", "--quiet")):
        if subprocess.call(args, cwd=ROOT) != 0:
            raise SystemExit("tracked worktree is not clean")


def existing(path_text: str, label: str) -> Path:
    path = ROOT / path_text
    if not path.exists():
        raise ValueError(f"{label}: missing path {path_text}")
    return path


def validate_map(mapping: dict[str, Any]) -> None:
    if mapping.get("schema") != "hepta.module-implementation-map.v4":
        raise ValueError("implementation map must use schema v4")
    if mapping.get("module") != "auth.authbus":
        raise ValueError("implementation map names the wrong module")
    identity = mapping.get("sourceIdentity")
    if not isinstance(identity, dict) or identity.get("mode") != "runtime_exact_head":
        raise ValueError("implementation map must require runtime exact-head binding")
    if identity.get("committedIdentity") is not None:
        raise ValueError("committed implementation map must not contain a stale SHA anchor")
    if mapping.get("productionImplementation") is not False:
        raise ValueError("source map must not claim production implementation")
    if mapping.get("activation") is not False or mapping.get("release") is not False:
        raise ValueError("source map must not claim activation or release")

    operations = mapping.get("operations")
    if not isinstance(operations, list) or len(operations) < 21:
        raise ValueError("implementation map is missing AuthBus operations")
    operation_names: set[str] = set()
    for index, row in enumerate(operations):
        if not isinstance(row, dict):
            raise ValueError(f"operation {index} is not an object")
        name = row.get("operation")
        if not isinstance(name, str) or not name or name in operation_names:
            raise ValueError(f"invalid or duplicate operation at index {index}")
        operation_names.add(name)
        existing(str(row.get("sourcePath")), f"operation {name}")
        tests = row.get("tests", [])
        if not isinstance(tests, list):
            raise ValueError(f"operation {name}: tests must be a list")
        for test_path in tests:
            if isinstance(test_path, str) and not test_path.startswith("/opt/"):
                existing(test_path, f"operation {name} test")

    for root in mapping.get("observedSourcePaths", []):
        existing(str(root), "observed source")
    for binding in mapping.get("productionWriterBindings", []):
        path = existing(str(binding["sourcePath"]), "writer binding")
        token = str(binding["mustContain"])
        if token not in path.read_text(encoding="utf-8"):
            raise ValueError(f"{path}: missing writer binding token {token!r}")


def validate_product_contract(mapping: dict[str, Any]) -> dict[str, Any]:
    contract = load_json(PRODUCT_CONTRACT)
    if contract.get("schema") != "hepta.authbus.product-caller-contract.v2":
        raise ValueError("product caller contract schema mismatch")
    callers = contract.get("callers")
    if not isinstance(callers, list) or not callers:
        raise ValueError("product caller contract has no callers")
    observed: list[dict[str, Any]] = []
    for caller in callers:
        if not isinstance(caller, dict):
            raise ValueError("product caller row is not an object")
        name = str(caller.get("name"))
        path = existing(str(caller.get("sourcePath")), f"caller {name}")
        text = path.read_text(encoding="utf-8")
        missing = [token for token in caller.get("requiredTokens", []) if token not in text]
        forbidden = [token for token in caller.get("forbiddenTokens", []) if token in text]
        if missing:
            raise ValueError(f"caller {name} missing required tokens: {missing}")
        if forbidden:
            raise ValueError(f"caller {name} contains forbidden tokens: {forbidden}")
        for test_path in caller.get("testPaths", []):
            existing(str(test_path), f"caller {name} test")
        contracts = caller.get("contracts")
        required_contracts = {
            "noBypass",
            "canonicalDigest",
            "authorityIdentity",
            "ambiguousOutcome",
            "terminalCleanup",
            "recoveryOwner",
            "unavailableBehavior",
            "correlation",
        }
        if not isinstance(contracts, dict) or set(contracts) != required_contracts:
            raise ValueError(f"caller {name} contract fields are incomplete")
        observed.append(
            {
                "name": name,
                "sourcePath": path.relative_to(ROOT).as_posix(),
                "sourceSha256": sha256(path),
                "testPaths": caller.get("testPaths", []),
                "contracts": contracts,
            }
        )

    mapped_names = {
        str(row.get("name")) for row in mapping.get("productCallers", []) if isinstance(row, dict)
    }
    contract_names = {row["name"] for row in observed}
    if mapped_names != contract_names:
        raise ValueError(
            f"product callers drift between map and contract: map={mapped_names}, contract={contract_names}"
        )
    return {"schema": contract["schema"], "callers": observed}


def validate_crash_matrix() -> dict[str, Any]:
    matrix = load_json(CRASH_MATRIX)
    if matrix.get("schema") != "hepta.authbus.crash-consistency-matrix.v2":
        raise ValueError("crash consistency matrix schema mismatch")
    scenarios = matrix.get("scenarios")
    if not isinstance(scenarios, list):
        raise ValueError("crash consistency scenarios must be a list")
    by_id: dict[str, dict[str, Any]] = {}
    required_fields = {
        "id",
        "faultClass",
        "boundary",
        "commitState",
        "retryRule",
        "startupDetection",
        "recoveryAction",
        "readService",
        "evidenceTier",
        "evidence",
    }
    for row in scenarios:
        if not isinstance(row, dict) or set(row) != required_fields:
            raise ValueError("crash scenario fields are incomplete or unexpected")
        scenario_id = str(row["id"])
        if scenario_id in by_id:
            raise ValueError(f"duplicate crash scenario {scenario_id}")
        evidence = row["evidence"]
        if not isinstance(evidence, list) or not evidence:
            raise ValueError(f"crash scenario {scenario_id} has no evidence binding")
        for evidence_path in evidence:
            if isinstance(evidence_path, str) and not evidence_path.startswith("/opt/"):
                existing(evidence_path, f"crash scenario {scenario_id}")
        by_id[scenario_id] = row
    if set(by_id) != REQUIRED_FAULTS:
        missing = sorted(REQUIRED_FAULTS - set(by_id))
        extra = sorted(set(by_id) - REQUIRED_FAULTS)
        raise ValueError(f"crash matrix drift: missing={missing}, extra={extra}")
    return {
        "schema": matrix["schema"],
        "scenarioCount": len(by_id),
        "scenarioIds": sorted(by_id),
        "matrixSha256": sha256(CRASH_MATRIX),
    }


def validate_performance_contract() -> dict[str, Any]:
    contract = load_json(PERFORMANCE_CONTRACT)
    if contract.get("schema") != "hepta.authbus.performance-contract.v1":
        raise ValueError("performance qualification contract schema mismatch")
    stages = contract.get("requiredStages")
    required_stages = {
        "signatureVerification",
        "authorityValidation",
        "mutationGateWait",
        "sqliteTransaction",
        "frontierUpdate",
        "checkpointPublication",
        "reconciliation",
        "productAcknowledgement",
        "endToEnd",
    }
    if not isinstance(stages, list) or set(stages) != required_stages:
        raise ValueError("performance contract stage set is incomplete")
    cases = contract.get("caseContracts")
    if not isinstance(cases, list):
        raise ValueError("performance contract has no case matrix")
    ids = {
        str(row.get("id"))
        for row in cases
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    required_ids = set(contract.get("requiredCaseIds", []))
    if ids != required_ids or len(ids) < 16:
        raise ValueError("performance contract required-case matrix drift")
    if contract.get("minimumSamplesPerCase", 0) < 200:
        raise ValueError("performance contract minimum sample count is too small")
    return {
        "schema": contract["schema"],
        "caseCount": len(ids),
        "requiredStages": sorted(required_stages),
        "contractSha256": sha256(PERFORMANCE_CONTRACT),
    }


def validate_production_acceptance_contract() -> dict[str, Any]:
    contract = load_json(PRODUCTION_ACCEPTANCE_CONTRACT)
    if contract.get("schema") != "hepta.authbus.production-acceptance-contract.v1":
        raise ValueError("production acceptance contract schema mismatch")
    if contract.get("module") != "auth.authbus":
        raise ValueError("production acceptance contract names the wrong module")
    if contract.get("sourceActivation") is not False:
        raise ValueError("source production acceptance must remain fail-closed")
    evidence = contract.get("requiredEvidence")
    if not isinstance(evidence, list):
        raise ValueError("production acceptance evidence list is missing")
    names = {
        str(row.get("name"))
        for row in evidence
        if isinstance(row, dict) and isinstance(row.get("name"), str)
    }
    required_names = {
        "exactHead",
        "syntheticMerge",
        "targetHost",
        "performance",
        "kmsHsm",
        "keyRotationRevocation",
        "backupRestore",
        "dualOwnerMount",
        "activationPlan",
        "rollbackPlan",
    }
    if names != required_names:
        raise ValueError("production acceptance evidence set is incomplete")
    signature = contract.get("signaturePolicy")
    if (
        not isinstance(signature, dict)
        or signature.get("algorithm") != "ed25519"
        or signature.get("principalsMustDiffer") is not True
    ):
        raise ValueError("production acceptance signature policy is not fail-closed")
    activation = contract.get("activationSemantics")
    if (
        not isinstance(activation, dict)
        or activation.get("verifiedOutput") != "approved_for_canary"
        or activation.get("productionActivated") is not False
        or activation.get("release") is not False
    ):
        raise ValueError("production acceptance activation semantics are unsafe")
    return {
        "schema": contract["schema"],
        "requiredEvidence": sorted(required_names),
        "contractSha256": sha256(PRODUCTION_ACCEPTANCE_CONTRACT),
        "sourceActivation": False,
    }


def candidate_identity(kind: str, expected_commit: str | None) -> dict[str, Any]:
    commit = run("git", "rev-parse", "HEAD")
    tree = run("git", "rev-parse", "HEAD^{tree}")
    parents = run("git", "show", "-s", "--format=%P", "HEAD").split()
    if expected_commit and commit != expected_commit:
        raise ValueError(f"checked-out commit {commit} does not match expected {expected_commit}")
    if kind == "exact_head" and len(parents) > 1:
        raise ValueError("exact-head projection unexpectedly names a merge commit")
    if kind == "synthetic_merge" and len(parents) != 2:
        raise ValueError("synthetic-merge projection must have exactly two parents")
    return {"kind": kind, "commit": commit, "tree": tree, "parents": parents}


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--candidate-kind",
        required=True,
        choices=("exact_head", "synthetic_merge", "main_head"),
    )
    parser.add_argument("--expected-commit")
    args = parser.parse_args()

    ensure_clean()
    for document in DOCS:
        if not document.is_file():
            raise SystemExit(f"required AuthBus document is missing: {document.relative_to(ROOT)}")

    try:
        mapping = load_json(MAP_PATH)
        validate_map(mapping)
        product = validate_product_contract(mapping)
        crash = validate_crash_matrix()
        performance = validate_performance_contract()
        production_acceptance = validate_production_acceptance_contract()
        candidate = candidate_identity(args.candidate_kind, args.expected_commit)
    except (KeyError, TypeError, ValueError) as error:
        raise SystemExit(f"AuthBus evidence projection failed: {error}") from error

    document_entries = [
        (path.relative_to(ROOT).as_posix(), sha256(path)) for path in DOCS
    ]
    source_entries: list[tuple[str, str]] = []
    for root_text in mapping["observedSourcePaths"]:
        root = ROOT / root_text
        paths = [root] if root.is_file() else sorted(
            path for path in root.rglob("*") if path.is_file() and "target" not in path.parts
        )
        for path in paths:
            source_entries.append((path.relative_to(ROOT).as_posix(), sha256(path)))

    bound_map = deepcopy(mapping)
    bound_map["sourceIdentity"] = {
        "mode": "exact_candidate",
        **candidate,
        "workflowRunId": os.environ.get("GITHUB_RUN_ID"),
        "workflowRunAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "workflowJob": os.environ.get("GITHUB_JOB"),
    }
    bound_map["sourceDigest"] = aggregate(source_entries)
    bound_map["documentDigest"] = aggregate(document_entries)
    bound_map["productCallerProjection"] = product
    bound_map["crashConsistencyProjection"] = crash
    bound_map["performanceQualificationProjection"] = performance
    bound_map["productionAcceptanceProjection"] = production_acceptance

    current_projection = {
        "schema": "hepta.authbus.current-implementation-projection.v2",
        "module": "auth.authbus",
        "candidate": candidate,
        "document": CURRENT_IMPLEMENTATION.relative_to(ROOT).as_posix(),
        "documentSha256": sha256(CURRENT_IMPLEMENTATION),
        "operationCount": len(mapping["operations"]),
        "productCallers": [row["name"] for row in product["callers"]],
        "productionImplementation": False,
        "activation": False,
        "release": False,
    }
    dossier = {
        "schema": "hepta.authbus.qualification-dossier.v2",
        "module": "auth.authbus",
        "candidate": candidate,
        "sourceDigest": aggregate(source_entries),
        "documentDigest": aggregate(document_entries),
        "documents": [
            {"path": name, "sha256": digest} for name, digest in sorted(document_entries)
        ],
        "implementationMap": {
            "path": MAP_PATH.relative_to(ROOT).as_posix(),
            "sha256": sha256(MAP_PATH),
            "operationCount": len(mapping["operations"]),
        },
        "productCallerContract": product,
        "crashConsistencyMatrix": crash,
        "performanceQualification": performance,
        "productionAcceptance": production_acceptance,
        "targetHostEvidenceRequired": True,
        "independentSecurityAcceptance": False,
        "activation": False,
        "release": False,
    }
    release_status = {
        "schema": "hepta.authbus.release-status-projection.v2",
        "module": "auth.authbus",
        "candidate": candidate,
        "sourceQualification": "running",
        "syntheticMergeRequired": args.candidate_kind != "main_head",
        "targetHostQualification": "pending_external_execution",
        "kmsHsmComposition": "pending_external_execution",
        "productionAcceptance": "pending_signed_external_evidence",
        "independentSecurityAcceptance": False,
        "operatorActivation": False,
        "canaryPromotion": False,
        "release": False,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / "source-head.json", candidate)
    write_json(args.output_dir / "implementation-map.bound.json", bound_map)
    write_json(args.output_dir / "current-implementation.bound.json", current_projection)
    write_json(args.output_dir / "qualification-dossier.bound.json", dossier)
    write_json(args.output_dir / "release-status.bound.json", release_status)
    ensure_clean()


if __name__ == "__main__":
    main()
