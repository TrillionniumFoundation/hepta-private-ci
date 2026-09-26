#!/usr/bin/env python3
"""Qualification-only WAL/checkpoint, sharding and capacity model.

This is an executable reference model for future kernel.authority storage work.
It is deliberately not imported by runtime code and never grants production
implementation, activation, release, or SLO status.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

SCHEMA = "hepta.kernel-authority-storage-model.v1"
MAX_AUTHORITY_LEASES = 16_384
MAX_CAPABILITY_REVOCATIONS = 16_384
MAX_RETIRED_AUTHORITY_LEASE_IDS = 16_384
CHECKPOINT_INTERVAL = 128
SHARD_COUNT = 16


class ModelError(RuntimeError):
    """Raised when the modeled durable state fails closed."""


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".next")
    content = canonical(value) + b"\n"
    with temporary.open("wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    fsync_directory(path.parent)


def append_record(root: Path, sequence: int, previous: str, operation: str) -> str:
    payload = {
        "operation": operation,
        "payloadSha256": sha256_bytes(f"payload:{sequence}:{operation}".encode()),
        "previousRecordSha256": previous,
        "sequence": sequence,
    }
    record_sha256 = sha256_bytes(canonical(payload))
    envelope = {"record": payload, "recordSha256": record_sha256}
    with (root / "journal.jsonl").open("ab") as stream:
        stream.write(canonical(envelope) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    return record_sha256


def checkpoint(root: Path, generation: int, sequence: int, head: str) -> None:
    state = {
        "generation": generation,
        "headRecordSha256": head,
        "sequence": sequence,
        "stateSha256": sha256_bytes(f"state:{sequence}:{head}".encode()),
    }
    checkpoint_path = root / f"checkpoint-{generation}.json"
    atomic_json(checkpoint_path, state)
    manifest = {
        "checkpointPath": checkpoint_path.name,
        "checkpointSha256": sha256_bytes(checkpoint_path.read_bytes()),
        "generation": generation,
    }
    atomic_json(root / "manifest.json", manifest)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ModelError(f"invalid {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise ModelError(f"{path.name} is not an object")
    return value


def recover(root: Path) -> dict[str, Any]:
    manifest = read_json(root / "manifest.json")
    expected_manifest_fields = {"checkpointPath", "checkpointSha256", "generation"}
    if set(manifest) != expected_manifest_fields:
        raise ModelError("manifest fields drifted")
    checkpoint_path = root / str(manifest["checkpointPath"])
    checkpoint_bytes = checkpoint_path.read_bytes()
    if sha256_bytes(checkpoint_bytes) != manifest["checkpointSha256"]:
        raise ModelError("checkpoint digest mismatch")
    state = read_json(checkpoint_path)
    if set(state) != {
        "generation",
        "headRecordSha256",
        "sequence",
        "stateSha256",
    }:
        raise ModelError("checkpoint fields drifted")
    if state["generation"] != manifest["generation"]:
        raise ModelError("checkpoint generation mismatch")
    sequence = int(state["sequence"])
    head = str(state["headRecordSha256"])
    journal = (root / "journal.jsonl").read_bytes()
    lines = journal.splitlines(keepends=True)
    discarded_partial_tail = False
    if lines and not lines[-1].endswith(b"\n"):
        lines.pop()
        discarded_partial_tail = True
    for index, line in enumerate(lines, start=1):
        try:
            envelope = json.loads(line)
        except json.JSONDecodeError as error:
            raise ModelError(f"committed journal record {index} is invalid") from error
        if not isinstance(envelope, dict) or set(envelope) != {
            "record",
            "recordSha256",
        }:
            raise ModelError(f"journal record {index} fields drifted")
        record = envelope["record"]
        if not isinstance(record, dict) or set(record) != {
            "operation",
            "payloadSha256",
            "previousRecordSha256",
            "sequence",
        }:
            raise ModelError(f"journal payload {index} fields drifted")
        record_sequence = int(record["sequence"])
        if record_sequence <= sequence:
            continue
        if record_sequence != sequence + 1:
            raise ModelError("journal sequence gap")
        if record["previousRecordSha256"] != head:
            raise ModelError("journal hash-chain mismatch")
        expected_digest = sha256_bytes(canonical(record))
        if envelope["recordSha256"] != expected_digest:
            raise ModelError("journal record digest mismatch")
        sequence = record_sequence
        head = expected_digest
    return {
        "discardedPartialTail": discarded_partial_tail,
        "headRecordSha256": head,
        "sequence": sequence,
    }


def build_model(root: Path, operations: int) -> tuple[int, str]:
    root.mkdir(parents=True, exist_ok=True)
    (root / "journal.jsonl").write_bytes(b"")
    head = "0" * 64
    generation = 0
    checkpoint(root, generation, 0, head)
    for sequence in range(1, operations + 1):
        operation = ("put", "dispatch", "revoke", "prune")[sequence % 4]
        head = append_record(root, sequence, head, operation)
        if sequence % CHECKPOINT_INTERVAL == 0 and sequence != operations:
            generation += 1
            checkpoint(root, generation, sequence, head)
    return operations, head


def copy_model(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination)


def corruption_drills(root: Path, operations: int, expected_head: str) -> dict[str, bool]:
    baseline = recover(root)
    baseline_ok = (
        baseline["sequence"] == operations
        and baseline["headRecordSha256"] == expected_head
    )

    torn = root.parent / "torn-tail"
    copy_model(root, torn)
    with (torn / "journal.jsonl").open("ab") as stream:
        stream.write(b'{"record":')
        stream.flush()
        os.fsync(stream.fileno())
    torn_recovery = recover(torn)
    torn_tail_ok = (
        torn_recovery["sequence"] == operations
        and torn_recovery["discardedPartialTail"] is True
    )

    corrupted = root.parent / "corrupted-record"
    copy_model(root, corrupted)
    journal = bytearray((corrupted / "journal.jsonl").read_bytes())
    pivot = journal.rfind(b'"payloadSha256":"')
    if pivot < 0:
        raise ModelError("cannot find committed record to corrupt")
    value_index = pivot + len(b'"payloadSha256":"')
    journal[value_index] = ord("0") if journal[value_index] != ord("0") else ord("1")
    (corrupted / "journal.jsonl").write_bytes(journal)
    corrupted_record_rejected = False
    try:
        recover(corrupted)
    except ModelError:
        corrupted_record_rejected = True

    rolled_back = root.parent / "rolled-back-checkpoint"
    copy_model(root, rolled_back)
    manifest = read_json(rolled_back / "manifest.json")
    checkpoint_path = rolled_back / str(manifest["checkpointPath"])
    checkpoint_bytes = bytearray(checkpoint_path.read_bytes())
    checkpoint_bytes[-2] = ord("0") if checkpoint_bytes[-2] != ord("0") else ord("1")
    checkpoint_path.write_bytes(checkpoint_bytes)
    rollback_rejected = False
    try:
        recover(rolled_back)
    except ModelError:
        rollback_rejected = True

    return {
        "baselineRecovery": baseline_ok,
        "committedRecordCorruptionRejected": corrupted_record_rejected,
        "partialTailDiscarded": torn_tail_ok,
        "rolledBackCheckpointRejected": rollback_rejected,
    }


def shard_for(owner_id: str, lease_id: str) -> int:
    digest = hashlib.sha256(f"{owner_id}\0{lease_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % SHARD_COUNT


def sharding_model(operations: int) -> dict[str, Any]:
    counts = [0] * SHARD_COUNT
    stable = True
    for index in range(max(operations, 1_024)):
        lease_id = f"lease-{index}"
        first = shard_for("authority-owner", lease_id)
        second = shard_for("authority-owner", lease_id)
        stable = stable and first == second
        counts[first] += 1
    minimum = min(counts)
    maximum = max(counts)
    return {
        "deterministic": stable,
        "shardCount": SHARD_COUNT,
        "minimumAssignments": minimum,
        "maximumAssignments": maximum,
        "maxToMinRatioPpm": (maximum * 1_000_000) // max(1, minimum),
    }


def capacity_model() -> dict[str, Any]:
    profiles = {
        "low": {"leasesPerHour": 10, "revocationsPerHour": 2},
        "medium": {"leasesPerHour": 100, "revocationsPerHour": 20},
        "high": {"leasesPerHour": 1_000, "revocationsPerHour": 200},
    }
    projections: dict[str, Any] = {}
    reserve = MAX_AUTHORITY_LEASES // 10
    usable = MAX_AUTHORITY_LEASES - reserve
    for name, profile in profiles.items():
        lease_hours = usable / profile["leasesPerHour"]
        revocation_hours = (MAX_CAPABILITY_REVOCATIONS - reserve) / profile[
            "revocationsPerHour"
        ]
        projections[name] = {
            **profile,
            "hoursToLeaseReserve": round(lease_hours, 3),
            "hoursToRevocationReserve": round(revocation_hours, 3),
            "recommendedRolloverHours": round(min(lease_hours, revocation_hours), 3),
        }
    return {
        "limits": {
            "leases": MAX_AUTHORITY_LEASES,
            "retiredLeaseIds": MAX_RETIRED_AUTHORITY_LEASE_IDS,
            "revocations": MAX_CAPABILITY_REVOCATIONS,
        },
        "reserve": reserve,
        "profiles": projections,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--operations", type=int, default=512)
    args = parser.parse_args()
    if not 256 <= args.operations <= 32_768:
        parser.error("operations must be in 256..=32768")

    with tempfile.TemporaryDirectory(prefix="kernel-authority-storage-model-") as directory:
        root = Path(directory) / "model"
        operations, head = build_model(root, args.operations)
        drills = corruption_drills(root, operations, head)
        recovered = recover(root)
        passed = all(drills.values()) and recovered["sequence"] == operations
        receipt = {
            "schema": SCHEMA,
            "schemaVersion": 1,
            "qualificationOnly": True,
            "prototypeOnly": True,
            "productionImplementation": False,
            "activationGranted": False,
            "releaseGranted": False,
            "operations": operations,
            "checkpointInterval": CHECKPOINT_INTERVAL,
            "recovered": recovered,
            "crashAndCorruptionDrills": drills,
            "sharding": sharding_model(operations),
            "capacityLifetime": capacity_model(),
            "passed": passed,
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical(receipt) + b"\n")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
