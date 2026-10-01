"""Externally trusted audit anchors and bounded, snapshot-consistent verification.

A checkpoint supplied by a caller must come from its trusted retention boundary.
Neither this module nor an unsigned continuation authenticates an external caller.
Suffix verification proves audit history, not current owner-state equivalence.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import json
import sqlite3
import time
from typing import Iterator

from .control_plane import (
    EngineeringError,
    EngineeringStore,
    ZERO_DIGEST,
    canonical_json,
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


@dataclass(frozen=True)
class AuditVerificationBudget:
    maximum_events: int = 4096
    maximum_payload_bytes: int = 8 * 1024 * 1024

    def __post_init__(self) -> None:
        if (
            type(self.maximum_events) is not int
            or not 1 <= self.maximum_events <= 65536
            or type(self.maximum_payload_bytes) is not int
            or not 1 <= self.maximum_payload_bytes <= 64 * 1024 * 1024
        ):
            raise EngineeringError("invalid_audit_verification_budget")


@dataclass(frozen=True)
class AuditReadCut:
    sequence: int
    event_digest: str

    def __post_init__(self) -> None:
        _validate_anchor(self.sequence, self.event_digest)


@dataclass(frozen=True)
class AuditSuffixPage:
    """One verified segment; complete means this segment reached through.

    A trusted caller may retain next_checkpoint and through to continue. It must
    preserve the chain of page receipts. Accepting an arbitrary caller-supplied
    continuation is NOT proof that the omitted prefix was verified.
    """

    checkpoint_digest: str
    verified_from_sequence: int
    next_checkpoint: AuditCheckpoint
    through: AuditReadCut
    verified_events: int
    verified_payload_bytes: int
    complete: bool
    runtime_authority: bool = False
    merge_authority: bool = False


def _validate_anchor(sequence: int, digest: str) -> None:
    if type(sequence) is not int or not 0 <= sequence <= 2**63 - 1:
        raise EngineeringError("audit_checkpoint_invalid")
    checked_sha256(digest, "audit_checkpoint_event_digest")
    if sequence == 0 and digest != ZERO_DIGEST:
        raise EngineeringError("audit_checkpoint_invalid")


@contextmanager
def _read_snapshot(store: EngineeringStore) -> Iterator[sqlite3.Connection]:
    connection = store.connection
    owned = not connection.in_transaction
    if owned:
        connection.execute("BEGIN")
    try:
        yield connection
    finally:
        # A read must not commit, roll back, or otherwise finish its caller's
        # transaction. BEGIN/ROLLBACK here only delimit our own read snapshot.
        if owned:
            connection.rollback()


def _require_anchor(connection: sqlite3.Connection, sequence: int, digest: str) -> None:
    _validate_anchor(sequence, digest)
    if sequence:
        row = connection.execute(
            "SELECT 1 FROM audit_events WHERE sequence=? "
            "AND typeof(event_digest)='text' "
            "AND length(CAST(event_digest AS BLOB))=64 AND event_digest=?",
            (sequence, digest),
        ).fetchone()
        if row is None:
            raise EngineeringError("audit_checkpoint_not_in_history")


def create_audit_checkpoint(
    store: EngineeringStore, *, now_ns: int | None = None
) -> AuditCheckpoint:
    """Perform an explicit full checkpoint; this is not a bounded hot-path call."""
    if not isinstance(store, EngineeringStore):
        raise EngineeringError("audit_checkpoint_store_required")
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or not 0 <= now <= 2**63 - 1:
        raise EngineeringError("invalid_time")
    with _read_snapshot(store):
        store.verify_audit_chain()
        anchor = store.audit_anchor()
        return AuditCheckpoint(
            int(anchor["sequence"]), str(anchor["eventDigest"]),
            store_snapshot_digest(store), now,
        )


def _verify_page(
    store: EngineeringStore,
    checkpoint: AuditCheckpoint,
    budget: AuditVerificationBudget,
    through: AuditReadCut | None,
    *,
    require_complete: bool,
) -> AuditSuffixPage:
    if not isinstance(store, EngineeringStore) or not isinstance(checkpoint, AuditCheckpoint):
        raise EngineeringError("audit_checkpoint_required")
    if not isinstance(budget, AuditVerificationBudget):
        raise EngineeringError("invalid_audit_verification_budget")
    budget.__post_init__()
    _validate_anchor(checkpoint.sequence, checkpoint.event_digest)
    if (
        type(checkpoint.created_unix_ns) is not int
        or not 0 <= checkpoint.created_unix_ns <= 2**63 - 1
        or type(checkpoint.schema_version) is not int
        or checkpoint.schema_version != 1
    ):
        raise EngineeringError("audit_checkpoint_invalid")
    checked_sha256(checkpoint.owner_snapshot_digest, "owner_snapshot_digest")
    if through is not None and not isinstance(through, AuditReadCut):
        raise EngineeringError("audit_read_cut_required")
    with _read_snapshot(store) as connection:
        _require_anchor(connection, checkpoint.sequence, checkpoint.event_digest)
        if through is None:
            last = connection.execute(
                "SELECT sequence,CASE WHEN typeof(event_digest)='text' "
                "AND length(CAST(event_digest AS BLOB))=64 THEN event_digest END "
                "FROM audit_events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            through = AuditReadCut(0, ZERO_DIGEST) if last is None else AuditReadCut(last[0], last[1])
        _require_anchor(connection, through.sequence, through.event_digest)
        if through.sequence < checkpoint.sequence:
            raise EngineeringError("audit_read_cut_before_checkpoint")
        # Only fixed-size metadata crosses the SQL boundary before admission.
        # LIMIT+1 bounds even the oversize probe. Payload bytes are not fetched
        # until their cumulative budget and each row's metadata bounds pass.
        metadata = connection.execute(
            "SELECT sequence,length(CAST(payload_json AS BLOB)),"
            "length(CAST(event_type AS BLOB)),length(CAST(event_id AS BLOB)),"
            "length(CAST(previous_digest AS BLOB)),length(CAST(event_digest AS BLOB)),"
            "(typeof(payload_json)='blob' AND typeof(event_type)='text' "
            "AND typeof(event_id)='text' AND typeof(previous_digest)='text' "
            "AND typeof(event_digest)='text' AND instr(event_type,char(0))=0 "
            "AND typeof(created_unix_ns)='integer' AND created_unix_ns>=0) "
            "FROM audit_events "
            "WHERE sequence>? AND sequence<=? ORDER BY sequence LIMIT ?",
            (checkpoint.sequence, through.sequence, budget.maximum_events + 1),
        ).fetchall()
        if require_complete and len(metadata) > budget.maximum_events:
            raise EngineeringError("audit_suffix_event_budget_exceeded")
        admitted: list[int] = []
        payload_bytes = 0
        for row in metadata[:budget.maximum_events]:
            sequence, size, type_size, id_size, previous_size, digest_size, shape_ok = row
            if sequence != checkpoint.sequence + len(admitted) + 1:
                raise EngineeringError("audit_chain_sequence_gap")
            if (
                shape_ok != 1 or type(size) is not int or size < 0
                or type(type_size) is not int or not 1 <= type_size <= 128
                or (id_size, previous_size, digest_size) != (32, 64, 64)
            ):
                raise EngineeringError("audit_chain_metadata_invalid")
            if payload_bytes + size > budget.maximum_payload_bytes:
                if require_complete or not admitted:
                    raise EngineeringError("audit_suffix_payload_budget_exceeded")
                break
            payload_bytes += size
            admitted.append(sequence)
        previous = checkpoint.event_digest
        latest = checkpoint.sequence
        # Fetch only the admitted interval, after both budgets pass. Stream a
        # single indexed query instead of issuing one query per event. Byte
        # lengths above include embedded NULs; SQLite length(TEXT) would not.
        events = connection.execute(
            "SELECT * FROM audit_events WHERE sequence>? AND sequence<=? "
            "ORDER BY sequence LIMIT ?",
            (checkpoint.sequence, admitted[-1], len(admitted)),
        ) if admitted else ()
        for event in events:
            sequence = event["sequence"]
            if sequence != latest + 1:
                raise EngineeringError("audit_chain_sequence_gap")
            try:
                raw = event["payload_json"]
                if not isinstance(raw, bytes):
                    raise EngineeringError("audit_chain_payload_invalid")
                payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict) or canonical_json(payload) != raw:
                    raise EngineeringError("audit_chain_payload_invalid")
                created = event["created_unix_ns"]
                if type(created) is not int or created < 0:
                    raise EngineeringError("audit_chain_metadata_invalid")
                digest = semantic_digest({
                    "previousDigest": previous,
                    "eventType": event["event_type"],
                    "payload": payload,
                    "createdUnixNs": created,
                })
            except EngineeringError:
                raise
            except (TypeError, UnicodeError, ValueError, RecursionError):
                raise EngineeringError("audit_chain_payload_invalid") from None
            if (
                event["previous_digest"] != previous
                or event["event_digest"] != digest
                or event["event_id"] != digest[:32]
            ):
                raise EngineeringError("audit_chain_invalid")
            previous, latest = digest, sequence
        if admitted and latest != admitted[-1]:
            raise EngineeringError("audit_chain_sequence_gap")
        complete = latest == through.sequence
        if complete and previous != through.event_digest:
            raise EngineeringError("audit_chain_invalid")
        if not complete and len(metadata) == len(admitted):
            raise EngineeringError("audit_chain_sequence_gap")
        if require_complete and not complete:
            raise EngineeringError("audit_suffix_event_budget_exceeded")
        return AuditSuffixPage(
            semantic_digest(asdict(checkpoint)), checkpoint.sequence,
            AuditCheckpoint(latest, previous, checkpoint.owner_snapshot_digest,
                            checkpoint.created_unix_ns),
            through, len(admitted), payload_bytes, complete,
        )


def verify_audit_suffix_page(
    store: EngineeringStore,
    checkpoint: AuditCheckpoint,
    *,
    budget: AuditVerificationBudget = AuditVerificationBudget(),
    through: AuditReadCut | None = None,
) -> AuditSuffixPage:
    """Verify a bounded contiguous segment against a fixed, append-safe cut."""
    return _verify_page(store, checkpoint, budget, through, require_complete=False)


def verify_audit_suffix(
    store: EngineeringStore,
    checkpoint: AuditCheckpoint,
    *,
    budget: AuditVerificationBudget = AuditVerificationBudget(),
    through: AuditReadCut | None = None,
) -> dict[str, object]:
    """Verify a complete bounded suffix or reject; never silently truncate."""
    page = _verify_page(store, checkpoint, budget, through, require_complete=True)
    return {
        "checkpointDigest": page.checkpoint_digest,
        "verifiedFromSequence": page.verified_from_sequence,
        "latestSequence": page.next_checkpoint.sequence,
        "latestEventDigest": page.next_checkpoint.event_digest,
        "verifiedSuffixEvents": page.verified_events,
        "verifiedPayloadBytes": page.verified_payload_bytes,
        "complete": page.complete,
        "throughSequence": page.through.sequence,
        "throughEventDigest": page.through.event_digest,
        "ownerSnapshotVerified": False,
        "runtimeAuthority": False,
        "mergeAuthority": False,
    }
