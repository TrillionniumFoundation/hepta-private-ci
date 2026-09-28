"""Checkpointed audit-tail verification and incremental owner-state anchoring.

A full checkpoint verifies the complete in-file audit chain and records one digest
per durable owner table.  Later checkpoints verify only the hash-linked tail from
that trusted checkpoint and recompute tables implicated by observed events.  An
unknown event type fails safe by recomputing every owner table.  Checkpoints are
qualification evidence; they grant no runtime, merge, deployment or release authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Mapping

from .control_plane import (
    EngineeringError,
    EngineeringStore,
    ZERO_DIGEST,
    semantic_digest,
)

AUDIT_CHECKPOINT_SCHEMA = "hepta.control-engineering-audit-checkpoint.v1"

AUDIT_STATE_TABLES = (
    "work_envelopes",
    "path_leases",
    "assignment_generations",
    "assignment_generation_frontiers",
    "orchestration_generations",
    "worker_registrations",
    "worker_claims",
    "worker_capacity_reservations",
    "worker_heartbeat_observations",
    "worker_result_observations",
    "worker_completion_observations",
    "integration_queue_generations",
    "integration_queue_items",
    "distributed_cluster_frontiers",
    "distributed_fence_frontiers",
    "integration_decisions",
    "integration_decision_bindings",
    "integration_decision_seals",
    "engineering_schema_meta",
)

_EVENT_TABLES: Mapping[str, frozenset[str]] = {
    "work_envelope_issued": frozenset({"work_envelopes"}),
    "path_lease_acquired": frozenset({"path_leases"}),
    "path_lease_renewed": frozenset({"path_leases"}),
    "path_lease_released": frozenset({"path_leases"}),
    "path_lease_revoked": frozenset({"path_leases"}),
    "path_lease_expired": frozenset({"path_leases"}),
    "assignment_generation_published": frozenset(
        {"assignment_generations", "assignment_generation_frontiers"}
    ),
    "orchestration_generation_published": frozenset(
        {"assignment_generations", "assignment_generation_frontiers", "orchestration_generations"}
    ),
    "worker_registered": frozenset({"worker_registrations"}),
    "worker_registration_renewed": frozenset({"worker_registrations"}),
    "worker_revoked": frozenset(
        {"worker_registrations", "worker_claims", "worker_capacity_reservations"}
    ),
    "worker_assignment_claimed": frozenset(
        {"worker_claims", "worker_capacity_reservations"}
    ),
    "worker_claim_heartbeat": frozenset(
        {"worker_claims", "worker_registrations", "worker_heartbeat_observations"}
    ),
    "worker_result_submitted": frozenset(
        {"worker_claims", "worker_capacity_reservations", "worker_result_observations"}
    ),
    "worker_capacity_released": frozenset({"worker_capacity_reservations"}),
    "worker_claim_completed_observed": frozenset(
        {"worker_claims", "worker_completion_observations"}
    ),
    "worker_claim_expired": frozenset(
        {"worker_claims", "worker_capacity_reservations"}
    ),
    "integration_queue_published": frozenset(
        {"integration_queue_generations", "integration_queue_items"}
    ),
    "integration_stage_observed": frozenset({"integration_queue_items"}),
    "integration_queue_invalidated": frozenset(
        {"integration_queue_generations", "integration_queue_items"}
    ),
    "integration_terminal_observed": frozenset(
        {"integration_queue_generations", "integration_queue_items"}
    ),
    "distributed_fence_admitted": frozenset(
        {"distributed_cluster_frontiers", "distributed_fence_frontiers"}
    ),
    "integration_decision_recorded": frozenset({"integration_decisions"}),
    "integration_decision_bound": frozenset({"integration_decision_bindings"}),
    "integration_decision_sealed": frozenset({"integration_decision_seals"}),
}


@dataclass(frozen=True)
class AuditCheckpoint:
    schema: str
    source_commit: str
    source_tree: str
    sequence: int
    event_digest: str
    table_digests: tuple[tuple[str, str], ...]
    owner_state_digest: str
    observed_unix_ns: int
    previous_checkpoint_digest: str
    checkpoint_digest: str
    runtime_authority: bool = False
    merge_authority: bool = False
    release_authority: bool = False


def _sql_value(value: object) -> object:
    if value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        return {"byteLength": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    raise EngineeringError("audit_checkpoint_store_value")


def _table_digest(store: EngineeringStore, table: str) -> str:
    if table not in AUDIT_STATE_TABLES:
        raise EngineeringError("audit_checkpoint_table")
    info = store.connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    columns = tuple(str(row[1]) for row in info)
    if not columns:
        raise EngineeringError("audit_checkpoint_store_incomplete")
    primary = tuple(
        str(row[1])
        for row in sorted(
            (row for row in info if int(row[5]) > 0),
            key=lambda row: int(row[5]),
        )
    )
    order_columns = primary or columns
    order = ",".join(f'"{column}"' for column in order_columns)
    digest = hashlib.sha256()
    digest.update(semantic_digest({"table": table, "columns": columns}).encode("ascii"))
    digest.update(b"\n")
    rows = store.connection.execute(
        f'SELECT * FROM "{table}" ORDER BY {order}'
    ).fetchall()
    for row in rows:
        body = {column: _sql_value(row[column]) for column in columns}
        digest.update(semantic_digest({"table": table, "row": body}).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _owner_state_digest(table_digests: tuple[tuple[str, str], ...]) -> str:
    return semantic_digest({"tables": table_digests})


def _checkpoint_digest(value: dict[str, object]) -> str:
    unsigned = dict(value)
    unsigned.pop("checkpoint_digest", None)
    unsigned.pop("checkpointDigest", None)
    return semantic_digest(unsigned)


def _identity(value: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise EngineeringError(label)
    return value


def _make_checkpoint(
    *,
    source_commit: str,
    source_tree: str,
    sequence: int,
    event_digest: str,
    table_digests: tuple[tuple[str, str], ...],
    observed_unix_ns: int,
    previous_checkpoint_digest: str,
) -> AuditCheckpoint:
    body: dict[str, object] = {
        "schema": AUDIT_CHECKPOINT_SCHEMA,
        "source_commit": source_commit,
        "source_tree": source_tree,
        "sequence": sequence,
        "event_digest": event_digest,
        "table_digests": table_digests,
        "owner_state_digest": _owner_state_digest(table_digests),
        "observed_unix_ns": observed_unix_ns,
        "previous_checkpoint_digest": previous_checkpoint_digest,
        "runtime_authority": False,
        "merge_authority": False,
        "release_authority": False,
    }
    body["checkpoint_digest"] = _checkpoint_digest(body)
    return AuditCheckpoint(**body)


def create_audit_checkpoint(
    store: EngineeringStore,
    *,
    source_commit: str,
    source_tree: str,
    observed_unix_ns: int,
) -> AuditCheckpoint:
    if not isinstance(store, EngineeringStore):
        raise EngineeringError("audit_checkpoint_store_required")
    _identity(source_commit, "audit_checkpoint_source_commit")
    _identity(source_tree, "audit_checkpoint_source_tree")
    if type(observed_unix_ns) is not int or observed_unix_ns < 0:
        raise EngineeringError("invalid_time")
    store.verify_audit_chain()
    last = store.connection.execute(
        "SELECT sequence,event_digest FROM audit_events ORDER BY sequence DESC LIMIT 1"
    ).fetchone()
    sequence = 0 if last is None else int(last["sequence"])
    event_digest = ZERO_DIGEST if last is None else str(last["event_digest"])
    table_digests = tuple(
        (table, _table_digest(store, table)) for table in AUDIT_STATE_TABLES
    )
    return _make_checkpoint(
        source_commit=source_commit,
        source_tree=source_tree,
        sequence=sequence,
        event_digest=event_digest,
        table_digests=table_digests,
        observed_unix_ns=observed_unix_ns,
        previous_checkpoint_digest=ZERO_DIGEST,
    )


def _validate_checkpoint(checkpoint: AuditCheckpoint) -> None:
    if not isinstance(checkpoint, AuditCheckpoint):
        raise EngineeringError("audit_checkpoint_required")
    if checkpoint.schema != AUDIT_CHECKPOINT_SCHEMA:
        raise EngineeringError("audit_checkpoint_schema")
    _identity(checkpoint.source_commit, "audit_checkpoint_source_commit")
    _identity(checkpoint.source_tree, "audit_checkpoint_source_tree")
    if type(checkpoint.sequence) is not int or checkpoint.sequence < 0:
        raise EngineeringError("audit_checkpoint_sequence")
    if type(checkpoint.observed_unix_ns) is not int or checkpoint.observed_unix_ns < 0:
        raise EngineeringError("audit_checkpoint_time")
    for digest, code in (
        (checkpoint.event_digest, "audit_checkpoint_event_digest"),
        (checkpoint.owner_state_digest, "audit_checkpoint_owner_state_digest"),
        (checkpoint.previous_checkpoint_digest, "audit_checkpoint_previous_digest"),
        (checkpoint.checkpoint_digest, "audit_checkpoint_digest"),
    ):
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise EngineeringError(code)
    if any((checkpoint.runtime_authority, checkpoint.merge_authority, checkpoint.release_authority)):
        raise EngineeringError("audit_checkpoint_authority_delta")
    if _checkpoint_digest(asdict(checkpoint)) != checkpoint.checkpoint_digest:
        raise EngineeringError("audit_checkpoint_digest")
    if tuple(table for table, _ in checkpoint.table_digests) != AUDIT_STATE_TABLES:
        raise EngineeringError("audit_checkpoint_table_set")
    if any(
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        for _, digest in checkpoint.table_digests
    ):
        raise EngineeringError("audit_checkpoint_table_digest")
    if _owner_state_digest(checkpoint.table_digests) != checkpoint.owner_state_digest:
        raise EngineeringError("audit_checkpoint_owner_state")


def _verified_tail(
    store: EngineeringStore,
    checkpoint: AuditCheckpoint,
) -> tuple[tuple[object, ...], set[str]]:
    _validate_checkpoint(checkpoint)
    if checkpoint.sequence == 0:
        previous = ZERO_DIGEST
    else:
        anchor = store.connection.execute(
            "SELECT event_digest FROM audit_events WHERE sequence=?",
            (checkpoint.sequence,),
        ).fetchone()
        if anchor is None or str(anchor[0]) != checkpoint.event_digest:
            raise EngineeringError("audit_checkpoint_anchor_mismatch")
        previous = checkpoint.event_digest
    rows = store.connection.execute(
        "SELECT sequence,previous_digest,event_digest,event_type,payload_json,created_unix_ns "
        "FROM audit_events WHERE sequence>? ORDER BY sequence",
        (checkpoint.sequence,),
    ).fetchall()
    changed: set[str] = set()
    expected_sequence = checkpoint.sequence + 1
    for row in rows:
        if int(row["sequence"]) != expected_sequence:
            raise EngineeringError("audit_checkpoint_tail_sequence")
        expected_sequence += 1
        if str(row["previous_digest"]) != previous:
            raise EngineeringError("audit_checkpoint_tail_link")
        try:
            payload = json.loads(bytes(row["payload_json"]).decode("utf-8"))
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
            raise EngineeringError("audit_checkpoint_tail_payload") from None
        body = {
            "previousDigest": previous,
            "eventType": str(row["event_type"]),
            "payload": payload,
            "createdUnixNs": int(row["created_unix_ns"]),
        }
        digest = semantic_digest(body)
        if digest != str(row["event_digest"]):
            raise EngineeringError("audit_checkpoint_tail_digest")
        previous = digest
        tables = _EVENT_TABLES.get(str(row["event_type"]))
        if tables is None:
            changed.update(AUDIT_STATE_TABLES)
        else:
            changed.update(tables)
    return tuple(rows), changed


def advance_audit_checkpoint(
    store: EngineeringStore,
    checkpoint: AuditCheckpoint,
    *,
    source_commit: str,
    source_tree: str,
    observed_unix_ns: int,
) -> AuditCheckpoint:
    if not isinstance(store, EngineeringStore):
        raise EngineeringError("audit_checkpoint_store_required")
    _identity(source_commit, "audit_checkpoint_source_commit")
    _identity(source_tree, "audit_checkpoint_source_tree")
    if (source_commit, source_tree) != (
        checkpoint.source_commit,
        checkpoint.source_tree,
    ):
        raise EngineeringError("audit_checkpoint_source_change_requires_full")
    if type(observed_unix_ns) is not int or observed_unix_ns < checkpoint.observed_unix_ns:
        raise EngineeringError("audit_checkpoint_time_regression")
    rows, changed = _verified_tail(store, checkpoint)
    current = dict(checkpoint.table_digests)
    for table in sorted(changed):
        current[table] = _table_digest(store, table)
    table_digests = tuple((table, current[table]) for table in AUDIT_STATE_TABLES)
    if rows:
        last = rows[-1]
        sequence = int(last["sequence"])
        event_digest = str(last["event_digest"])
    else:
        sequence = checkpoint.sequence
        event_digest = checkpoint.event_digest
    return _make_checkpoint(
        source_commit=source_commit,
        source_tree=source_tree,
        sequence=sequence,
        event_digest=event_digest,
        table_digests=table_digests,
        observed_unix_ns=observed_unix_ns,
        previous_checkpoint_digest=checkpoint.checkpoint_digest,
    )


def verify_audit_checkpoint(
    store: EngineeringStore,
    checkpoint: AuditCheckpoint,
    *,
    require_current_state: bool = True,
) -> None:
    _verified_tail(store, checkpoint)
    if require_current_state:
        current = tuple(
            (table, _table_digest(store, table)) for table in AUDIT_STATE_TABLES
        )
        if current != checkpoint.table_digests:
            raise EngineeringError("audit_checkpoint_state_drift")
        last = store.connection.execute(
            "SELECT sequence,event_digest FROM audit_events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        observed = (0, ZERO_DIGEST) if last is None else (int(last[0]), str(last[1]))
        if observed != (checkpoint.sequence, checkpoint.event_digest):
            raise EngineeringError("audit_checkpoint_not_current")
