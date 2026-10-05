"""Verify externally governed production evidence without activating the module."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
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


def _normalized_public_key_digest(path: Path) -> str:
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise ValueError("public key path must be an absolute regular file")
    try:
        result = subprocess.run(
            [
                "/usr/bin/openssl",
                "pkey",
                "-pubin",
                "-in",
                str(path),
                "-outform",
                "DER",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError("public key normalization failed") from error
    if result.returncode != 0 or not result.stdout or len(result.stdout) > 1_048_576:
        raise ValueError("public key normalization failed")
    return hashlib.sha256(result.stdout).hexdigest()


def _load_bindings(path: Path) -> dict[tuple[str, str], PublicKeyBinding]:
    if not path.is_file() or path.is_symlink():
        raise ValueError("public key manifest must be a regular file")
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs)
    if not isinstance(value, list) or not value:
        raise ValueError("public key manifest must be a nonempty array")
    result: dict[tuple[str, str], PublicKeyBinding] = {}
    fingerprints: dict[str, tuple[str, str]] = {}
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
        key_path = Path(public_key_path)
        fingerprint = _normalized_public_key_digest(key_path)
        reused_by = fingerprints.get(fingerprint)
        if reused_by is not None:
            raise ValueError(
                "public key material reused across identities: "
                f"{reused_by[0]}/{reused_by[1]} and {issuer}/{identity}"
            )
        fingerprints[fingerprint] = key
        result[key] = PublicKeyBinding(str(key_path), algorithm)
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
