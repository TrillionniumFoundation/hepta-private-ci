#!/usr/bin/env python3
"""Check target-storage receipt structure without authenticating its claims.

Source qualification may run without a target receipt and then emits an
explicitly unqualified status. Promotion/release callers must pass
`--require-qualified`; without an independently governed signature verifier and
retained-evidence verification it always fails closed. A signedAttestation
boolean, named reviewers and syntactically valid digests are untrusted claims.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SCHEMA = "hepta.secrets-target-storage-acceptance.v1"
UNSAFE_FILESYSTEMS = {
    "9p", "afs", "cifs", "ceph", "fuse", "fuseblk", "gcsfuse", "glusterfs",
    "nfs", "nfs4", "overlay", "s3fs", "smb3", "sshfs", "virtiofs",
}
REQUIRED_TESTS = {
    "wal",
    "fsync",
    "byte_range_locking",
    "disk_full",
    "inode_full",
    "power_loss",
    "snapshot_restore",
    "container_restart",
    "node_migration",
    "corruption_detection",
}
REQUIRED_REVIEW_ROLES = {
    "secrets_security",
    "sqlite_storage",
    "product_caller",
    "operations_sre",
}
AUTHENTICATION_BLOCKER = (
    "independent authentication is unavailable: receipt claims, evidence digests "
    "and reviewer attestations have not been verified against a trusted authority"
)


def is_hex(value: object, length: int) -> bool:
    return isinstance(value, str) and len(value) == length and value != "0" * length and all(
        char in "0123456789abcdef" for char in value
    )


def nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def evaluate_structure(receipt: dict[str, Any], expected_source_sha: str) -> tuple[bool, list[str]]:
    """Check a claimed acceptance structure; this result grants no qualification."""
    errors: list[str] = []
    if receipt.get("schema") != SCHEMA:
        errors.append("unexpected schema")
    if not is_hex(expected_source_sha, 40) or receipt.get("sourceHeadSha") != expected_source_sha:
        errors.append("sourceHeadSha does not match exact candidate")
    if not is_hex(receipt.get("sourceTreeSha"), 40):
        errors.append("sourceTreeSha must be a full Git tree ID")

    target_id = receipt.get("targetId")
    if not nonempty(target_id):
        errors.append("targetId is required")
    elif any(token in target_id.lower() for token in ("github-runner", "ci-local", "test-fixture")):
        errors.append("CI-local target cannot qualify production storage")

    for field in ("platform", "nodeType", "volumeType", "filesystem", "databasePath"):
        if not nonempty(receipt.get(field)):
            errors.append(f"{field} is required")
    filesystem = str(receipt.get("filesystem", "")).strip().lower()
    if filesystem in UNSAFE_FILESYSTEMS:
        errors.append(f"filesystem {filesystem!r} is not an accepted local-locking profile")
    database_path = receipt.get("databasePath")
    if isinstance(database_path, str) and not database_path.startswith("/"):
        errors.append("databasePath must be absolute")
    mount_options = receipt.get("mountOptions")
    if not isinstance(mount_options, list) or not mount_options or not all(nonempty(item) for item in mount_options):
        errors.append("mountOptions must be a non-empty string list")

    tests = receipt.get("tests")
    passed_tests = False
    if not isinstance(tests, dict) or set(tests) != REQUIRED_TESTS:
        errors.append("storage test set is incomplete or contains unknown tests")
    else:
        passed_tests = True
        for name, result in tests.items():
            if not isinstance(result, dict):
                errors.append(f"{name}: test result must be an object")
                passed_tests = False
                continue
            if result.get("passed") is not True:
                errors.append(f"{name}: test did not pass")
                passed_tests = False
            if not is_hex(result.get("evidenceSha256"), 64):
                errors.append(f"{name}: evidenceSha256 is invalid")
                passed_tests = False

    reviewers = receipt.get("independentReviewers")
    reviewer_roles: set[str] = set()
    principals: set[str] = set()
    reviewers_valid = True
    if not isinstance(reviewers, list):
        errors.append("independentReviewers must be a list")
        reviewers_valid = False
    else:
        for reviewer in reviewers:
            if not isinstance(reviewer, dict):
                reviewers_valid = False
                errors.append("reviewer entry must be an object")
                continue
            role = reviewer.get("role")
            principal = reviewer.get("principal")
            reviewer_roles.add(str(role))
            normalized_principal = principal.strip() if isinstance(principal, str) else ""
            if not normalized_principal or normalized_principal in principals:
                reviewers_valid = False
                errors.append("review principals must be non-empty and distinct")
            else:
                principals.add(normalized_principal)
            if not is_hex(reviewer.get("attestationSha256"), 64):
                reviewers_valid = False
                errors.append(f"{role}: reviewer attestation digest is invalid")
        if reviewer_roles != REQUIRED_REVIEW_ROLES:
            reviewers_valid = False
            errors.append("all required independent review roles must attest")

    signed = receipt.get("signedAttestation") is True
    operator = receipt.get("operatorAccepted") is True
    computed = not errors and passed_tests and reviewers_valid and signed and operator
    if receipt.get("targetStorageProfileQualified") is not computed:
        errors.append("targetStorageProfileQualified does not equal computed evidence state")
        computed = False
    return computed, errors


def evaluate_receipt(receipt: dict[str, Any], expected_source_sha: str) -> tuple[bool, list[str]]:
    """Fail closed: structural completeness cannot authenticate external evidence."""
    _, errors = evaluate_structure(receipt, expected_source_sha)
    return False, [*errors, AUTHENTICATION_BLOCKER]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--require-qualified", action="store_true")
    args = parser.parse_args()

    if not is_hex(args.expected_source_sha, 40):
        parser.error("expected source SHA must be 40 lowercase hexadecimal characters")

    status: dict[str, Any]
    exit_code = 0
    if args.receipt is None:
        status = {
            "schema": "hepta.secrets-target-storage-gate.v1",
            "sourceHeadSha": args.expected_source_sha,
            "receiptPresent": False,
            "receiptStructureComplete": False,
            "independentAuthenticationVerified": False,
            "targetStorageProfileQualified": False,
            "errors": ["no target storage acceptance receipt supplied"],
        }
        if args.require_qualified:
            exit_code = 1
    else:
        try:
            receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            status = {
                "schema": "hepta.secrets-target-storage-gate.v1",
                "sourceHeadSha": args.expected_source_sha,
                "receiptPresent": False,
                "receiptStructureComplete": False,
                "independentAuthenticationVerified": False,
                "targetStorageProfileQualified": False,
                "errors": [f"cannot read receipt: {error}"],
            }
            exit_code = 1
        else:
            if not isinstance(receipt, dict):
                structure_complete, structure_errors = False, ["receipt must be a JSON object"]
                qualified, errors = False, ["receipt must be a JSON object"]
            else:
                structure_complete, structure_errors = evaluate_structure(receipt, args.expected_source_sha)
                qualified, errors = evaluate_receipt(receipt, args.expected_source_sha)
            status = {
                "schema": "hepta.secrets-target-storage-gate.v1",
                "sourceHeadSha": args.expected_source_sha,
                "receiptPresent": True,
                "receiptPath": str(args.receipt),
                "receiptStructureComplete": structure_complete,
                "independentAuthenticationVerified": False,
                "targetStorageProfileQualified": qualified,
                "errors": errors,
            }
            if structure_errors or (args.require_qualified and not qualified):
                exit_code = 1

    status["validationReasons"] = status["errors"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(status, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
