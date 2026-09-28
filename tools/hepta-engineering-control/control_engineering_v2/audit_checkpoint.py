"""Externally retained audit checkpoints with bounded suffix verification."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import time

from .control_plane import (
    EngineeringError,
    EngineeringStore,
    ZERO_DIGEST,
    checked_sha256,
    semantic_digest,
)
from .external_controls import store_snapshot_digest


@dataclass(frozen=True)
class AuditCheckpoint:
    sequence: int
    event_digest: str
    owner_snapshot_digest: str
    created_unix_ns: int
    schema_version: int = 1


def create_audit_checkpoint(
    store: EngineeringStore, *, now_ns: int | None = None
) -> AuditCheckpoint:
    if not isinstance(store, EngineeringStore):
        raise EngineeringError("audit_checkpoint_store_required")
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or now < 0:
        raise EngineeringError("invalid_time")
    store.verify_audit_chain()
    anchor = store.audit_anchor()
    return AuditCheckpoint(
        int(anchor["sequence"]),
        str(anchor["eventDigest"]),
        store_snapshot_digest(store),
        now,
    )


def verify_audit_suffix(
    store: EngineeringStore, checkpoint: AuditCheckpoint
) -> dict[str, object]:
    """Verify only events after an externally trusted full checkpoint.

    The checkpoint's owner snapshot must be retained outside this SQLite file.
    This function does not pretend an in-file checkpoint protects against an
    administrator rewriting both owner state and history.
    """
    if not isinstance(store, EngineeringStore) or not isinstance(
        checkpoint, AuditCheckpoint
    ):
        raise EngineeringError("audit_checkpoint_required")
    if (
        type(checkpoint.sequence) is not int
        or checkpoint.sequence < 0
        or type(checkpoint.created_unix_ns) is not int
        or checkpoint.created_unix_ns < 0
        or checkpoint.schema_version != 1
    ):
        raise EngineeringError("audit_checkpoint_invalid")
    checked_sha256(checkpoint.owner_snapshot_digest, "owner_snapshot_digest")
    previous = checkpoint.event_digest
    if checkpoint.sequence == 0:
        if previous != ZERO_DIGEST:
            raise EngineeringError("audit_checkpoint_invalid")
    else:
        checked_sha256(previous, "audit_checkpoint_event_digest")
        row = store.connection.execute(
            "SELECT event_digest FROM audit_events WHERE sequence=?",
            (checkpoint.sequence,),
        ).fetchone()
        if row is None or str(row[0]) != previous:
            raise EngineeringError("audit_checkpoint_not_in_history")
    rows = store.connection.execute(
        "SELECT * FROM audit_events WHERE sequence>? ORDER BY sequence",
        (checkpoint.sequence,),
    ).fetchall()
    expected_sequence = checkpoint.sequence + 1
    for row in rows:
        if int(row["sequence"]) != expected_sequence:
            raise EngineeringError("audit_chain_sequence_gap")
        try:
            payload = json.loads(bytes(row["payload_json"]).decode("utf-8"))
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
            raise EngineeringError("audit_chain_payload_invalid") from None
        body = {
            "previousDigest": previous,
            "eventType": str(row["event_type"]),
            "payload": payload,
            "createdUnixNs": int(row["created_unix_ns"]),
        }
        digest = semantic_digest(body)
        if (
            str(row["previous_digest"]) != previous
            or str(row["event_digest"]) != digest
            or str(row["event_id"]) != digest[:32]
        ):
            raise EngineeringError("audit_chain_invalid")
        previous = digest
        expected_sequence += 1
    latest = checkpoint.sequence if not rows else int(rows[-1]["sequence"])
    return {
        "checkpointDigest": semantic_digest(asdict(checkpoint)),
        "verifiedFromSequence": checkpoint.sequence,
        "latestSequence": latest,
        "latestEventDigest": previous,
        "verifiedSuffixEvents": len(rows),
        "runtimeAuthority": False,
        "mergeAuthority": False,
    }
