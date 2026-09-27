#!/usr/bin/env python3
"""Bind source-head and deterministic synthetic-merge native receipts.

This pairing step is deliberately external to committed documentation: it can
bind the exact source and synthetic merge commits without a self-referential
hash.  It grants no activation, acceptance, promotion, or release authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

REQUIRED_IDENTITY_FIELDS = {
    "role",
    "commitSha",
    "treeSha",
    "toolchain",
    "os",
    "architecture",
    "dependencyLockSha256",
    "providerBinarySha256",
    "providerSourceCommit",
    "providerEvidenceSha256",
    "manifestSha256",
}
SHARED_DIGEST_FIELDS = (
    "dependencyLockSha256",
    "providerBinarySha256",
    "providerSourceCommit",
    "providerEvidenceSha256",
    "manifestSha256",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_receipt(path: Path, role: str) -> tuple[dict, list[str]]:
    failures: list[str] = []
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {}, [f"{role} receipt unreadable: {error}"]
    if receipt.get("schema") != "hepta.secrets-native-feedback.v2":
        failures.append(f"{role} receipt schema mismatch")
    identity = receipt.get("candidateIdentity")
    if not isinstance(identity, dict):
        failures.append(f"{role} candidate identity missing")
        return receipt, failures
    missing = sorted(REQUIRED_IDENTITY_FIELDS.difference(identity))
    if missing:
        failures.append(f"{role} identity fields missing: {', '.join(missing)}")
    if identity.get("role") != role:
        failures.append(f"{role} identity role mismatch")
    if not receipt.get("identityClean"):
        failures.append(f"{role} candidate identity was not clean")
    if not receipt.get("passed"):
        failures.append(f"{role} native qualification did not pass")
    if receipt.get("productionExecutionProved"):
        failures.append(f"{role} receipt overclaims production execution")
    if receipt.get("independentAcceptance") or receipt.get("releaseAuthority"):
        failures.append(f"{role} receipt overclaims acceptance or release authority")
    return receipt, failures


def paired_receipt(
    source_path: Path,
    merge_path: Path,
    expected_source_sha: str,
) -> tuple[dict, list[str]]:
    source, failures = load_receipt(source_path, "source-head")
    merge, merge_failures = load_receipt(merge_path, "synthetic-merge")
    failures.extend(merge_failures)
    source_identity = source.get("candidateIdentity", {})
    merge_identity = merge.get("candidateIdentity", {})

    if source_identity.get("commitSha") != expected_source_sha:
        failures.append("source receipt does not bind the expected pull-request head")
    for label, value in (
        ("source commit", source_identity.get("commitSha")),
        ("source tree", source_identity.get("treeSha")),
        ("synthetic merge commit", merge_identity.get("commitSha")),
        ("synthetic merge tree", merge_identity.get("treeSha")),
    ):
        if not isinstance(value, str) or len(value) != 40:
            failures.append(f"{label} is not a full Git object identity")

    shared: dict[str, object] = {}
    for field in SHARED_DIGEST_FIELDS:
        source_value = source_identity.get(field)
        merge_value = merge_identity.get(field)
        if source_value != merge_value:
            failures.append(f"paired identity mismatch for {field}")
        shared[field] = source_value

    receipt = {
        "schema": "hepta.secrets-native-paired-attestation.v1",
        "sourceCommitSha": source_identity.get("commitSha"),
        "sourceTreeSha": source_identity.get("treeSha"),
        "syntheticMergeSha": merge_identity.get("commitSha"),
        "syntheticMergeTreeSha": merge_identity.get("treeSha"),
        "toolchain": {
            "sourceHead": source_identity.get("toolchain"),
            "syntheticMerge": merge_identity.get("toolchain"),
        },
        "os": {
            "sourceHead": source_identity.get("os"),
            "syntheticMerge": merge_identity.get("os"),
        },
        "architecture": {
            "sourceHead": source_identity.get("architecture"),
            "syntheticMerge": merge_identity.get("architecture"),
        },
        **shared,
        "sourceReceiptSha256": sha256_file(source_path),
        "syntheticMergeReceiptSha256": sha256_file(merge_path),
        "passed": not failures,
        "failures": failures,
        "providerDynamicE2E": False,
        "productionExecutionProved": False,
        "independentAcceptance": False,
        "releaseAuthority": False,
    }
    return receipt, failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--merge", type=Path, required=True)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    receipt, failures = paired_receipt(
        args.source, args.merge, args.expected_source_sha
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
