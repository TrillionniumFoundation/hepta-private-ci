#!/usr/bin/env python3
"""Emit non-authoritative diagnostics and verify Lane A receipt identities."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from lane_a_foundation_lib import (  # noqa: E402
    CANDIDATE_KINDS,
    VerificationError,
    candidate_identity,
    canonical,
    exact_source,
)

OUTCOMES = frozenset({"success", "failure", "cancelled", "skipped"})
PROVENANCE_PATHS = (
    "docs/modules/platform.types/PUBLIC_API_INVENTORY_V1.json",
    "docs/modules/platform.types/IMPLEMENTATION_MAP.json",
    "docs/modules/platform.types/PROTOCOL_AND_QUALIFICATION_V1.md",
    "docs/lane-a-foundation/platform.types/TRUTH_MATRIX_V1.json",
    "docs/lane-a-foundation/platform.types/CURRENT_IMPLEMENTATION.md",
    "qualification/module-execution-dossiers/detail/platform.types.md",
    "codex-rs/hepta-types/MANIFEST_V1_CONFORMANCE.json",
    "codex-rs/hepta-types/CONSUMER_QUALIFICATION_V1.json",
    ".github/workflows/lane-a-foundation.yml",
)


class EvidenceError(RuntimeError):
    """Candidate diagnostics or authoritative receipt identity is invalid."""


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EvidenceError(f"cannot read receipt {path}: {error}") from error
    if not isinstance(value, dict):
        raise EvidenceError(f"receipt must be a JSON object: {path}")
    return value


def sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise EvidenceError(f"cannot hash {path}: {error}") from error


def expected_identity(args: argparse.Namespace) -> dict[str, Any]:
    candidate_sha, candidate_tree = exact_source(args.expected_sha)
    return candidate_identity(
        args.candidate_kind,
        candidate_sha,
        candidate_tree,
        source_sha=args.source_sha,
        base_sha=args.base_sha,
        pull_request_number=args.pr_number,
    )


def validate_receipt_documents(
    source_receipt: dict[str, Any],
    native_receipt: dict[str, Any],
    identity: dict[str, Any],
) -> None:
    expected = (
        (source_receipt, "source-truth"),
        (native_receipt, "native-qualification"),
    )
    for receipt, receipt_class in expected:
        if receipt.get("lane") != "LANE-A-FOUNDATION":
            raise EvidenceError(f"{receipt_class}: lane mismatch")
        if receipt.get("receiptClass") != receipt_class:
            raise EvidenceError(f"{receipt_class}: receipt-class mismatch")
        if receipt.get("candidateKind") != identity["kind"]:
            raise EvidenceError(f"{receipt_class}: candidate kind mismatch")
        if receipt.get("candidateIdentity") != identity:
            raise EvidenceError(f"{receipt_class}: candidate identity mismatch")
        for field, key in (
            ("candidateSha", "candidateSha"),
            ("candidateTree", "candidateTree"),
            ("sourceSha", "candidateSha"),
            ("sourceTree", "candidateTree"),
        ):
            if receipt.get(field) != identity[key]:
                raise EvidenceError(f"{receipt_class}: {field} mismatch")
        if receipt.get("productionActivation") != "not_claimed":
            raise EvidenceError(f"{receipt_class}: production activation overclaim")
        if receipt.get("externalAcceptance") != "not_claimed":
            raise EvidenceError(f"{receipt_class}: external acceptance overclaim")
    if native_receipt.get("status") != "passed_in_current_job":
        raise EvidenceError("native receipt did not pass in the current job")
    if source_receipt["candidateIdentity"] != native_receipt["candidateIdentity"]:
        raise EvidenceError("source and native receipts identify different candidates")


def write_diagnostics(args: argparse.Namespace) -> None:
    identity = expected_identity(args)
    outcomes = {
        "truth": args.truth_outcome,
        "native": args.native_outcome,
        "consumers": args.consumer_outcome,
    }
    for name, outcome in outcomes.items():
        if outcome not in OUTCOMES:
            raise EvidenceError(f"invalid {name} outcome: {outcome!r}")
    files: dict[str, dict[str, Any]] = {}
    for relative in PROVENANCE_PATHS:
        path = ROOT / relative
        if not path.is_file():
            raise EvidenceError(f"missing candidate provenance file: {relative}")
        files[relative] = {
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
    record = {
        "schema": "hepta.lane-a.candidate-diagnostics.v1",
        "schemaVersion": 1,
        "lane": "LANE-A-FOUNDATION",
        "candidateKind": identity["kind"],
        "candidateIdentity": identity,
        "candidateIdentitySha256": hashlib.sha256(canonical(identity)).hexdigest(),
        "generatedAtUtc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "outcomes": outcomes,
        "allRequiredChecksPassed": all(value == "success" for value in outcomes.values()),
        "authoritativeQualification": False,
        "receiptEmissionExpected": all(value == "success" for value in outcomes.values()),
        "provenanceFiles": files,
        "github": {
            "runId": os.environ.get("GITHUB_RUN_ID"),
            "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "job": os.environ.get("GITHUB_JOB"),
            "workflow": os.environ.get("GITHUB_WORKFLOW"),
        },
        "nonClaims": {
            "productionActivation": "not_claimed",
            "externalAcceptance": "not_claimed",
            "promotion": "not_claimed",
            "release": "not_claimed",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def verify_receipts(args: argparse.Namespace) -> None:
    identity = expected_identity(args)
    source = read_object(args.source_receipt)
    native = read_object(args.native_receipt)
    validate_receipt_documents(source, native, identity)
    report = {
        "schema": "hepta.lane-a.receipt-pair-verification.v1",
        "schemaVersion": 1,
        "lane": "LANE-A-FOUNDATION",
        "candidateKind": identity["kind"],
        "candidateIdentity": identity,
        "sourceReceiptSha256": sha256_file(args.source_receipt),
        "nativeReceiptSha256": sha256_file(args.native_receipt),
        "status": "passed",
        "productionActivation": "not_claimed",
        "externalAcceptance": "not_claimed",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def self_test() -> None:
    identity = {
        "schema": "hepta.lane-a.candidate-identity.v1",
        "kind": "source-head",
        "candidateSha": "a" * 40,
        "candidateTree": "b" * 40,
        "sourceSha": "a" * 40,
    }
    common = {
        "lane": "LANE-A-FOUNDATION",
        "candidateKind": "source-head",
        "candidateIdentity": identity,
        "candidateSha": "a" * 40,
        "candidateTree": "b" * 40,
        "sourceSha": "a" * 40,
        "sourceTree": "b" * 40,
        "productionActivation": "not_claimed",
        "externalAcceptance": "not_claimed",
    }
    source = {**common, "receiptClass": "source-truth"}
    native = {
        **common,
        "receiptClass": "native-qualification",
        "status": "passed_in_current_job",
    }
    validate_receipt_documents(source, native, identity)
    mutations = []
    wrong_kind = dict(source)
    wrong_kind["candidateKind"] = "synthetic-merge"
    mutations.append((wrong_kind, native))
    wrong_identity = json.loads(json.dumps(native))
    wrong_identity["candidateIdentity"]["sourceSha"] = "c" * 40
    mutations.append((source, wrong_identity))
    overclaim = dict(source)
    overclaim["productionActivation"] = "claimed"
    mutations.append((overclaim, native))
    for invalid_source, invalid_native in mutations:
        try:
            validate_receipt_documents(invalid_source, invalid_native, identity)
        except EvidenceError:
            pass
        else:
            raise EvidenceError("self-test accepted an interchangeable or overclaiming receipt")


def add_identity_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--candidate-kind", choices=sorted(CANDIDATE_KINDS), required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--base-sha")
    parser.add_argument("--pr-number", type=int)


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    diagnostic = commands.add_parser("diagnostics")
    add_identity_arguments(diagnostic)
    diagnostic.add_argument("--truth-outcome", required=True)
    diagnostic.add_argument("--native-outcome", required=True)
    diagnostic.add_argument("--consumer-outcome", required=True)
    diagnostic.add_argument("--output", type=Path, required=True)

    verify = commands.add_parser("verify-receipts")
    add_identity_arguments(verify)
    verify.add_argument("--source-receipt", type=Path, required=True)
    verify.add_argument("--native-receipt", type=Path, required=True)
    verify.add_argument("--output", type=Path, required=True)
    commands.add_parser("self-test")
    args = parser.parse_args()
    try:
        if args.command == "diagnostics":
            write_diagnostics(args)
        elif args.command == "verify-receipts":
            verify_receipts(args)
        else:
            self_test()
    except (EvidenceError, VerificationError) as error:
        print(f"lane-a candidate evidence failed: {error}", file=sys.stderr)
        return 1
    print(f"lane-a candidate evidence {args.command}: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
