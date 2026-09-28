#!/usr/bin/env python3
"""Verify external storage-owner observations for one cognitive deletion plan.

A read-only extension of the existing trusted-host ceremony, not another fact
store or eraser. Only public keys are accepted. This code never signs plans,
opens SQLite, deletes files, calls providers, or authorizes model unlearning.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time
import uuid

CLASSES = frozenset({"active_sqlite", "wal_journal", "retired_generations", "backups",
                     "cold_segments", "caches", "exports", "derived_artifacts", "trained_parameters"})
DOMAIN = b"hepta.cognitive.lifecycle-observation.v1\0"
ID = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
HEX = re.compile(r"[0-9a-f]{64}\Z")
MAX_OBLIGATIONS = 128
MAX_INPUT_BYTES = 256 * 1024


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def exact(value: dict, keys: set[str]) -> None:
    require(isinstance(value, dict) and set(value) == keys, "unknown or missing critical field")


def identifier(value: str) -> None:
    require(isinstance(value, str) and ID.fullmatch(value) is not None, "invalid bounded identity")


def digest(value: str) -> None:
    require(isinstance(value, str) and HEX.fullmatch(value) is not None, "invalid SHA-256")


def integer(value: int, minimum: int = 1) -> None:
    require(type(value) is int and minimum <= value <= (1 << 63) - 1, "invalid bounded integer")


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def sha256(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def signing_bytes(envelope: dict) -> bytes:
    return DOMAIN + canonical({key: envelope[key] for key in ("payload", "signer_id", "key_epoch")})


def verify_signature(envelope: dict, signer: dict) -> dict:
    exact(envelope, {"payload", "signer_id", "key_epoch", "signature_hex"})
    identifier(envelope["signer_id"])
    integer(envelope["key_epoch"])
    require(envelope["signer_id"] == signer["signer_id"] and envelope["key_epoch"] == signer["key_epoch"],
            "signer or key epoch mismatch")
    require(signer["revoked"] is False, "signer revoked")
    signature = envelope["signature_hex"]
    require(isinstance(signature, str) and re.fullmatch(r"[0-9a-f]{128}", signature) is not None,
            "invalid Ed25519 signature encoding")
    data = signing_bytes(envelope)
    require(len(data) <= MAX_INPUT_BYTES, "signed input exceeds bounds")
    # RFC 8410 SubjectPublicKeyInfo for the externally installed Ed25519 key.
    der = bytes.fromhex("302a300506032b6570032100" + signer["public_key_hex"])
    with tempfile.TemporaryDirectory(prefix="cognitive-lifecycle-verify-") as temporary:
        root = Path(temporary)
        (root / "key.der").write_bytes(der)
        (root / "payload").write_bytes(data)
        (root / "signature").write_bytes(bytes.fromhex(signature))
        result = subprocess.run(
            ["openssl", "pkeyutl", "-verify", "-pubin", "-keyform", "DER",
             "-inkey", str(root / "key.der"), "-rawin", "-in", str(root / "payload"),
             "-sigfile", str(root / "signature")],
            capture_output=True, timeout=10, check=False,
        )
    require(result.returncode == 0, "owner signature verification failed or verifier unavailable")
    return envelope["payload"]


def validate_trust(trust: dict, now: int) -> dict[str, dict]:
    exact(trust, {"schema", "revision", "valid_until", "coordinator", "owners"})
    require(trust["schema"] == "hepta.cognitive.lifecycle-trust.v1", "unsupported trust schema")
    integer(trust["revision"])
    integer(trust["valid_until"])
    require(trust["valid_until"] > now, "trust must be current")
    require(isinstance(trust["owners"], list) and 1 <= len(trust["owners"]) <= MAX_OBLIGATIONS,
            "invalid owner trust count")
    signers = {}
    keys = set()
    for signer in [trust["coordinator"], *trust["owners"]]:
        exact(signer, {"signer_id", "key_epoch", "public_key_hex", "revoked"})
        identifier(signer["signer_id"])
        integer(signer["key_epoch"])
        digest(signer["public_key_hex"])
        require(type(signer["revoked"]) is bool, "invalid trust revocation flag")
        require(signer["signer_id"] not in signers and signer["public_key_hex"] not in keys,
                "independent owner/coordinator keys and identities must be distinct")
        keys.add(signer["public_key_hex"])
        signers[signer["signer_id"]] = signer
    return signers


def reconcile(plan_envelope: dict, receipts: list, trust: dict, now: int, expected_plan_sha256: str) -> dict:
    integer(now)
    signers = validate_trust(trust, now)
    plan = verify_signature(plan_envelope, trust["coordinator"])
    exact(plan, {"schema", "request_id", "owner_agent_id", "writer_generation", "cut_sha256",
                 "policy_sha256", "inventory_sha256", "created_at", "obligations"})
    require(plan["schema"] == "hepta.cognitive.lifecycle-plan.v1", "unsupported plan schema")
    identifier(plan["request_id"])
    require(str(uuid.UUID(plan["owner_agent_id"])) == plan["owner_agent_id"], "noncanonical Agent identity")
    integer(plan["writer_generation"])
    integer(plan["created_at"])
    require(plan["created_at"] <= now, "plan is from the future")
    for key in ("cut_sha256", "policy_sha256", "inventory_sha256"):
        digest(plan[key])
    obligations = plan["obligations"]
    require(isinstance(obligations, list) and len(CLASSES) <= len(obligations) <= MAX_OBLIGATIONS,
            "missing or excessive storage obligations")
    expected = {}
    for item in obligations:
        exact(item, {"storage_class", "storage_owner", "requirement", "inventory_sha256"})
        require(item["storage_class"] in CLASSES, "unknown storage class")
        require(item["storage_owner"] in signers and item["storage_owner"] != trust["coordinator"]["signer_id"],
                "storage obligation has no independent owner")
        require(item["requirement"] in {"erase", "unlearn", "not_applicable"}, "unknown lifecycle requirement")
        require(item["requirement"] != "unlearn" or item["storage_class"] == "trained_parameters",
                "unlearning cannot substitute for storage erasure")
        digest(item["inventory_sha256"])
        identity = (item["storage_class"], item["storage_owner"])
        require(identity not in expected, "duplicate storage obligation")
        expected[identity] = item
    require({key[0] for key in expected} == CLASSES, "inventory omits an entire storage class")
    require(isinstance(receipts, list) and len(receipts) <= MAX_OBLIGATIONS, "receipt budget exceeded")
    plan_digest = sha256(plan)
    digest(expected_plan_sha256)
    require(plan_digest == expected_plan_sha256, "plan differs from the host-requested operation")
    observed = {}
    for envelope in receipts:
        require(isinstance(envelope, dict), "invalid receipt envelope")
        signer = signers.get(envelope.get("signer_id"))
        require(signer is not None and signer is not trust["coordinator"], "unknown storage signer")
        receipt = verify_signature(envelope, signer)
        exact(receipt, {"schema", "plan_sha256", "storage_class", "storage_owner", "inventory_sha256",
                        "status", "method", "observed_at", "evidence_sha256"})
        require(receipt["schema"] == "hepta.cognitive.lifecycle-receipt.v1", "unsupported receipt schema")
        require(receipt["plan_sha256"] == plan_digest, "receipt binds another request, cut or policy")
        identity = (receipt["storage_class"], receipt["storage_owner"])
        require(identity in expected and identity not in observed, "unknown or duplicate receipt obligation")
        item = expected[identity]
        require(receipt["storage_owner"] == signer["signer_id"], "receipt signer does not own this storage")
        require(receipt["inventory_sha256"] == item["inventory_sha256"], "receipt covers another inventory")
        integer(receipt["observed_at"])
        require(plan["created_at"] <= receipt["observed_at"] <= now, "stale or future lifecycle receipt")
        digest(receipt["evidence_sha256"])
        identifier(receipt["method"])
        require(receipt["status"] in {"completed", "pending", "indeterminate", "failed"}, "unknown disposition")
        if receipt["status"] == "completed":
            allowed = {"erase": {"physical_storage", "crypto_erasure"},
                       "unlearn": {"parameter_unlearning"}, "not_applicable": {"owner_absence"}}
            require(receipt["method"] in allowed[item["requirement"]],
                    "logical tombstone, revocation or wrong method is not the requested completion")
        observed[identity] = receipt
    results = [{**item, "status": observed.get(key, {}).get("status", "missing"),
                "verified_receipt_sha256": sha256(observed[key]) if key in observed else None}
               for key, item in sorted(expected.items())]
    complete = all(item["status"] == "completed" for item in results)
    return {"schema": "hepta.cognitive.lifecycle-reconciliation.v1", "plan_sha256": plan_digest,
            "trust_sha256": sha256(trust), "observed_at": now, "obligations": results,
            "all_required_owner_receipts_verified": complete,
            "result": "owner_attested_complete" if complete else "incomplete",
            "authorized_effects": False, "physical_erasure_independently_proved": False,
            "target_host_qualified": False}


def no_duplicates(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON field")
        result[key] = value
    return result


def no_float(value: str) -> None:
    raise ValueError("floating point and nonfinite values are not permitted")


def file_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_nlink,
            metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns)


def load_bounded(path: Path) -> object:
    # O_NONBLOCK must precede fstat: opening a substituted FIFO otherwise waits
    # indefinitely before its type can be rejected. Do not silently omit the
    # descriptor primitives on unsupported hosts.
    require(os.name == "posix" and all(hasattr(os, flag) for flag in
            ("O_NOFOLLOW", "O_NONBLOCK", "O_CLOEXEC")),
            "signed-file admission requires the POSIX descriptor profile")
    require(path.is_absolute() and path.resolve(strict=True) == path, "input path must be canonical")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, "input must be a single-link regular file")
        require(not before.st_mode & 0o022, "signed input is group/world writable")
        require(before.st_size <= MAX_INPUT_BYTES, "input exceeds byte budget")
        content = stream.read(MAX_INPUT_BYTES + 1)
        after = os.fstat(stream.fileno())
        # A valid old signature on a retained descriptor is insufficient when
        # the live trust pathname was replaced while that descriptor was read.
        current = path.stat(follow_symlinks=False)
        require(path.resolve(strict=True) == path and
                file_identity(before) == file_identity(after) == file_identity(current),
                "input or its current pathname changed during read")
    require(len(content) <= MAX_INPUT_BYTES, "input exceeds byte budget")
    return json.loads(content, object_pairs_hook=no_duplicates, parse_float=no_float, parse_constant=no_float)


def reconcile_files(plan_path: Path, receipts_path: Path, trust_path: Path,
                    expected_plan_sha256: str, expected_trust_sha256: str) -> dict:
    """Verify historical facts, then reobserve current trust before reporting.

    Signature work may take long enough for trust to expire or be revoked. The
    final read binds the same input set; it never caches an authority decision,
    edits owner receipts, or converts an attestation into independent erasure.
    This is a last-observed report, not a multi-file transaction or effect grant.
    """
    digest(expected_trust_sha256)
    digest(expected_plan_sha256)
    trust = load_bounded(trust_path)
    require(sha256(trust) == expected_trust_sha256,
            "trust differs from independently installed host identity")
    plan_envelope = load_bounded(plan_path)
    receipts = load_bounded(receipts_path)
    started = int(time.time())
    report = reconcile(plan_envelope, receipts, trust, started, expected_plan_sha256)
    require(sha256(load_bounded(plan_path)) == sha256(plan_envelope),
            "signed lifecycle plan changed during verification")
    require(sha256(load_bounded(receipts_path)) == sha256(receipts),
            "lifecycle receipt set changed during verification")
    # Trust is read last, after the potentially expensive crypto and input work.
    # A signature over yesterday's key/epoch is not current trust at final use.
    current_trust = load_bounded(trust_path)
    finished = int(time.time())
    require(finished >= started, "clock regressed during lifecycle verification")
    require(sha256(current_trust) == expected_trust_sha256,
            "lifecycle signer trust changed during verification")
    validate_trust(current_trust, finished)
    report["observed_at"] = finished
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--receipts", required=True, type=Path)
    parser.add_argument("--trusted-owners", required=True, type=Path)
    parser.add_argument("--expected-trust-sha256", required=True)
    parser.add_argument("--expected-plan-sha256", required=True)
    args = parser.parse_args()
    report = reconcile_files(args.plan, args.receipts, args.trusted_owners,
                             args.expected_plan_sha256, args.expected_trust_sha256)
    print(json.dumps(report, sort_keys=True, indent=2))
    if not report["all_required_owner_receipts_verified"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
