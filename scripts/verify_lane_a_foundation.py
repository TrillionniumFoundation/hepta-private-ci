#!/usr/bin/env python3
"""Verify Lane A current-implementation truth and emit exact-candidate receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "docs/lane-a-foundation/MODULE_TRUTH_MATRIX.json"
EXPECTED_MODULES = [
    "platform.types",
    "platform.wire",
    "kernel.authority",
    "kernel.operations",
    "kernel.evidence",
    "auth.authbus",
    "secrets.heptabao",
]
EXPECTED_AXES = [
    "source",
    "implementation",
    "durability",
    "qualification",
    "activation",
    "acceptance",
]
REQUIRED_SECTIONS = [
    "## Current executable contract",
    "## Target-only design",
    "## Known limits and non-claims",
    "## Verification",
]


class VerificationError(RuntimeError):
    """Raised when repository truth and the Lane A matrix diverge."""


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise VerificationError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise VerificationError(f"top-level JSON object required: {path}")
    return value


def require_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise VerificationError(f"cannot read UTF-8 source {path}: {error}") from error


def validate_matrix(matrix: dict[str, Any], root: Path = ROOT) -> None:
    if matrix.get("schemaVersion") != 1:
        raise VerificationError("schemaVersion must be 1")
    if matrix.get("lane") != "LANE-A-FOUNDATION":
        raise VerificationError("lane identity mismatch")
    if matrix.get("moduleCoverage") != len(EXPECTED_MODULES):
        raise VerificationError("moduleCoverage is not the closed-world Lane A size")
    if matrix.get("statusAxes") != EXPECTED_AXES:
        raise VerificationError("statusAxes must be exact, ordered and orthogonal")

    closure = matrix.get("closure")
    if not isinstance(closure, dict):
        raise VerificationError("closure object is required")
    required_closure = {
        "repositoryControlledDocumentationGaps": "closed",
        "currentImplementationTruth": "closed",
        "automatedDriftGate": "closed",
        "productionImplementation": "not_claimed",
        "productionActivation": "not_claimed",
        "externalAcceptance": "not_claimed",
    }
    if closure != required_closure:
        raise VerificationError(
            "closure must close repository truth without forging production or acceptance"
        )

    modules = matrix.get("modules")
    if not isinstance(modules, list):
        raise VerificationError("modules array is required")
    names = [row.get("module") for row in modules if isinstance(row, dict)]
    if names != EXPECTED_MODULES:
        raise VerificationError(f"closed-world module order mismatch: {names!r}")

    for row in modules:
        validate_module(row, root)

    by_name = {row["module"]: row for row in modules}
    require_state(by_name, "kernel.operations", "implementation", "reference_model")
    require_state(by_name, "kernel.operations", "durability", "not_implemented")
    require_state(by_name, "auth.authbus", "implementation", "replay_verifier")
    require_state(by_name, "auth.authbus", "durability", "process_memory_only")
    require_state(by_name, "platform.wire", "implementation", "fixed_v1_codec")
    require_state(by_name, "kernel.authority", "implementation", "final_use_boundary")
    require_state(
        by_name, "kernel.evidence", "durability", "sqlite_migrations_0001_0008"
    )
    require_state(by_name, "secrets.heptabao", "implementation", "bounded_kv_v2_reader")

    forbidden_current = {
        "platform.wire": {"version negotiation"},
        "kernel.operations": {
            "durable operation ledger",
            "transactional durable outbox",
        },
        "auth.authbus": {
            "cryptographic signature verification",
            "durable replay protection",
            "authorization policy evaluation",
            "quota registry",
            "quota reservation and settlement",
        },
        "secrets.heptabao": {
            "secret mutation",
            "generic lease renewal API",
            "generic revoke API",
        },
    }
    for module, forbidden in forbidden_current.items():
        current = set(by_name[module]["currentCapabilities"])
        overlap = current & forbidden
        if overlap:
            raise VerificationError(
                f"{module} promotes target-only capability into current truth: {sorted(overlap)}"
            )

    validate_module_specific_source(root)


def validate_module(row: Any, root: Path) -> None:
    if not isinstance(row, dict):
        raise VerificationError("module rows must be objects")
    module = row.get("module")
    if module not in EXPECTED_MODULES:
        raise VerificationError(f"unknown module {module!r}")

    states = row.get("states")
    if not isinstance(states, dict) or list(states) != EXPECTED_AXES:
        raise VerificationError(f"{module}: states must contain the exact ordered axes")
    if states["source"] != "implemented":
        raise VerificationError(f"{module}: source anchor package must be implemented")
    if states["acceptance"] != "not_granted":
        raise VerificationError(
            f"{module}: repository source may not self-grant acceptance"
        )

    guide = root / str(row.get("formalGuide", ""))
    if not guide.is_file():
        raise VerificationError(f"{module}: missing formal guide {guide}")
    specification = root / str(row.get("currentSpecification", ""))
    text = require_text(specification)
    for section in REQUIRED_SECTIONS:
        if section not in text:
            raise VerificationError(
                f"{module}: current specification missing {section}"
            )

    current = row.get("currentCapabilities")
    target = row.get("targetOnlyCapabilities")
    if not isinstance(current, list) or not all(
        isinstance(value, str) and value for value in current
    ):
        raise VerificationError(
            f"{module}: currentCapabilities must be nonempty strings"
        )
    if not isinstance(target, list) or not all(
        isinstance(value, str) and value for value in target
    ):
        raise VerificationError(f"{module}: targetOnlyCapabilities must be strings")
    overlap = set(current) & set(target)
    if overlap:
        raise VerificationError(
            f"{module}: current/target capability overlap: {sorted(overlap)}"
        )

    anchors = row.get("sourceAnchors")
    if not isinstance(anchors, list) or not anchors:
        raise VerificationError(f"{module}: at least one source anchor is required")
    for anchor in anchors:
        if not isinstance(anchor, dict):
            raise VerificationError(f"{module}: source anchor must be an object")
        path = root / str(anchor.get("path", ""))
        source = require_text(path)
        for needle in anchor.get("mustContain", []):
            if needle not in source:
                raise VerificationError(
                    f"{module}: source anchor missing {needle!r} in {path}"
                )
        for needle in anchor.get("mustNotContain", []):
            if needle in source:
                raise VerificationError(
                    f"{module}: forbidden current symbol {needle!r} found in {path}"
                )


def require_state(
    by_name: dict[str, dict[str, Any]], module: str, axis: str, expected: str
) -> None:
    observed = by_name[module]["states"][axis]
    if observed != expected:
        raise VerificationError(
            f"{module}: {axis} must be {expected!r}, got {observed!r}"
        )


def validate_module_specific_source(root: Path) -> None:
    wire = require_text(root / "codex-rs/hepta-wire/src/envelope.rs")
    if "const WIRE_VERSION: u16 = 1;" not in wire or "pub fn negotiate" in wire:
        raise VerificationError(
            "platform.wire current source is not the fixed V1 codec described by the matrix"
        )

    operations = require_text(root / "codex-rs/hepta-operations/src/ledger.rs")
    if "In-memory deterministic model" not in operations:
        raise VerificationError(
            "kernel.operations durability class changed without truth update"
        )
    for function in ("mark_indeterminate", "observe_terminal"):
        start = operations.find(f"pub fn {function}")
        if start < 0 or "is_zero()" not in operations[start : start + 900]:
            raise VerificationError(
                f"kernel.operations {function} must reject zero evidence digest"
            )

    authbus = require_text(root / "codex-rs/hepta-authbus/src/lib.rs")
    if (
        "AuthorityPosture::DENY_ALL" not in authbus
        or "BTreeMap<StableId, u64>" not in authbus
    ):
        raise VerificationError(
            "auth.authbus is no longer the documented deny-all process-local replay verifier"
        )
    if "This crate does not verify that signature" not in authbus:
        raise VerificationError(
            "auth.authbus must document that signature_digest is not cryptographic proof"
        )

    migrations = root / "codex-rs/hepta-evidence/migrations"
    observed = sorted(path.name for path in migrations.glob("*.sql"))
    expected = [
        "0001_governance.sql",
        "0002_provider_evidence.sql",
        "0003_provider_host_binding.sql",
        "0004_memory_mutation_shadow.sql",
        "0005_channel_ingress_evidence.sql",
        "0006_provider_ephemeral_input.sql",
        "0007_provider_effect_evidence.sql",
        "0008_provider_effect_ack_source.sql",
    ]
    if observed != expected:
        raise VerificationError(
            f"kernel.evidence migration lineage drift: {observed!r}"
        )


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def git_value(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise VerificationError(f"git {' '.join(args)} failed: {error}") from error
    return result.stdout.strip()


def write_receipt(output: Path, expected_sha: str | None) -> None:
    matrix = read_json(MATRIX_PATH)
    validate_matrix(matrix)
    source_sha = git_value("rev-parse", "HEAD")
    if expected_sha is not None and source_sha != expected_sha:
        raise VerificationError(
            f"exact source mismatch: expected {expected_sha}, got {source_sha}"
        )
    receipt = {
        "schemaVersion": 1,
        "lane": "LANE-A-FOUNDATION",
        "sourceSha": source_sha,
        "sourceTree": git_value("rev-parse", "HEAD^{tree}"),
        "matrixSha256": hashlib.sha256(canonical_bytes(matrix)).hexdigest(),
        "moduleCoverage": len(EXPECTED_MODULES),
        "repositoryControlledDocumentationGaps": "closed",
        "currentImplementationTruth": "closed",
        "productionImplementation": "not_claimed",
        "productionActivation": "not_claimed",
        "externalAcceptance": "not_claimed",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def self_test() -> None:
    matrix = read_json(MATRIX_PATH)
    validate_matrix(matrix)

    bad = deepcopy(matrix)
    bad["modules"][3]["states"]["durability"] = "durable"
    try:
        validate_matrix(bad)
    except VerificationError:
        pass
    else:
        raise VerificationError(
            "self-test failed to reject false operations durability"
        )

    bad = deepcopy(matrix)
    bad["closure"]["externalAcceptance"] = "closed"
    try:
        validate_matrix(bad)
    except VerificationError:
        pass
    else:
        raise VerificationError("self-test failed to reject forged external acceptance")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("verify")
    subparsers.add_parser("self-test")
    receipt = subparsers.add_parser("receipt")
    receipt.add_argument("--output", type=Path, required=True)
    receipt.add_argument("--expected-sha")
    args = parser.parse_args(argv)

    try:
        if args.command == "verify":
            validate_matrix(read_json(MATRIX_PATH))
        elif args.command == "self-test":
            self_test()
        elif args.command == "receipt":
            write_receipt(args.output, args.expected_sha)
        else:
            raise VerificationError(f"unsupported command {args.command}")
    except VerificationError as error:
        print(f"lane-a-foundation verification failed: {error}", file=sys.stderr)
        return 1
    print(f"lane-a-foundation {args.command}: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
