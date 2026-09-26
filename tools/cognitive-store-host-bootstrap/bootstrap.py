#!/usr/bin/env python3
"""Authenticate and transition cognitive.store host bootstrap evidence.

The HMAC key authenticates the host-retained current-cut bundle; it is not a
production-authority signing key.  Authority material must already have been
verified by its external issuer.  Raw fencing tokens are never persisted here.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import stat
import tempfile
import time
from pathlib import Path
from typing import Any

SCHEMA = "hepta.cognitive-store-host-bootstrap.v1"
TERMINAL = {"revoked", "indeterminate", "rolled_back"}
ALLOWED = {
    "prepared": {"active", "revoked", "indeterminate"},
    "active": {"prepared", "revoked", "indeterminate", "rollback_prepared"},
    "rollback_prepared": {"rolled_back", "revoked", "indeterminate"},
    "revoked": set(),
    "indeterminate": {"rollback_prepared"},
    "rolled_back": set(),
}


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def load_key(path: Path) -> bytes:
    st = path.stat()
    if os.name == "posix" and stat.S_IMODE(st.st_mode) & 0o077:
        raise ValueError("host bootstrap key must not be group/world accessible")
    key = path.read_bytes()
    if not 32 <= len(key) <= 4096:
        raise ValueError("host bootstrap key must contain 32..=4096 bytes")
    return key


def sign(payload: dict[str, Any], key: bytes) -> str:
    return hmac.new(key, canonical(payload), hashlib.sha256).hexdigest()


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, pending = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            os.unlink(pending)
        except FileNotFoundError:
            pass


def validate_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(f"{label} must be lowercase SHA-256")
    return value


def validate_anchor(anchor: dict[str, Any], owner: str) -> None:
    required = {"profile", "owner_agent_id", "schema_digest", "state_digest"}
    if set(anchor) != required or anchor["owner_agent_id"] != owner:
        raise ValueError("recovery anchor is incomplete or belongs to another owner")
    validate_sha(anchor["schema_digest"], "anchor schema digest")
    validate_sha(anchor["state_digest"], "anchor state digest")


def validate_authority(authority: dict[str, Any], owner: str, now: int) -> None:
    required = {
        "agent_id",
        "grant_digest",
        "authority_epoch",
        "owner_epoch",
        "lease_expires_at_unix_seconds",
        "fencing_token_digest",
        "issuer_receipt_digest",
    }
    if set(authority) != required or authority["agent_id"] != owner:
        raise ValueError("authority receipt is incomplete or belongs to another owner")
    for field in ("grant_digest", "fencing_token_digest", "issuer_receipt_digest"):
        validate_sha(authority[field], field)
    if type(authority["authority_epoch"]) is not int or authority["authority_epoch"] <= 0:
        raise ValueError("authority epoch must be positive")
    if type(authority["owner_epoch"]) is not int or authority["owner_epoch"] <= 0:
        raise ValueError("owner epoch must be positive")
    if type(authority["lease_expires_at_unix_seconds"]) is not int or authority["lease_expires_at_unix_seconds"] <= now:
        raise ValueError("authority lease is already expired")


def verify(envelope: dict[str, Any], key: bytes, *, now: int | None = None) -> dict[str, Any]:
    if set(envelope) != {"payload", "signature"} or not isinstance(envelope["payload"], dict):
        raise ValueError("invalid bootstrap envelope")
    payload = envelope["payload"]
    expected = sign(payload, key)
    if not hmac.compare_digest(expected, envelope["signature"]):
        raise ValueError("bootstrap signature mismatch")
    if payload.get("schema") != SCHEMA or payload.get("state") not in ALLOWED:
        raise ValueError("unsupported bootstrap schema/state")
    owner = payload.get("owner_agent_id")
    if not isinstance(owner, str) or not owner:
        raise ValueError("missing owner")
    validate_anchor(payload["recovery_anchor"], owner)
    validate_authority(payload["authority"], owner, int(time.time()) if now is None else now)
    if type(payload.get("writer_generation")) is not int or payload["writer_generation"] <= 0:
        raise ValueError("writer generation must be positive")
    validate_sha(payload["active_pointer_sha256"], "active pointer digest")
    validate_sha(payload["database_sha256"], "database digest")
    predecessor = payload.get("predecessor_bundle_sha256")
    if predecessor is not None:
        validate_sha(predecessor, "predecessor bundle digest")
    return payload


def envelope(payload: dict[str, Any], key: bytes) -> dict[str, Any]:
    return {"payload": payload, "signature": sign(payload, key)}


def prepare(
    *,
    owner: str,
    anchor: dict[str, Any],
    authority: dict[str, Any],
    lease_id: str,
    generation: int,
    pointer_digest: str,
    database_digest: str,
    predecessor: str | None,
    purpose: str = "activate",
    now: int | None = None,
) -> dict[str, Any]:
    observed = int(time.time()) if now is None else now
    validate_anchor(anchor, owner)
    validate_authority(authority, owner, observed)
    if not lease_id or generation <= 0:
        raise ValueError("lease id and positive writer generation are required")
    validate_sha(pointer_digest, "active pointer digest")
    validate_sha(database_digest, "database digest")
    if predecessor is not None:
        validate_sha(predecessor, "predecessor bundle digest")
    return {
        "schema": SCHEMA,
        "state": "prepared" if purpose == "activate" else "rollback_prepared",
        "owner_agent_id": owner,
        "recovery_anchor": anchor,
        "authority": authority,
        "lease_id": lease_id,
        "writer_generation": generation,
        "active_pointer_sha256": pointer_digest,
        "database_sha256": database_digest,
        "predecessor_bundle_sha256": predecessor,
        "canary": None,
        "rollback": None if purpose == "activate" else {"compatibility_digest": None},
        "observation": {"issued_at_unix_seconds": observed},
    }


def transition(
    current: dict[str, Any],
    target: str,
    *,
    details: dict[str, Any],
    now: int | None = None,
) -> dict[str, Any]:
    state = current["state"]
    if target not in ALLOWED[state]:
        raise ValueError(f"illegal bootstrap transition {state!r} -> {target!r}")
    next_payload = json.loads(json.dumps(current))
    next_payload["state"] = target
    next_payload["predecessor_bundle_sha256"] = sha256(current)
    next_payload["observation"] = {
        "observed_at_unix_seconds": int(time.time()) if now is None else now,
        **details,
    }
    if target == "active":
        canary = details.get("canary")
        if not isinstance(canary, dict) or canary.get("status") != "committed":
            raise ValueError("activation requires a committed canary receipt")
        if canary.get("before_state_digest") != current["recovery_anchor"]["state_digest"]:
            raise ValueError("canary predecessor does not match the authenticated current cut")
        if canary.get("after_state_digest") == canary.get("before_state_digest"):
            raise ValueError("canary did not advance the durable cut")
        validate_sha(canary.get("after_state_digest"), "canary successor digest")
        next_payload["canary"] = canary
    if target == "rollback_prepared":
        compatibility = details.get("compatibility_digest")
        validate_sha(compatibility, "rollback compatibility digest")
        next_payload["rollback"] = {"compatibility_digest": compatibility}
    if target in TERMINAL:
        reason = details.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("terminal transition requires a reason")
    return next_payload


def load_verified(path: Path, key: bytes, now: int | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    value = load_json(path)
    return value, verify(value, key, now=now)


def cli() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--key-file", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)

    prepare_p = sub.add_parser("prepare")
    prepare_p.add_argument("--owner", required=True)
    prepare_p.add_argument("--anchor", type=Path, required=True)
    prepare_p.add_argument("--authority", type=Path, required=True)
    prepare_p.add_argument("--lease-id", required=True)
    prepare_p.add_argument("--generation", type=int, required=True)
    prepare_p.add_argument("--active-pointer-sha256", required=True)
    prepare_p.add_argument("--database-sha256", required=True)
    prepare_p.add_argument("--predecessor-bundle-sha256")
    prepare_p.add_argument("--output", type=Path, required=True)

    verify_p = sub.add_parser("verify")
    verify_p.add_argument("--input", type=Path, required=True)
    verify_p.add_argument("--expected-owner")
    verify_p.add_argument("--minimum-generation", type=int, default=1)

    transition_p = sub.add_parser("transition")
    transition_p.add_argument("--input", type=Path, required=True)
    transition_p.add_argument("--target", choices=sorted({state for states in ALLOWED.values() for state in states}), required=True)
    transition_p.add_argument("--details", type=Path, required=True)
    transition_p.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    key = load_key(args.key_file)
    if args.command == "prepare":
        payload = prepare(
            owner=args.owner,
            anchor=load_json(args.anchor),
            authority=load_json(args.authority),
            lease_id=args.lease_id,
            generation=args.generation,
            pointer_digest=args.active_pointer_sha256,
            database_digest=args.database_sha256,
            predecessor=args.predecessor_bundle_sha256,
        )
        atomic_write(args.output, envelope(payload, key))
        print(json.dumps({"state": payload["state"], "bundle_sha256": sha256(payload)}, sort_keys=True))
    elif args.command == "verify":
        _, payload = load_verified(args.input, key)
        if args.expected_owner is not None and payload["owner_agent_id"] != args.expected_owner:
            raise SystemExit("owner mismatch")
        if payload["writer_generation"] < args.minimum_generation:
            raise SystemExit("writer generation below minimum")
        print(json.dumps({"state": payload["state"], "bundle_sha256": sha256(payload)}, sort_keys=True))
    else:
        _, current = load_verified(args.input, key)
        details = load_json(args.details)
        next_payload = transition(current, args.target, details=details)
        if next_payload["writer_generation"] < current["writer_generation"]:
            raise SystemExit("writer generation regressed")
        atomic_write(args.output, envelope(next_payload, key))
        print(json.dumps({"state": next_payload["state"], "bundle_sha256": sha256(next_payload)}, sort_keys=True))


if __name__ == "__main__":
    cli()
