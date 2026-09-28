"""Verify externally governed production evidence without activating the module."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time

from .production_adapters import (
    OpenSslPublicKeyTrustStore,
    PublicKeyBinding,
    load_external_receipts,
    verify_external_production_bundle,
)

_SCHEMA = "hepta.control-engineering-production-acceptance-verification.v1"


def _unique_pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_bindings(path: Path) -> dict[tuple[str, str], PublicKeyBinding]:
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs)
    if not isinstance(value, list) or not value:
        raise ValueError("public key manifest must be a nonempty array")
    result: dict[tuple[str, str], PublicKeyBinding] = {}
    for row in value:
        if not isinstance(row, dict):
            raise ValueError("invalid public key manifest row")
        issuer = row.get("issuer")
        identity = row.get("signingIdentity")
        public_key_path = row.get("publicKeyPath")
        algorithm = row.get("algorithm")
        if not all(isinstance(item, str) and item for item in (issuer, identity, public_key_path, algorithm)):
            raise ValueError("invalid public key manifest row")
        key = (issuer, identity)
        if key in result:
            raise ValueError("duplicate public key identity")
        result[key] = PublicKeyBinding(public_key_path, algorithm)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipts", required=True, type=Path)
    parser.add_argument("--public-keys", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--target-digest", required=True)
    parser.add_argument("--now-ns", type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        trust = OpenSslPublicKeyTrustStore(_load_bindings(args.public_keys))
        receipts = load_external_receipts(args.receipts)
        decision = verify_external_production_bundle(
            receipts,
            trust,
            expected_source_commit=args.source_commit,
            expected_source_tree=args.source_tree,
            expected_target_digest=args.target_digest,
            now_ns=time.time_ns() if args.now_ns is None else args.now_ns,
        )
        value = {
            "schema": _SCHEMA,
            "decision": asdict(decision),
            "productionImplementationChanged": False,
            "activationPerformed": False,
            "releasePerformed": False,
        }
    except (OSError, ValueError) as error:
        print(json.dumps({"schema": _SCHEMA, "status": "rejected", "error": str(error)}))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
