#!/usr/bin/env python3
"""Emit and verify exact-candidate learning.artifacts qualification receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA = "hepta.learning-artifacts.qualification-receipt.v1"
EXPECTED_CHECKS = (
    "closed_world",
    "build",
    "strict_clippy",
    "owner_regression",
    "security",
    "property",
    "boundary_sequence",
    "service_e2e",
    "read_boundary",
    "write_atomicity",
    "snapshot_fallback",
    "format",
)
HEX40 = re.compile(r"^[0-9a-f]{40}$")


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def parse_pairs(values: list[str], label: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        name, separator, payload = value.partition("=")
        if not separator or not name or not payload or name in result:
            raise ValueError(f"invalid or duplicate {label}: {value!r}")
        result[name] = payload
    return result


def require_sha(value: str, label: str) -> None:
    if not HEX40.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase 40-hex Git object id")


def validate_receipt(receipt: dict[str, Any]) -> None:
    if receipt.get("schema") != SCHEMA or receipt.get("schemaVersion") != 1:
        raise ValueError("unexpected qualification receipt schema")
    mode = receipt.get("mode")
    if mode not in {"exact-source", "ordered-parent-merge"}:
        raise ValueError("unexpected qualification receipt mode")
    for field in ("sourceSha", "sourceTree", "candidateSha", "candidateTree"):
        value = receipt.get(field)
        if not isinstance(value, str):
            raise ValueError(f"{field} is missing")
        require_sha(value, field)
    base = receipt.get("baseSha")
    if not isinstance(base, str) or (base and not HEX40.fullmatch(base)):
        raise ValueError("baseSha must be empty or a lowercase 40-hex object id")
    if mode == "exact-source":
        if receipt["sourceSha"] != receipt["candidateSha"]:
            raise ValueError("exact-source candidate SHA differs from source SHA")
        if receipt["sourceTree"] != receipt["candidateTree"]:
            raise ValueError("exact-source candidate tree differs from source tree")
    elif not base:
        raise ValueError("ordered-parent-merge receipt requires baseSha")

    checks = receipt.get("checks")
    if not isinstance(checks, dict) or set(checks) != set(EXPECTED_CHECKS):
        raise ValueError("qualification check set is not closed-world")
    failures = {name: state for name, state in checks.items() if state != "success"}
    if failures:
        raise ValueError(f"qualification contains non-success outcomes: {failures}")

    objects = receipt.get("sourceObjects")
    if not isinstance(objects, dict) or not objects:
        raise ValueError("sourceObjects must be a non-empty object")
    for path, object_id in objects.items():
        if not isinstance(path, str) or not path or not isinstance(object_id, str):
            raise ValueError("invalid source object binding")
        require_sha(object_id, f"source object {path}")

    digest = receipt.get("receiptDigest")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("invalid receiptDigest")
    unsigned = dict(receipt)
    unsigned.pop("receiptDigest", None)
    expected = hashlib.sha256(canonical(unsigned)).hexdigest()
    if digest != expected:
        raise ValueError("qualification receipt digest mismatch")


def emit(args: argparse.Namespace) -> None:
    checks = parse_pairs(args.check, "check")
    objects = parse_pairs(args.source_object, "source object")
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "schemaVersion": 1,
        "module": "learning.artifacts",
        "mode": args.mode,
        "sourceSha": args.source_sha,
        "sourceTree": args.source_tree,
        "baseSha": args.base_sha,
        "candidateSha": args.candidate_sha,
        "candidateTree": args.candidate_tree,
        "checks": dict(sorted(checks.items())),
        "sourceObjects": dict(sorted(objects.items())),
        "claimBoundary": {
            "sourceQualified": True,
            "activation": False,
            "independentAcceptance": False,
            "promotion": False,
            "release": False,
        },
    }
    unsigned = dict(receipt)
    receipt["receiptDigest"] = hashlib.sha256(canonical(unsigned)).hexdigest()
    validate_receipt(receipt)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(json.dumps(receipt, indent=2, sort_keys=True).encode() + b"\n")


def verify(args: argparse.Namespace) -> None:
    value = json.loads(Path(args.receipt).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("receipt must be a JSON object")
    validate_receipt(value)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    sub = root.add_subparsers(dest="command", required=True)
    emit_parser = sub.add_parser("emit")
    emit_parser.add_argument("--mode", required=True)
    emit_parser.add_argument("--source-sha", required=True)
    emit_parser.add_argument("--source-tree", required=True)
    emit_parser.add_argument("--base-sha", default="")
    emit_parser.add_argument("--candidate-sha", required=True)
    emit_parser.add_argument("--candidate-tree", required=True)
    emit_parser.add_argument("--check", action="append", default=[])
    emit_parser.add_argument("--source-object", action="append", default=[])
    emit_parser.add_argument("--output", required=True)
    emit_parser.set_defaults(handler=emit)

    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("receipt")
    verify_parser.set_defaults(handler=verify)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        args.handler(args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"learning.artifacts qualification receipt rejected: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
