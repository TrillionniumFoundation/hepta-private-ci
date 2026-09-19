"""Externally witnessable audit anchors for Lane G owner state.

The SQLite audit chain remains local evidence. An AuditAnchorReceipt becomes an
external anti-rollback witness only after a separately controlled signer signs
it and the signed receipt is retained outside the engineering owner database.
"""

from __future__ import annotations

from dataclasses import dataclass
import time

from . import control_plane as _control
from .evidence import SignatureVerifier


@dataclass(frozen=True)
class AuditAnchorReceipt:
    schema_version: int
    sequence: int
    event_digest: str
    writer_binding_digest: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


def prepare_audit_anchor(
    store: _control.EngineeringStore,
    *,
    issuer: str,
    signing_identity: str,
    observed_unix_ns: int | None = None,
    expires_unix_ns: int,
) -> AuditAnchorReceipt:
    now = store._now(observed_unix_ns)
    _control.checked_id(issuer, "audit_anchor_issuer")
    _control.checked_id(signing_identity, "audit_anchor_signing_identity")
    if issuer != "engineering_audit_witness":
        raise _control.EngineeringError("audit_anchor_issuer_role")
    if type(expires_unix_ns) is not int or expires_unix_ns <= now:
        raise _control.EngineeringError("invalid_audit_anchor_expiry")
    with store._transaction():
        store.verify_audit_chain()
        writer = store.connection.execute(
            "SELECT semantic_digest FROM engineering_writer_bindings WHERE singleton=1"
        ).fetchone()
        if writer is None:
            raise _control.EngineeringError("writer_binding_required")
        event = store.connection.execute(
            "SELECT sequence,event_digest,created_unix_ns FROM audit_events "
            "ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        if event is None:
            raise _control.EngineeringError("audit_anchor_empty")
        if now < int(event["created_unix_ns"]):
            raise _control.EngineeringError("audit_anchor_time_order")
        writer_digest = str(writer["semantic_digest"])
        event_digest = str(event["event_digest"])
        _control.checked_sha256(writer_digest, "writer_binding_digest")
        _control.checked_sha256(event_digest, "audit_event_digest")
        return AuditAnchorReceipt(
            _control.STORE_SCHEMA_VERSION,
            int(event["sequence"]),
            event_digest,
            writer_digest,
            issuer,
            signing_identity,
            now,
            expires_unix_ns,
        )


def verify_audit_anchor(
    store: _control.EngineeringStore,
    anchor: AuditAnchorReceipt,
    verifier: SignatureVerifier,
    *,
    minimum_sequence: int = 0,
    now_ns: int | None = None,
) -> None:
    if not isinstance(anchor, AuditAnchorReceipt):
        raise _control.EngineeringError("audit_anchor_receipt_required")
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or now < 0:
        raise _control.EngineeringError("invalid_time")
    if (
        type(anchor.schema_version) is not int
        or anchor.schema_version != _control.STORE_SCHEMA_VERSION
    ):
        raise _control.EngineeringError("audit_anchor_schema_mismatch")
    if (
        type(anchor.sequence) is not int
        or anchor.sequence < 1
        or type(minimum_sequence) is not int
        or minimum_sequence < 0
        or anchor.sequence < minimum_sequence
    ):
        raise _control.EngineeringError("audit_anchor_sequence")
    _control.checked_sha256(anchor.event_digest, "audit_event_digest")
    _control.checked_sha256(anchor.writer_binding_digest, "writer_binding_digest")
    if (
        anchor.issuer != "engineering_audit_witness"
        or not anchor.signing_identity
    ):
        raise _control.EngineeringError("audit_anchor_issuer_role")
    if (
        type(anchor.observed_unix_ns) is not int
        or type(anchor.expires_unix_ns) is not int
        or not anchor.observed_unix_ns <= now < anchor.expires_unix_ns
    ):
        raise _control.EngineeringError("audit_anchor_stale")
    if not verifier.verify(
        anchor,
        anchor.issuer,
        anchor.signing_identity,
        anchor.signature,
    ):
        raise _control.EngineeringError("audit_anchor_signature")

    with store._transaction():
        store.verify_audit_chain()
        writer = store.connection.execute(
            "SELECT semantic_digest FROM engineering_writer_bindings WHERE singleton=1"
        ).fetchone()
        if writer is None or str(writer["semantic_digest"]) != anchor.writer_binding_digest:
            raise _control.EngineeringError("audit_anchor_writer_mismatch")
        event = store.connection.execute(
            "SELECT event_digest,created_unix_ns FROM audit_events WHERE sequence=?",
            (anchor.sequence,),
        ).fetchone()
        if event is None or str(event["event_digest"]) != anchor.event_digest:
            raise _control.EngineeringError("audit_anchor_chain_mismatch")
        if anchor.observed_unix_ns < int(event["created_unix_ns"]):
            raise _control.EngineeringError("audit_anchor_time_order")
