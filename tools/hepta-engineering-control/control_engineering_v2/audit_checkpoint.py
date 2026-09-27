"""Signed audit checkpoints and delta verification for the engineering owner.

A checkpoint binds one exact audit head and a full durable-owner snapshot. Later
verification can start at that checkpoint and validate only the appended suffix.
The checkpoint is evidence material; it grants no runtime, merge, release, or
acceptance authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json

from .clock import Clock, ClockPolicy, validate_observation_window
from .control_plane import (
    ZERO_DIGEST,
    EngineeringError,
    EngineeringStore,
    checked_id,
    checked_sha256,
    semantic_digest,
)
from .evidence import SignatureTrustStore
from .external_controls import _AUDIT_STATE_TABLES, store_snapshot_digest


@dataclass(frozen=True)
class OwnerTableAnchor:
    table: str
    row_count: int
    digest: str


@dataclass(frozen=True)
class OwnerStateAnchor:
    tables: tuple[OwnerTableAnchor, ...]
    root_digest: str
    changed_tables: tuple[str, ...]


@dataclass(frozen=True)
class AuditCheckpointReceipt:
    sequence: int
    event_digest: str
    source_commit: str
    source_tree: str
    store_snapshot_digest: str
    table_anchor_digest: str
    previous_checkpoint_digest: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class AuditSuffixVerification:
    checkpoint_sequence: int
    current_sequence: int
    appended_events: int
    current_event_digest: str
    checkpoint_receipt_digest: str


def _checked_git_sha1(value: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
        or value == "0" * 40
    ):
        raise EngineeringError("invalid_" + label)
    return value


def _sql_value(value: object) -> object:
    if value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        return {"byteLength": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    raise EngineeringError("audit_checkpoint_store_value")


def _table_anchor(store: EngineeringStore, table: str) -> OwnerTableAnchor:
    checked_id(table, "table")
    info = store.connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    columns = tuple(str(row[1]) for row in info)
    if not columns:
        raise EngineeringError("audit_checkpoint_store_incomplete")
    primary = tuple(
        str(row[1])
        for row in sorted(
            (row for row in info if int(row[5]) > 0), key=lambda row: int(row[5])
        )
    )
    order_columns = primary or columns
    order = ",".join(f'"{column}"' for column in order_columns)
    rows = store.connection.execute(
        f'SELECT * FROM "{table}" ORDER BY {order}'
    ).fetchall()
    digest = hashlib.sha256()
    digest.update(semantic_digest({"table": table, "columns": columns}).encode("ascii"))
    digest.update(b"\n")
    for row in rows:
        digest.update(
            semantic_digest(
                {
                    "table": table,
                    "row": {column: _sql_value(row[column]) for column in columns},
                }
            ).encode("ascii")
        )
        digest.update(b"\n")
    return OwnerTableAnchor(table, len(rows), digest.hexdigest())


def build_owner_state_anchor(
    store: EngineeringStore,
    *,
    previous: OwnerStateAnchor | None = None,
) -> OwnerStateAnchor:
    if not isinstance(store, EngineeringStore):
        raise EngineeringError("audit_checkpoint_store_required")
    tables = tuple(_table_anchor(store, table) for table in _AUDIT_STATE_TABLES)
    previous_by_table = (
        {} if previous is None else {entry.table: entry.digest for entry in previous.tables}
    )
    changed = tuple(
        entry.table
        for entry in tables
        if previous_by_table.get(entry.table) != entry.digest
    )
    root = semantic_digest(tuple(asdict(entry) for entry in tables))
    return OwnerStateAnchor(tables, root, changed)


def checkpoint_receipt_digest(receipt: AuditCheckpointReceipt) -> str:
    if not isinstance(receipt, AuditCheckpointReceipt):
        raise EngineeringError("audit_checkpoint_required")
    return semantic_digest(asdict(receipt))


def build_audit_checkpoint(
    store: EngineeringStore,
    *,
    source_commit: str,
    source_tree: str,
    issuer: str,
    signing_identity: str,
    trust_store: SignatureTrustStore,
    clock_policy: ClockPolicy,
    observed_unix_ns: int,
    expires_unix_ns: int,
    previous_checkpoint: AuditCheckpointReceipt | None = None,
    previous_owner_anchor: OwnerStateAnchor | None = None,
    clock: Clock | None = None,
    now_ns: int | None = None,
) -> tuple[AuditCheckpointReceipt, OwnerStateAnchor]:
    if not isinstance(store, EngineeringStore):
        raise EngineeringError("audit_checkpoint_store_required")
    _checked_git_sha1(source_commit, "source_commit")
    _checked_git_sha1(source_tree, "source_tree")
    checked_id(issuer, "issuer")
    checked_id(signing_identity, "signing_identity")
    validate_observation_window(
        observed_unix_ns,
        expires_unix_ns,
        clock_policy,
        clock=clock,
        now_ns=now_ns,
    )
    store.verify_audit_chain()
    head = store.audit_anchor()
    if int(head["sequence"]) < 1:
        raise EngineeringError("audit_checkpoint_empty_chain")
    owner_anchor = build_owner_state_anchor(store, previous=previous_owner_anchor)
    previous_digest = ZERO_DIGEST
    if previous_checkpoint is not None:
        previous_digest = checkpoint_receipt_digest(previous_checkpoint)
        if previous_checkpoint.sequence >= int(head["sequence"]):
            raise EngineeringError("audit_checkpoint_order")
    unsigned = AuditCheckpointReceipt(
        sequence=int(head["sequence"]),
        event_digest=str(head["eventDigest"]),
        source_commit=source_commit,
        source_tree=source_tree,
        store_snapshot_digest=store_snapshot_digest(store),
        table_anchor_digest=owner_anchor.root_digest,
        previous_checkpoint_digest=previous_digest,
        issuer=issuer,
        signing_identity=signing_identity,
        observed_unix_ns=observed_unix_ns,
        expires_unix_ns=expires_unix_ns,
    )
    signature = trust_store.sign(unsigned, issuer, signing_identity)
    return replace(unsigned, signature=signature), owner_anchor


def _verify_checkpoint_receipt(
    receipt: AuditCheckpointReceipt,
    trust_store: SignatureTrustStore,
    clock_policy: ClockPolicy,
    *,
    clock: Clock | None,
    now_ns: int | None,
) -> None:
    if not isinstance(receipt, AuditCheckpointReceipt):
        raise EngineeringError("audit_checkpoint_required")
    if type(receipt.sequence) is not int or receipt.sequence < 1:
        raise EngineeringError("audit_checkpoint_sequence")
    for value, label in (
        (receipt.event_digest, "event_digest"),
        (receipt.store_snapshot_digest, "store_snapshot_digest"),
        (receipt.table_anchor_digest, "table_anchor_digest"),
        (receipt.previous_checkpoint_digest, "previous_checkpoint_digest"),
    ):
        checked_sha256(value, label)
    _checked_git_sha1(receipt.source_commit, "source_commit")
    _checked_git_sha1(receipt.source_tree, "source_tree")
    checked_id(receipt.issuer, "issuer")
    checked_id(receipt.signing_identity, "signing_identity")
    validate_observation_window(
        receipt.observed_unix_ns,
        receipt.expires_unix_ns,
        clock_policy,
        clock=clock,
        now_ns=now_ns,
    )
    if not trust_store.verify(
        receipt,
        receipt.issuer,
        receipt.signing_identity,
        receipt.signature,
    ):
        raise EngineeringError("audit_checkpoint_signature")


def verify_current_audit_checkpoint(
    store: EngineeringStore,
    receipt: AuditCheckpointReceipt,
    trust_store: SignatureTrustStore,
    clock_policy: ClockPolicy,
    *,
    owner_anchor: OwnerStateAnchor | None = None,
    clock: Clock | None = None,
    now_ns: int | None = None,
) -> str:
    _verify_checkpoint_receipt(
        receipt, trust_store, clock_policy, clock=clock, now_ns=now_ns
    )
    head = store.audit_anchor()
    if (
        int(head["sequence"]) != receipt.sequence
        or str(head["eventDigest"]) != receipt.event_digest
    ):
        raise EngineeringError("audit_checkpoint_not_current")
    if store_snapshot_digest(store) != receipt.store_snapshot_digest:
        raise EngineeringError("audit_checkpoint_store_mismatch")
    current_anchor = owner_anchor or build_owner_state_anchor(store)
    if current_anchor.root_digest != receipt.table_anchor_digest:
        raise EngineeringError("audit_checkpoint_table_anchor_mismatch")
    return checkpoint_receipt_digest(receipt)


def verify_audit_suffix(
    store: EngineeringStore,
    receipt: AuditCheckpointReceipt,
    trust_store: SignatureTrustStore,
    clock_policy: ClockPolicy,
    *,
    clock: Clock | None = None,
    now_ns: int | None = None,
) -> AuditSuffixVerification:
    """Verify the append-only suffix after a trusted signed checkpoint."""

    _verify_checkpoint_receipt(
        receipt, trust_store, clock_policy, clock=clock, now_ns=now_ns
    )
    checkpoint_row = store.connection.execute(
        "SELECT * FROM audit_events WHERE sequence=?", (receipt.sequence,)
    ).fetchone()
    if checkpoint_row is None or str(checkpoint_row["event_digest"]) != receipt.event_digest:
        raise EngineeringError("audit_checkpoint_history_missing")
    previous = receipt.event_digest
    rows = store.connection.execute(
        "SELECT * FROM audit_events WHERE sequence>? ORDER BY sequence",
        (receipt.sequence,),
    ).fetchall()
    expected_sequence = receipt.sequence + 1
    for row in rows:
        if int(row["sequence"]) != expected_sequence:
            raise EngineeringError("audit_chain_broken")
        try:
            payload = json.loads(bytes(row["payload_json"]).decode("utf-8"))
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
            raise EngineeringError("audit_chain_broken") from None
        digest = semantic_digest(
            {
                "previousDigest": previous,
                "eventType": str(row["event_type"]),
                "payload": payload,
                "createdUnixNs": int(row["created_unix_ns"]),
            }
        )
        if (
            str(row["previous_digest"]) != previous
            or str(row["event_digest"]) != digest
            or str(row["event_id"]) != digest[:32]
        ):
            raise EngineeringError("audit_chain_broken")
        previous = digest
        expected_sequence += 1
    head = store.audit_anchor()
    if int(head["sequence"]) != receipt.sequence + len(rows):
        raise EngineeringError("audit_chain_broken")
    if str(head["eventDigest"]) != previous:
        raise EngineeringError("audit_chain_broken")
    return AuditSuffixVerification(
        checkpoint_sequence=receipt.sequence,
        current_sequence=int(head["sequence"]),
        appended_events=len(rows),
        current_event_digest=previous,
        checkpoint_receipt_digest=checkpoint_receipt_digest(receipt),
    )
