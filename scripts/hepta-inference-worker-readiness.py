#!/usr/bin/env python3
"""Emit exact-candidate inference.worker receipts and validate target-host evidence.

Repository/CI receipts bind source, documents and named checks to one Git
candidate. Hardware evidence validation is structural and fail-closed; it does
not turn self-generated data into independent physical attestation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "docs/modules/inference.worker/IMPLEMENTATION_MAP.json"
TECH = ROOT / "docs/modules/inference.worker/TECHNICAL.md"
RUNBOOK = ROOT / "docs/modules/inference.worker/PRODUCTION_READINESS.md"
LANE_B_WORKFLOW = ROOT / ".github/workflows/hepta-lane-b-truth.yml"
WORKER_REL = "codex-rs/hepta-infer-worker-host"

NEGATIVE_CLAIMS = (
    "productionImplementation",
    "productExecutionComplete",
    "deploymentQualificationComplete",
    "independentAcceptanceComplete",
    "productExecutionProved",
    "independentAcceptance",
    "activation",
    "release",
)
EVIDENCE_CLASSES = (
    "identity",
    "source-head-tested",
    "merge-candidate-tested",
)
REQUIRED_TEST_CHECKS = (
    "codex-hepta-infer-core-lib",
    "codex-hepta-infer-worker-host-lib",
)
HARDWARE_SCENARIOS = (
    "cold-load-warm-reload",
    "cpu-or-gpu-inference",
    "concurrent-at-grant-ceiling",
    "reject-above-grant-ceiling",
    "reject-model-above-memory-grant",
    "real-oom",
    "cancel-during-inference",
    "cancel-during-unload",
    "driver-crash",
    "device-reset-loss",
    "repeated-load-run-unload-leak",
    "app-server-kill-restart",
    "worker-kill-durable-boundaries",
)
ISOLATION_CONTROLS = (
    "processBoundary",
    "cpuMemoryLimits",
    "deviceAclOrLease",
    "acceleratorMemory",
    "filesystemBoundary",
    "authenticatedControl",
)
MODEL_DIGESTS = (
    "modelDigest",
    "weightsDigest",
    "tokenizerDigest",
    "preprocessorDigest",
    "quantizationDigest",
    "runtimeDigest",
    "deviceDigest",
)
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.rstrip("\n")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected object")
    return value


def _write_or_print(value: dict[str, Any], output: Path | None) -> None:
    encoded = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if output is None:
        print(encoded, end="")
        return
    path = output if output.is_absolute() else ROOT / output
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding="utf-8")


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}: expected non-empty text")
    return value


def _require_hex(value: Any, field: str, pattern: re.Pattern[str]) -> str:
    text = _require_text(value, field)
    if not pattern.fullmatch(text) or set(text) == {"0"}:
        raise ValueError(f"{field}: invalid digest/identity")
    return text


def worker_tree(commit: str) -> str:
    value = git("rev-parse", f"{commit}:{WORKER_REL}")
    if not HEX40.fullmatch(value):
        raise ValueError("invalid worker tree identity")
    return value


def worker_source_delta(source_commit: str, candidate_commit: str) -> list[str]:
    value = git(
        "diff",
        "--name-only",
        f"{source_commit}..{candidate_commit}",
        "--",
        WORKER_REL,
    )
    return [line for line in value.splitlines() if line]


def build_receipt(
    expected_sha: str | None = None,
    evidence_class: str = "identity",
    passed_checks: tuple[str, ...] | list[str] = (),
) -> dict[str, Any]:
    if evidence_class not in EVIDENCE_CLASSES:
        raise ValueError(f"unsupported evidence class {evidence_class}")
    head = git("rev-parse", "HEAD")
    if expected_sha is not None and head != expected_sha:
        raise ValueError(f"checkout {head} does not match expected candidate {expected_sha}")
    tree = git("rev-parse", "HEAD^{tree}")
    mapping = load_json(MAP)
    if mapping.get("module") != "inference.worker":
        raise ValueError("implementation map module mismatch")
    source_base = mapping.get("sourceBase")
    if not isinstance(source_base, dict) or set(source_base) != {"commit", "tree"}:
        raise ValueError("invalid implementation-map sourceBase")
    source_commit = _require_hex(source_base.get("commit"), "sourceBase.commit", HEX40)
    source_tree = _require_hex(source_base.get("tree"), "sourceBase.tree", HEX40)
    if git("rev-parse", f"{source_commit}^{{tree}}") != source_tree:
        raise ValueError("implementation-map sourceBase tree mismatch")
    git("merge-base", "--is-ancestor", source_commit, head)

    claim = mapping.get("claimBoundary")
    if not isinstance(claim, dict):
        raise ValueError("missing claimBoundary")
    for key in NEGATIVE_CLAIMS:
        value = mapping.get(key) if key in mapping else claim.get(key)
        if value is not False:
            raise ValueError(f"{key} must remain false until independently qualified")

    for path in (TECH, RUNBOOK):
        text = path.read_text(encoding="utf-8")
        if "ResourceGrant" not in text or "isolation" not in text.lower():
            raise ValueError(f"{path}: trust/isolation contract is incomplete")

    checks = sorted(set(passed_checks))
    if evidence_class != "identity":
        missing = sorted(set(REQUIRED_TEST_CHECKS) - set(checks))
        if missing:
            raise ValueError(
                "tested evidence is missing required checks: " + ", ".join(missing)
            )

    candidate_worker_tree = worker_tree(head)
    map_source_worker_tree = worker_tree(source_commit)
    map_blob = git("rev-parse", f"{head}:{MAP.relative_to(ROOT)}")
    source_delta = worker_source_delta(source_commit, head)
    ci = {
        "workflow": os.environ.get("GITHUB_WORKFLOW"),
        "job": os.environ.get("GITHUB_JOB"),
        "runId": os.environ.get("GITHUB_RUN_ID"),
        "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
    }
    ci = {key: value for key, value in ci.items() if value}

    return {
        "schema": "hepta.inference-worker-candidate-receipt.v2",
        "schemaVersion": 2,
        "module": "inference.worker",
        "candidate": {
            "commit": head,
            "tree": tree,
            "workerTree": candidate_worker_tree,
        },
        "sourceBinding": {
            "implementationMapBlob": map_blob,
            "implementationMapSourceBase": source_base,
            "implementationMapSourceWorkerTree": map_source_worker_tree,
            "candidateWorkerTree": candidate_worker_tree,
            "workerPathsChangedSinceMapSourceBase": source_delta,
        },
        "documents": {
            str(MAP.relative_to(ROOT)): sha256_file(MAP),
            str(TECH.relative_to(ROOT)): sha256_file(TECH),
            str(RUNBOOK.relative_to(ROOT)): sha256_file(RUNBOOK),
            str(LANE_B_WORKFLOW.relative_to(ROOT)): sha256_file(LANE_B_WORKFLOW),
        },
        "qualificationEvidence": {
            "class": evidence_class,
            "passedChecks": checks,
            "ci": ci,
        },
        "repositoryControlledGaps": mapping.get("repositoryControlledGaps", []),
        "externalEvidenceGates": mapping.get("externalEvidenceGates", []),
        "claimBoundary": {key: False for key in NEGATIVE_CLAIMS},
        "limitations": [
            "receipt binds exact source/document/check identity only",
            "sourceBase is historical map provenance; candidate.workerTree is the current source anchor",
            "receipt is not hardware qualification",
            "receipt is not provider reconciliation evidence",
            "receipt is not independent acceptance or activation authority",
        ],
    }


def hardware_evidence_template(expected_sha: str | None = None) -> dict[str, Any]:
    head = git("rev-parse", "HEAD")
    if expected_sha is not None and head != expected_sha:
        raise ValueError(f"checkout {head} does not match expected candidate {expected_sha}")
    tree = git("rev-parse", "HEAD^{tree}")
    control = {
        "status": "pending",
        "owner": "PENDING",
        "evidenceDigest": "PENDING",
    }
    scenario = {
        "status": "pending",
        "evidenceDigest": "PENDING",
        "measurements": {},
    }
    return {
        "schema": "hepta.inference-worker-hardware-qualification.v1",
        "schemaVersion": 1,
        "module": "inference.worker",
        "candidate": {
            "commit": head,
            "tree": tree,
            "workerTree": worker_tree(head),
            "readinessReceiptDigest": "PENDING",
        },
        "host": {
            "hostClass": "PENDING",
            "runnerId": "PENDING",
            "os": "PENDING",
            "arch": "PENDING",
            "attestationDigest": "PENDING",
        },
        "model": {name: "PENDING" for name in MODEL_DIGESTS},
        "isolation": {name: dict(control) for name in ISOLATION_CONTROLS},
        "scenarios": [
            {"id": name, **dict(scenario)}
            for name in HARDWARE_SCENARIOS
        ],
        "observer": {
            "identity": "PENDING",
            "independent": False,
            "evidenceDigest": "PENDING",
        },
        "result": {
            "qualified": False,
            "qualifiedAt": "PENDING",
        },
    }


def validate_hardware_evidence(
    value: dict[str, Any],
    expected_sha: str | None = None,
) -> dict[str, Any]:
    if value.get("schema") != "hepta.inference-worker-hardware-qualification.v1":
        raise ValueError("hardware evidence schema mismatch")
    if value.get("schemaVersion") != 1 or value.get("module") != "inference.worker":
        raise ValueError("hardware evidence identity mismatch")

    candidate = value.get("candidate")
    if not isinstance(candidate, dict):
        raise ValueError("candidate: expected object")
    commit = _require_hex(candidate.get("commit"), "candidate.commit", HEX40)
    tree = _require_hex(candidate.get("tree"), "candidate.tree", HEX40)
    candidate_worker_tree = _require_hex(
        candidate.get("workerTree"), "candidate.workerTree", HEX40
    )
    _require_hex(
        candidate.get("readinessReceiptDigest"),
        "candidate.readinessReceiptDigest",
        HEX64,
    )
    if expected_sha is not None and commit != expected_sha:
        raise ValueError(
            f"hardware evidence candidate {commit} does not match expected {expected_sha}"
        )
    if git("rev-parse", f"{commit}^{{tree}}") != tree:
        raise ValueError("hardware evidence candidate tree mismatch")
    if worker_tree(commit) != candidate_worker_tree:
        raise ValueError("hardware evidence worker tree mismatch")

    host = value.get("host")
    if not isinstance(host, dict):
        raise ValueError("host: expected object")
    for key in ("hostClass", "runnerId", "os", "arch"):
        _require_text(host.get(key), f"host.{key}")
    _require_hex(host.get("attestationDigest"), "host.attestationDigest", HEX64)

    model = value.get("model")
    if not isinstance(model, dict):
        raise ValueError("model: expected object")
    for key in MODEL_DIGESTS:
        _require_hex(model.get(key), f"model.{key}", HEX64)

    isolation = value.get("isolation")
    if not isinstance(isolation, dict) or set(isolation) != set(ISOLATION_CONTROLS):
        raise ValueError("isolation controls must exactly match the required set")
    for key in ISOLATION_CONTROLS:
        row = isolation[key]
        if not isinstance(row, dict) or row.get("status") != "proved":
            raise ValueError(f"isolation.{key}: must be proved")
        _require_text(row.get("owner"), f"isolation.{key}.owner")
        _require_hex(
            row.get("evidenceDigest"),
            f"isolation.{key}.evidenceDigest",
            HEX64,
        )

    scenarios = value.get("scenarios")
    if not isinstance(scenarios, list):
        raise ValueError("scenarios: expected list")
    by_id: dict[str, dict[str, Any]] = {}
    for row in scenarios:
        if not isinstance(row, dict):
            raise ValueError("scenario: expected object")
        scenario_id = _require_text(row.get("id"), "scenario.id")
        if scenario_id in by_id:
            raise ValueError(f"duplicate scenario {scenario_id}")
        by_id[scenario_id] = row
    if set(by_id) != set(HARDWARE_SCENARIOS):
        missing = sorted(set(HARDWARE_SCENARIOS) - set(by_id))
        extra = sorted(set(by_id) - set(HARDWARE_SCENARIOS))
        raise ValueError(f"hardware scenario set mismatch missing={missing} extra={extra}")
    for scenario_id in HARDWARE_SCENARIOS:
        row = by_id[scenario_id]
        if row.get("status") != "passed":
            raise ValueError(f"scenario {scenario_id}: must be passed")
        _require_hex(
            row.get("evidenceDigest"),
            f"scenario.{scenario_id}.evidenceDigest",
            HEX64,
        )
        if not isinstance(row.get("measurements"), dict):
            raise ValueError(f"scenario {scenario_id}: measurements must be an object")

    observer = value.get("observer")
    if not isinstance(observer, dict):
        raise ValueError("observer: expected object")
    _require_text(observer.get("identity"), "observer.identity")
    if observer.get("independent") is not True:
        raise ValueError("observer.independent must be true")
    _require_hex(observer.get("evidenceDigest"), "observer.evidenceDigest", HEX64)

    result = value.get("result")
    if not isinstance(result, dict) or result.get("qualified") is not True:
        raise ValueError("result.qualified must be true")
    _require_text(result.get("qualifiedAt"), "result.qualifiedAt")

    return {
        "status": "PASS_INFERENCE_WORKER_HARDWARE_EVIDENCE_STRUCTURE",
        "module": "inference.worker",
        "candidate": {
            "commit": commit,
            "tree": tree,
            "workerTree": candidate_worker_tree,
        },
        "scenarios": len(HARDWARE_SCENARIOS),
        "isolationControls": len(ISOLATION_CONTROLS),
        "limitation": (
            "structural verification does not independently authenticate physical "
            "hardware, measurements, or observer identity"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--evidence-class", choices=EVIDENCE_CLASSES, default="identity")
    parser.add_argument("--passed-check", action="append", default=[])
    hardware = parser.add_mutually_exclusive_group()
    hardware.add_argument("--emit-hardware-template", type=Path)
    hardware.add_argument("--verify-hardware-evidence", type=Path)
    args = parser.parse_args()

    if args.emit_hardware_template:
        template = hardware_evidence_template(args.expected_sha)
        _write_or_print(template, args.emit_hardware_template)
        return 0
    if args.verify_hardware_evidence:
        path = (
            args.verify_hardware_evidence
            if args.verify_hardware_evidence.is_absolute()
            else ROOT / args.verify_hardware_evidence
        )
        result = validate_hardware_evidence(load_json(path), args.expected_sha)
        _write_or_print(result, args.output)
        return 0

    receipt = build_receipt(
        args.expected_sha,
        evidence_class=args.evidence_class,
        passed_checks=args.passed_check,
    )
    _write_or_print(receipt, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
