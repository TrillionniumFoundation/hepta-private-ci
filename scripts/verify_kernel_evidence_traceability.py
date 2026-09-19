#!/usr/bin/env python3
"""Verify kernel.evidence closure traceability and emit exact-candidate receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TRACEABILITY = ROOT / "docs/modules/kernel.evidence/TRACEABILITY.json"
IMPLEMENTATION_MAP = ROOT / "docs/modules/kernel.evidence/IMPLEMENTATION_MAP.json"

RECEIPT_ARTIFACTS = [
    "docs/modules/kernel.evidence/TRACEABILITY.json",
    "docs/modules/kernel.evidence/TECHNICAL.md",
    "docs/modules/kernel.evidence/IMPLEMENTATION_MAP.json",
    "docs/lane-a-foundation/kernel.evidence/CURRENT_IMPLEMENTATION.md",
    "docs/lane-a-foundation/kernel.evidence/STORE_V1.md",
    "qualification/module-execution-dossiers/detail/kernel.evidence.md",
    "codex-rs/hepta-evidence/src/qualification.rs",
    "codex-rs/hepta-evidence/src/qualification_tests.rs",
    "codex-rs/hepta-evidence/src/bin/hepta-evidence-writer.rs",
    "codex-rs/hepta-evidence/migrations/0011_qualification_evidence.sql",
]


class TraceabilityError(RuntimeError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TraceabilityError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise TraceabilityError(f"JSON object required: {path}")
    return value


def git(*args: str) -> str:
    run = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return run.stdout.strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_anchor(requirement: str, anchor: Any) -> None:
    if not isinstance(anchor, dict) or not isinstance(anchor.get("path"), str):
        raise TraceabilityError(f"{requirement}: invalid anchor")
    path = ROOT / anchor["path"]
    if not path.is_file():
        raise TraceabilityError(f"{requirement}: missing anchor {anchor['path']}")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise TraceabilityError(
            f"{requirement}: anchor is not UTF-8: {anchor['path']}"
        ) from error
    needles = anchor.get("mustContain", [])
    if not isinstance(needles, list) or not all(
        isinstance(item, str) and item for item in needles
    ):
        raise TraceabilityError(f"{requirement}: invalid mustContain")
    for needle in needles:
        if needle not in text:
            raise TraceabilityError(
                f"{requirement}: missing {needle!r} in {anchor['path']}"
            )


def verify() -> dict[str, Any]:
    trace = load_json(TRACEABILITY)
    if (
        trace.get("schema") != "hepta.kernel-evidence-traceability.v1"
        or trace.get("schemaVersion") != 1
        or trace.get("module") != "kernel.evidence"
    ):
        raise TraceabilityError("traceability header mismatch")
    boundary = trace.get("claimBoundary")
    if not isinstance(boundary, dict):
        raise TraceabilityError("traceability claimBoundary missing")
    expected_boundary = {
        "nativeContractImplemented": True,
        "authenticatedProductWriterImplemented": True,
        "externalCheckpointVerificationImplemented": True,
        "exactCandidateExecutionReceipt": "generated_by_lane_a_ci",
        "independentAcceptance": "pending_external",
        "activation": False,
        "release": False,
    }
    if boundary != expected_boundary:
        raise TraceabilityError("traceability claimBoundary changed unexpectedly")

    rows = trace.get("requirements")
    if not isinstance(rows, list) or len(rows) < 10:
        raise TraceabilityError("at least ten closure requirements are required")
    seen: set[str] = set()
    pending_external = 0
    for row in rows:
        if not isinstance(row, dict):
            raise TraceabilityError("requirement row must be an object")
        requirement = row.get("id")
        if not isinstance(requirement, str) or not requirement or requirement in seen:
            raise TraceabilityError("requirement ids must be unique non-empty strings")
        seen.add(requirement)
        if not isinstance(row.get("requirement"), str) or not row["requirement"]:
            raise TraceabilityError(f"{requirement}: requirement text missing")
        for field in ("sourceAnchors", "testAnchors"):
            anchors = row.get(field)
            if not isinstance(anchors, list) or not anchors:
                raise TraceabilityError(f"{requirement}: {field} missing")
            for anchor in anchors:
                validate_anchor(requirement, anchor)
        if not isinstance(row.get("executionReceipt"), str) or not row["executionReceipt"]:
            raise TraceabilityError(f"{requirement}: execution receipt binding missing")
        independent = row.get("independentReceipt")
        if not isinstance(independent, dict):
            raise TraceabilityError(f"{requirement}: independent receipt state missing")
        state = independent.get("state")
        if state not in {"not_required_for_native_invariant", "pending_external"}:
            raise TraceabilityError(
                f"{requirement}: invalid independent receipt state {state!r}"
            )
        if state == "pending_external":
            pending_external += 1
    if pending_external == 0:
        raise TraceabilityError("independent acceptance cannot disappear from traceability")

    implementation = load_json(IMPLEMENTATION_MAP)
    claim = implementation.get("claimBoundary")
    if not isinstance(claim, dict):
        raise TraceabilityError("implementation map claimBoundary missing")
    for field in ("independentAcceptance", "activation", "release"):
        if claim.get(field) is not False:
            raise TraceabilityError(
                f"implementation map must not self-claim {field} before external closure"
            )
    return {
        "requirements": len(rows),
        "pendingExternal": pending_external,
    }


def write_receipt(output: Path, expected_sha: str, kind: str) -> None:
    summary = verify()
    head = git("rev-parse", "HEAD")
    if head != expected_sha:
        raise TraceabilityError(
            f"exact candidate mismatch: HEAD={head}, expected={expected_sha}"
        )
    tree = git("rev-parse", "HEAD^{tree}")
    artifacts: dict[str, str] = {}
    for relative in RECEIPT_ARTIFACTS:
        path = ROOT / relative
        if not path.is_file():
            raise TraceabilityError(f"receipt artifact is missing: {relative}")
        artifacts[relative] = sha256_file(path)
    receipt = {
        "schema": "hepta.kernel-evidence-exact-candidate-receipt.v1",
        "schemaVersion": 1,
        "module": "kernel.evidence",
        "kind": kind,
        "candidateSha": head,
        "gitTree": tree,
        "requirements": summary["requirements"],
        "pendingExternalRequirements": summary["pendingExternal"],
        "artifactSha256": artifacts,
        "nativeTestsCompletedBeforeReceipt": True,
        "productExecutionProved": True,
        "independentAcceptance": False,
        "activation": False,
        "release": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def write_review_request(receipt_path: Path, output: Path, role: str) -> None:
    receipt = load_json(receipt_path)
    if (
        receipt.get("schema") != "hepta.kernel-evidence-exact-candidate-receipt.v1"
        or receipt.get("module") != "kernel.evidence"
        or receipt.get("independentAcceptance") is not False
    ):
        raise TraceabilityError("review request requires an unaccepted exact-candidate receipt")
    candidate_sha = receipt.get("candidateSha")
    tree = receipt.get("gitTree")
    if not isinstance(candidate_sha, str) or not isinstance(tree, str):
        raise TraceabilityError("exact-candidate receipt identity missing")
    request = {
        "schema": "hepta.kernel-evidence-independent-review-request.v1",
        "schemaVersion": 1,
        "module": "kernel.evidence",
        "candidate": {
            "candidateId": f"git:{candidate_sha}:{tree}",
            "sourceCommit": candidate_sha,
            "sourceTree": tree,
        },
        "requiredRole": role,
        "evidenceSetDigest": sha256_file(receipt_path),
        "evidenceReceiptPath": receipt_path.name,
        "decisionContract": "IndependentDecisionReceiptV1",
        "allowedDecisions": ["accept", "reject", "conditional", "abstain"],
        "requiredConditions": [
            "exact_candidate_only",
            "no_promotion_authority",
        ],
        "signerMustBeIndependentOfGenerator": True,
        "independentAcceptance": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify")
    receipt = sub.add_parser("receipt")
    receipt.add_argument("--expected-sha", required=True)
    receipt.add_argument(
        "--kind",
        choices=("source_head", "synthetic_merge_candidate"),
        required=True,
    )
    receipt.add_argument("--output", type=Path, required=True)
    review = sub.add_parser("review-request")
    review.add_argument("--receipt", type=Path, required=True)
    review.add_argument("--output", type=Path, required=True)
    review.add_argument("--role", default="independent-review")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            summary = verify()
            print(
                json.dumps(
                    {
                        "status": "PASS_KERNEL_EVIDENCE_TRACEABILITY",
                        **summary,
                        "independentAcceptance": False,
                        "activation": False,
                        "release": False,
                    },
                    sort_keys=True,
                )
            )
        elif args.command == "receipt":
            write_receipt(args.output, args.expected_sha, args.kind)
            print(f"kernel.evidence exact-candidate receipt: {args.output}")
        else:
            write_review_request(args.receipt, args.output, args.role)
            print(f"kernel.evidence independent review request: {args.output}")
    except (TraceabilityError, subprocess.CalledProcessError) as error:
        print(f"kernel.evidence traceability failed: {error}", file=__import__("sys").stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
