"""Incremental audit checkpoints bound to the complete durable owner snapshot."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import re

from .control_plane import (
    EngineeringError,
    EngineeringStore,
    canonical_json,
    checked_sha256,
    semantic_digest,
)
from .external_controls import store_snapshot_digest

_SHA1 = re.compile(r"[0-9a-f]{40}\Z")


@dataclass(frozen=True)
class AuditCheckpoint:
    sequence: int
    event_digest: str
    owner_snapshot_digest: str
    source_commit: str
    source_tree: str
    predecessor_checkpoint_digest: str
    delta_event_count: int
    delta_events_digest: str
    created_unix_ns: int
    checkpoint_digest: str
    runtime_authority: bool = False
    merge_authority: bool = False
    release_authority: bool = False


def _valid_git_sha(value: object) -> bool:
    return isinstance(value, str) and _SHA1.fullmatch(value) is not None


def _checkpoint_body(checkpoint: AuditCheckpoint) -> dict[str, object]:
    body = asdict(checkpoint)
    body.pop("checkpoint_digest")
    return body


def verify_checkpoint_digest(checkpoint: AuditCheckpoint) -> None:
    if not isinstance(checkpoint, AuditCheckpoint):
        raise EngineeringError("audit_checkpoint_required")
    checked_sha256(checkpoint.checkpoint_digest, "audit_checkpoint_digest")
    if semantic_digest(_checkpoint_body(checkpoint)) != checkpoint.checkpoint_digest:
        raise EngineeringError("audit_checkpoint_digest_mismatch")


def build_audit_checkpoint(
    store: EngineeringStore,
    *,
    source_commit: str,
    source_tree: str,
    previous: AuditCheckpoint | None = None,
    now_ns: int | None = None,
) -> AuditCheckpoint:
    if not isinstance(store, EngineeringStore):
        raise EngineeringError("audit_checkpoint_store_required")
    if not _valid_git_sha(source_commit) or not _valid_git_sha(source_tree):
        raise EngineeringError("audit_checkpoint_source_identity")
    now = store._now(now_ns)
    store.verify_audit_chain()
    anchor = store.audit_anchor()
    sequence = int(anchor["sequence"])
    event_digest = str(anchor["eventDigest"])
    start_sequence = 1
    predecessor = "0" * 64
    if previous is not None:
        verify_checkpoint_digest(previous)
        if previous.source_commit != source_commit or previous.source_tree != source_tree:
            raise EngineeringError("audit_checkpoint_source_drift")
        if previous.sequence > sequence:
            raise EngineeringError("audit_checkpoint_sequence_regression")
        row = store.connection.execute(
            "SELECT event_digest FROM audit_events WHERE sequence=?",
            (previous.sequence,),
        ).fetchone()
        if previous.sequence == 0:
            if row is not None:
                raise EngineeringError("audit_checkpoint_predecessor_mismatch")
        elif row is None or str(row["event_digest"]) != previous.event_digest:
            raise EngineeringError("audit_checkpoint_predecessor_mismatch")
        start_sequence = previous.sequence + 1
        predecessor = previous.checkpoint_digest

    digest = hashlib.sha256()
    count = 0
    rows = store.connection.execute(
        "SELECT sequence,event_digest,event_type,created_unix_ns "
        "FROM audit_events WHERE sequence>=? ORDER BY sequence",
        (start_sequence,),
    ).fetchall()
    for row in rows:
        digest.update(
            canonical_json(
                {
                    "sequence": int(row["sequence"]),
                    "eventDigest": str(row["event_digest"]),
                    "eventType": str(row["event_type"]),
                    "createdUnixNs": int(row["created_unix_ns"]),
                }
            )
        )
        digest.update(b"\n")
        count += 1
    provisional = AuditCheckpoint(
        sequence,
        event_digest,
        store_snapshot_digest(store),
        source_commit,
        source_tree,
        predecessor,
        count,
        digest.hexdigest(),
        now,
        "0" * 64,
    )
    return AuditCheckpoint(
        **{
            **asdict(provisional),
            "checkpoint_digest": semantic_digest(_checkpoint_body(provisional)),
        }
    )


def verify_audit_checkpoint(
    store: EngineeringStore,
    checkpoint: AuditCheckpoint,
    *,
    require_current_snapshot: bool = True,
) -> None:
    verify_checkpoint_digest(checkpoint)
    store.verify_audit_chain()
    if checkpoint.sequence == 0:
        if checkpoint.event_digest != "0" * 64:
            raise EngineeringError("audit_checkpoint_head_mismatch")
    else:
        row = store.connection.execute(
            "SELECT event_digest FROM audit_events WHERE sequence=?",
            (checkpoint.sequence,),
        ).fetchone()
        if row is None or str(row["event_digest"]) != checkpoint.event_digest:
            raise EngineeringError("audit_checkpoint_head_mismatch")
    if require_current_snapshot:
        anchor = store.audit_anchor()
        if int(anchor["sequence"]) != checkpoint.sequence:
            raise EngineeringError("audit_checkpoint_not_current")
        if store_snapshot_digest(store) != checkpoint.owner_snapshot_digest:
            raise EngineeringError("audit_checkpoint_owner_snapshot_mismatch")
