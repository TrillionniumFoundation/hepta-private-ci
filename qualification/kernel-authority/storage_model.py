#!/usr/bin/env python3
"""Qualification-only WAL/checkpoint, sharding and capacity model.

This executable reference model exercises a hash-chained journal, atomic
checkpoints and an independently retained monotonic frontier.  The frontier is
passed to recovery from outside the modeled local state directory, so a valid
but older checkpoint+journal pair is rejected rather than being confused with
mere file corruption.

The model is deliberately not imported by runtime code and never grants
production implementation, activation, release or an SLO.
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

SCHEMA = "hepta.kernel-authority-storage-model.v2"
FRONTIER_SCHEMA = "hepta.kernel-authority-storage-frontier.v1"
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


def record_envelope(sequence: int, previous: str, operation: str) -> dict[str, Any]:
    payload = {
        "operation": operation,
        "payloadSha256": sha256_bytes(f"payload:{sequence}:{operation}".encode()),
        "previousRecordSha256": previous,
        "sequence": sequence,
    }
    return {
        "record": payload,
        "recordSha256": sha256_bytes(canonical(payload)),
    }


def append_record(root: Path, sequence: int, previous: str, operation: str) -> str:
    envelope = record_envelope(sequence, previous, operation)
    with (root / "journal.jsonl").open("ab") as stream:
        stream.write(canonical(envelope) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    return str(envelope["recordSha256"])


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


def protected_frontier(sequence: int, head: str) -> dict[str, Any]:
    return {
        "schema": FRONTIER_SCHEMA,
        "sequence": sequence,
        "headRecordSha256": head,
    }


def validate_frontier(value: dict[str, Any]) -> tuple[int, str]:
    if set(value) != {"schema", "sequence", "headRecordSha256"}:
        raise ModelError("external frontier fields drifted")
    if value["schema"] != FRONTIER_SCHEMA:
        raise ModelError("external frontier schema mismatch")
    sequence = value["sequence"]
    head = value["headRecordSha256"]
    if type(sequence) is not int or sequence < 0:
        raise ModelError("external frontier sequence is invalid")
    if (
        not isinstance(head, str)
        or len(head) != 64
        or any(character not in "0123456789abcdef" for character in head)
    ):
        raise ModelError("external frontier digest is invalid")
    if sequence == 0 and head != "0" * 64:
        raise ModelError("genesis frontier digest mismatch")
    if sequence != 0 and head == "0" * 64:
        raise ModelError("non-genesis frontier has a zero digest")
    return sequence, head


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ModelError(f"invalid {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise ModelError(f"{path.name} is not an object")
    return value


def recover(
    root: Path, trusted_frontier: dict[str, Any] | None = None
) -> dict[str, Any]:
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
    expected_state_digest = sha256_bytes(f"state:{sequence}:{head}".encode())
    if state["stateSha256"] != expected_state_digest:
        raise ModelError("checkpoint state digest mismatch")

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

    external_frontier_matched = trusted_frontier is not None
    if trusted_frontier is not None:
        trusted_sequence, trusted_head = validate_frontier(trusted_frontier)
        if sequence != trusted_sequence or head != trusted_head:
            raise ModelError("local state does not match the external monotonic frontier")

    return {
        "discardedPartialTail": discarded_partial_tail,
        "externalFrontierMatched": external_frontier_matched,
        "headRecordSha256": head,
        "sequence": sequence,
    }


def copy_model(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination)


def build_model(
    root: Path, rollback_snapshot: Path, operations: int
) -> tuple[dict[str, Any], str]:
    root.mkdir(parents=True, exist_ok=True)
    (root / "journal.jsonl").write_bytes(b"")
    head = "0" * 64
    generation = 0
    checkpoint(root, generation, 0, head)
    rollback_sequence = max(1, operations // 2)
    for sequence in range(1, operations + 1):
        operation = ("put", "dispatch", "revoke", "prune")[sequence % 4]
        head = append_record(root, sequence, head, operation)
        if sequence % CHECKPOINT_INTERVAL == 0 and sequence != operations:
            generation += 1
            checkpoint(root, generation, sequence, head)
        if sequence == rollback_sequence:
            copy_model(root, rollback_snapshot)
    return protected_frontier(operations, head), head


def corruption_drills(
    root: Path,
    rollback_snapshot: Path,
    operations: int,
    expected_head: str,
    trusted_frontier: dict[str, Any],
) -> dict[str, bool]:
    baseline = recover(root, trusted_frontier)
    baseline_ok = (
        baseline["sequence"] == operations
        and baseline["headRecordSha256"] == expected_head
        and baseline["externalFrontierMatched"] is True
    )

    torn = root.parent / "torn-tail"
    copy_model(root, torn)
    with (torn / "journal.jsonl").open("ab") as stream:
        stream.write(b'{"record":')
        stream.flush()
        os.fsync(stream.fileno())
    torn_recovery = recover(torn, trusted_frontier)
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
    committed_record_corruption_rejected = False
    try:
        recover(corrupted, trusted_frontier)
    except ModelError:
        committed_record_corruption_rejected = True

    corrupted_checkpoint = root.parent / "corrupted-checkpoint"
    copy_model(root, corrupted_checkpoint)
    manifest = read_json(corrupted_checkpoint / "manifest.json")
    checkpoint_path = corrupted_checkpoint / str(manifest["checkpointPath"])
    checkpoint_bytes = bytearray(checkpoint_path.read_bytes())
    checkpoint_bytes[-2] = (
        ord("0") if checkpoint_bytes[-2] != ord("0") else ord("1")
    )
    checkpoint_path.write_bytes(checkpoint_bytes)
    corrupted_checkpoint_rejected = False
    try:
        recover(corrupted_checkpoint, trusted_frontier)
    except ModelError:
        corrupted_checkpoint_rejected = True

    valid_older_snapshot_rejected = False
    try:
        recover(rollback_snapshot, trusted_frontier)
    except ModelError:
        valid_older_snapshot_rejected = True

    next_operation = "put"
    next_envelope = record_envelope(operations + 1, expected_head, next_operation)
    frontier_ahead = protected_frontier(
        operations + 1, str(next_envelope["recordSha256"])
    )
    external_frontier_ahead_fences = False
    try:
        recover(root, frontier_ahead)
    except ModelError:
        external_frontier_ahead_fences = True

    stale_frontier_rejected = False
    rollback_state = recover(rollback_snapshot)
    stale_frontier = protected_frontier(
        int(rollback_state["sequence"]), str(rollback_state["headRecordSha256"])
    )
    try:
        recover(root, stale_frontier)
    except ModelError:
        stale_frontier_rejected = True

    return {
        "baselineRecovery": baseline_ok,
        "committedRecordCorruptionRejected": committed_record_corruption_rejected,
        "corruptedCheckpointRejected": corrupted_checkpoint_rejected,
        "externalFrontierAheadFences": external_frontier_ahead_fences,
        "partialTailDiscarded": torn_tail_ok,
        "staleExternalFrontierRejected": stale_frontier_rejected,
        "validOlderLocalSnapshotRejected": valid_older_snapshot_rejected,
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
        parent = Path(directory)
        root = parent / "model"
        rollback_snapshot = parent / "valid-older-local-snapshot"
        trusted_frontier, head = build_model(root, rollback_snapshot, args.operations)
        drills = corruption_drills(
            root,
            rollback_snapshot,
            args.operations,
            head,
            trusted_frontier,
        )
        recovered = recover(root, trusted_frontier)
        passed = (
            all(drills.values())
            and recovered["sequence"] == args.operations
            and recovered["externalFrontierMatched"] is True
        )
        receipt = {
            "schema": SCHEMA,
            "schemaVersion": 2,
            "qualificationOnly": True,
            "prototypeOnly": True,
            "productionImplementation": False,
            "activationGranted": False,
            "releaseGranted": False,
            "operations": args.operations,
            "checkpointInterval": CHECKPOINT_INTERVAL,
            "externalFrontier": {
                **trusted_frontier,
                "rollbackIndependent": True,
                "qualificationOnly": True,
            },
            "recovered": recovered,
            "crashRollbackAndCorruptionDrills": drills,
            "sharding": sharding_model(args.operations),
            "capacityLifetime": capacity_model(),
            "passed": passed,
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical(receipt) + b"\n")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
