#!/usr/bin/env python3
"""Extend the V2 qualification receipt with wire and canonical status evidence."""

from __future__ import annotations

import json
import pathlib
import shutil

import memory_federation_attestation as base

base.QUALIFIED_PATHS = (
    *base.QUALIFIED_PATHS,
    "codex-rs/hepta-memory-federation-wire",
    "scripts/memory_federation_full_attestation.py",
    "scripts/memory_federation_execution_guard.py",
    "scripts/verify_memory_federation_implementation.py",
    "scripts/verify_memory_federation_status.py",
    "scripts/run_memory_federation_qualification.sh",
)

# This is the executable command contract, in the same order as the read-only
# qualification script.  The execution guard hashes this tuple before and after
# the matrix, so changing either the source or the declared commands invalidates
# the run rather than silently inheriting an earlier receipt.
base.COMMANDS = (
    "python3 -m py_compile scripts/memory_federation_attestation.py "
    "scripts/memory_federation_full_attestation.py "
    "scripts/memory_federation_execution_guard.py "
    "scripts/verify_memory_federation_implementation.py "
    "scripts/verify_memory_federation_status.py",
    "python3 scripts/memory_federation_execution_guard.py self-test",
    "python3 scripts/memory_federation_execution_guard.py capture "
    "--state <guard-state> --expected-sha <tested-sha> --expected-tree <tested-tree>",
    "python3 scripts/verify_memory_federation_status.py verify",
    "python3 scripts/verify_memory_federation_implementation.py "
    "--expected-sha <tested-sha> --expected-tree <tested-tree>",
    "cargo fmt -p codex-hepta-memory-federation -p codex-hepta-memory "
    "-p codex-hepta-memory-extension -p codex-hepta-agentd -p codex-app-server -- --check",
    "cargo test -p codex-hepta-memory-federation --lib",
    "cargo test -p codex-hepta-memory-federation --lib --features legacy-v1",
    "cargo test -p codex-hepta-memory --lib cognitive_runtime_tests",
    "cargo test -p codex-hepta-memory --lib cognitive_federation_tests",
    "cargo test -p codex-hepta-memory-extension --lib cognitive::federation",
    "cargo check -p codex-hepta-agentd -p codex-app-server",
    "cargo clippy -p codex-hepta-memory-federation -p codex-hepta-memory "
    "-p codex-hepta-memory-extension -p codex-app-server --all-targets -- -D warnings",
    "cargo clippy -p codex-hepta-memory-federation --all-targets --features legacy-v1 -- -D warnings",
    "cargo clippy -p codex-hepta-agentd --lib -- -D warnings",
    "cargo fmt --manifest-path codex-rs/hepta-memory-federation-wire/Cargo.toml -- --check",
    "cargo metadata --manifest-path codex-rs/hepta-memory-federation-wire/Cargo.toml "
    "--format-version 1 --no-deps",
    "cargo test --manifest-path codex-rs/hepta-memory-federation-wire/Cargo.toml --lib",
    "cargo test --manifest-path codex-rs/hepta-memory-federation-wire/Cargo.toml --doc",
    "cargo clippy --manifest-path codex-rs/hepta-memory-federation-wire/Cargo.toml "
    "--all-targets -- -D warnings",
    "git diff --check",
    "test -z \"$(git status --porcelain --untracked-files=no)\"",
    "python3 scripts/memory_federation_execution_guard.py verify "
    "--state <guard-state> --expected-sha <tested-sha> --expected-tree <tested-tree>",
)

_WIRE_LOCK = pathlib.Path("codex-rs/hepta-memory-federation-wire/Cargo.lock")
_CAPABILITY_STATE = pathlib.Path("docs/modules/memory.federation/CAPABILITY_STATE.json")
_ORIGINAL_EMIT_PAYLOAD = base.emit_payload
_ORIGINAL_VERIFY_PAYLOAD = base._verify_payload


def _require_capability_state(value) -> dict:
    if not isinstance(value, dict):
        raise base.AttestationError("capability state must be a JSON object")
    if (
        value.get("schema") != "hepta.memory-federation.capability-state.v1"
        or value.get("schemaVersion") != 1
        or value.get("module") != "memory.federation"
    ):
        raise base.AttestationError("capability state identity mismatch")
    claims = value.get("claims")
    if not isinstance(claims, dict):
        raise base.AttestationError("capability-state claims are missing")
    for field in (
        "productionImplementation",
        "productExecutionProved",
        "independentAcceptance",
        "activation",
        "promotion",
        "release",
    ):
        if claims.get(field) is not False:
            raise base.AttestationError(
                f"capability-state claim {field} must remain false in a qualification payload"
            )
    return value


def _emit_payload_with_full_evidence(args):
    result = _ORIGINAL_EMIT_PAYLOAD(args)
    output = pathlib.Path(args.output)
    attestation_path = output / "attestation.json"
    attestation = base._read_json(attestation_path)
    evidence = base._require_mapping("evidence", attestation.get("evidence"))

    if not _CAPABILITY_STATE.is_file():
        raise base.AttestationError("canonical capability state is missing")
    capability_copy = output / "capability-state.json"
    shutil.copyfile(_CAPABILITY_STATE, capability_copy)
    _require_capability_state(json.loads(capability_copy.read_text(encoding="utf-8")))
    evidence["capabilityState"] = capability_copy.name
    evidence["capabilityStateSha256"] = base._sha256_bytes(capability_copy.read_bytes())

    if _WIRE_LOCK.is_file():
        copied_lock = output / "wire-Cargo.lock"
        shutil.copyfile(_WIRE_LOCK, copied_lock)
        evidence["wireCargoLock"] = copied_lock.name
        evidence["wireCargoLockSha256"] = base._sha256_bytes(copied_lock.read_bytes())

    digest = base._write_json(attestation_path, attestation)
    (output / "attestation.sha256").write_text(
        f"{digest}  attestation.json\n", encoding="utf-8"
    )
    return result


def _verify_payload_with_full_evidence(path, value):
    document = _ORIGINAL_VERIFY_PAYLOAD(path, value)
    evidence = base._require_mapping("evidence", document.get("evidence"))

    capability_path = base._resolve_evidence_file(path, evidence.get("capabilityState"))
    capability_digest = base._require_hex(
        "evidence.capabilityStateSha256",
        evidence.get("capabilityStateSha256"),
        base._SHA256_RE,
    )
    if base._sha256_bytes(capability_path.read_bytes()) != capability_digest:
        raise base.AttestationError("capability-state evidence digest mismatch")
    _require_capability_state(json.loads(capability_path.read_text(encoding="utf-8")))
    if not _CAPABILITY_STATE.is_file() or base._sha256_bytes(
        _CAPABILITY_STATE.read_bytes()
    ) != capability_digest:
        raise base.AttestationError(
            "capability-state evidence does not match the qualified checkout"
        )

    lock_path_value = evidence.get("wireCargoLock")
    lock_digest_value = evidence.get("wireCargoLockSha256")
    if (lock_path_value is None) != (lock_digest_value is None):
        raise base.AttestationError(
            "wire Cargo.lock evidence requires both a path and SHA-256 digest"
        )
    if lock_path_value is not None:
        lock_path = base._resolve_evidence_file(path, lock_path_value)
        lock_digest = base._require_hex(
            "evidence.wireCargoLockSha256",
            lock_digest_value,
            base._SHA256_RE,
        )
        if base._sha256_bytes(lock_path.read_bytes()) != lock_digest:
            raise base.AttestationError("wire Cargo.lock evidence digest mismatch")
        lock_text = lock_path.read_text(encoding="utf-8")
        if not lock_text.startswith("# This file is automatically @generated by Cargo."):
            raise base.AttestationError("wire Cargo.lock evidence is not a Cargo lockfile")
    return document


base.emit_payload = _emit_payload_with_full_evidence
base._verify_payload = _verify_payload_with_full_evidence


if __name__ == "__main__":
    raise SystemExit(base.main())
