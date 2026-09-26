"""Externally signed audit checkpoints and chained owner-state anchors.

A checkpoint allows a trusted external prefix digest to replace a full audit
prefix rescan.  The local verifier still proves every suffix event and the
current owner-state snapshot.  The receipt is evidence only: it grants no merge,
release, runtime, or deployment authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re

from .clock_policy import (
    ClockSkewPolicy,
    STRICT_CLOCK_POLICY,
    checked_now,
    validate_signed_window,
)
from .control_plane import (
    EngineeringError,
    EngineeringStore,
    ZERO_DIGEST,
    checked_id,
    checked_sha256,
    semantic_digest,
)
from .evidence import SignatureTrustStore
from .external_controls import store_snapshot_digest

_GIT_OID = re.compile(r"^[0-9a-f]{40}$")
MAX_CHECKPOINT_SUFFIX_ROWS = 1_000_000
AUDIT_CHECKPOINT_ISSUER = "external_audit_checkpoint"
OWNER_STATE_ANCHOR_ISSUER = "external_owner_state_anchor"


@dataclass(frozen=True)
class AuditCheckpointReceipt:
    source_commit: str
    source_tree: str
    sequence: int
    event_digest: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class OwnerStateAnchorReceipt:
    source_commit: str
    source_tree: str
    anchor_sequence: int
    previous_anchor_digest: str
    audit_checkpoint_digest: str
    audit_sequence: int
    audit_event_digest: str
    store_snapshot_digest: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class IncrementalAuditDecision:
    checkpoint_sequence: int
    verified_suffix_rows: int
    current_sequence: int
    current_event_digest: str
    checkpoint_digest: str
    runtime_authority: bool = False
    merge_authority: bool = False
    release_authority: bool = False


def _git_oid(value: str, label: str) -> str:
    if not isinstance(value, str) or _GIT_OID.fullmatch(value) is None:
        raise EngineeringError(label)
    return value


def _checkpoint_digest(receipt: AuditCheckpointReceipt) -> str:
    return semantic_digest(asdict(receipt))


def verify_audit_checkpoint(
    store: EngineeringStore,
    receipt: AuditCheckpointReceipt,
    trust_store: SignatureTrustStore,
    *,
    expected_source_commit: str,
    expected_source_tree: str,
    clock_policy: ClockSkewPolicy = STRICT_CLOCK_POLICY,
    now_ns: int | None = None,
) -> str:
    if not isinstance(store, EngineeringStore):
        raise EngineeringError("audit_checkpoint_store_required")
    if not isinstance(receipt, AuditCheckpointReceipt):
        raise EngineeringError("audit_checkpoint_required")
    _git_oid(expected_source_commit, "audit_checkpoint_expected_commit")
    _git_oid(expected_source_tree, "audit_checkpoint_expected_tree")
    if (
        receipt.source_commit != expected_source_commit
        or receipt.source_tree != expected_source_tree
    ):
        raise EngineeringError("audit_checkpoint_source_mismatch")
    if receipt.issuer != AUDIT_CHECKPOINT_ISSUER:
        raise EngineeringError("audit_checkpoint_issuer_role")
    checked_id(receipt.signing_identity, "audit_checkpoint_signing_identity")
    if type(receipt.sequence) is not int or receipt.sequence < 0:
        raise EngineeringError("audit_checkpoint_sequence")
    checked_sha256(receipt.event_digest, "audit_checkpoint_event_digest")
    if receipt.sequence == 0:
        if receipt.event_digest != ZERO_DIGEST:
            raise EngineeringError("audit_checkpoint_zero_mismatch")
    else:
        row = store.connection.execute(
            "SELECT event_digest FROM audit_events WHERE sequence=?",
            (receipt.sequence,),
        ).fetchone()
        if row is None or str(row["event_digest"]) != receipt.event_digest:
            raise EngineeringError("audit_checkpoint_event_mismatch")
    now = checked_now(now_ns)
    validate_signed_window(
        receipt.observed_unix_ns,
        receipt.expires_unix_ns,
        now,
        clock_policy,
        error_code="audit_checkpoint_stale",
    )
    if not trust_store.verify(
        receipt,
        receipt.issuer,
        receipt.signing_identity,
        receipt.signature,
    ):
        raise EngineeringError("audit_checkpoint_signature")
    return _checkpoint_digest(receipt)


def verify_audit_suffix(
    store: EngineeringStore,
    receipt: AuditCheckpointReceipt,
    trust_store: SignatureTrustStore,
    *,
    expected_source_commit: str,
    expected_source_tree: str,
    maximum_suffix_rows: int = MAX_CHECKPOINT_SUFFIX_ROWS,
    clock_policy: ClockSkewPolicy = STRICT_CLOCK_POLICY,
    now_ns: int | None = None,
) -> IncrementalAuditDecision:
    if (
        type(maximum_suffix_rows) is not int
        or not 1 <= maximum_suffix_rows <= MAX_CHECKPOINT_SUFFIX_ROWS
    ):
        raise EngineeringError("audit_checkpoint_suffix_limit")
    checkpoint_digest = verify_audit_checkpoint(
        store,
        receipt,
        trust_store,
        expected_source_commit=expected_source_commit,
        expected_source_tree=expected_source_tree,
        clock_policy=clock_policy,
        now_ns=now_ns,
    )
    count = int(
        store.connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE sequence>?",
            (receipt.sequence,),
        ).fetchone()[0]
    )
    if count > maximum_suffix_rows:
        raise EngineeringError("audit_checkpoint_suffix_limit")
    rows = store.connection.execute(
        "SELECT * FROM audit_events WHERE sequence>? ORDER BY sequence",
        (receipt.sequence,),
    ).fetchall()
    previous = receipt.event_digest
    expected_sequence = receipt.sequence + 1
    for row in rows:
        if int(row["sequence"]) != expected_sequence:
            raise EngineeringError("audit_checkpoint_sequence_gap")
        try:
            payload = json.loads(bytes(row["payload_json"]).decode("utf-8"))
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
            raise EngineeringError("audit_chain_broken") from None
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
            raise EngineeringError("audit_chain_broken")
        previous = digest
        expected_sequence += 1
    current_sequence = expected_sequence - 1
    return IncrementalAuditDecision(
        checkpoint_sequence=receipt.sequence,
        verified_suffix_rows=count,
        current_sequence=current_sequence,
        current_event_digest=previous,
        checkpoint_digest=checkpoint_digest,
    )


def verify_owner_state_anchor(
    store: EngineeringStore,
    receipt: OwnerStateAnchorReceipt,
    checkpoint: AuditCheckpointReceipt,
    trust_store: SignatureTrustStore,
    *,
    expected_source_commit: str,
    expected_source_tree: str,
    previous_anchor: OwnerStateAnchorReceipt | None = None,
    clock_policy: ClockSkewPolicy = STRICT_CLOCK_POLICY,
    now_ns: int | None = None,
) -> str:
    if not isinstance(receipt, OwnerStateAnchorReceipt):
        raise EngineeringError("owner_state_anchor_required")
    decision = verify_audit_suffix(
        store,
        checkpoint,
        trust_store,
        expected_source_commit=expected_source_commit,
        expected_source_tree=expected_source_tree,
        clock_policy=clock_policy,
        now_ns=now_ns,
    )
    if receipt.issuer != OWNER_STATE_ANCHOR_ISSUER:
        raise EngineeringError("owner_state_anchor_issuer_role")
    checked_id(receipt.signing_identity, "owner_state_anchor_signing_identity")
    if (
        receipt.source_commit != expected_source_commit
        or receipt.source_tree != expected_source_tree
        or receipt.audit_checkpoint_digest != decision.checkpoint_digest
        or receipt.audit_sequence != decision.current_sequence
        or receipt.audit_event_digest != decision.current_event_digest
    ):
        raise EngineeringError("owner_state_anchor_binding")
    if type(receipt.anchor_sequence) is not int or receipt.anchor_sequence < 1:
        raise EngineeringError("owner_state_anchor_sequence")
    checked_sha256(receipt.previous_anchor_digest, "previous_anchor_digest")
    checked_sha256(receipt.store_snapshot_digest, "store_snapshot_digest")
    if previous_anchor is None:
        if receipt.anchor_sequence != 1 or receipt.previous_anchor_digest != ZERO_DIGEST:
            raise EngineeringError("owner_state_anchor_predecessor")
    else:
        if (
            previous_anchor.issuer != OWNER_STATE_ANCHOR_ISSUER
            or previous_anchor.source_commit != expected_source_commit
            or previous_anchor.source_tree != expected_source_tree
            or previous_anchor.expires_unix_ns <= previous_anchor.observed_unix_ns
            or previous_anchor.expires_unix_ns < receipt.observed_unix_ns
            or not trust_store.verify(
                previous_anchor,
                previous_anchor.issuer,
                previous_anchor.signing_identity,
                previous_anchor.signature,
            )
        ):
            raise EngineeringError("owner_state_anchor_predecessor")
        previous_digest = semantic_digest(asdict(previous_anchor))
        if (
            receipt.anchor_sequence != previous_anchor.anchor_sequence + 1
            or receipt.previous_anchor_digest != previous_digest
            or receipt.observed_unix_ns < previous_anchor.observed_unix_ns
        ):
            raise EngineeringError("owner_state_anchor_predecessor")
    now = checked_now(now_ns)
    validate_signed_window(
        receipt.observed_unix_ns,
        receipt.expires_unix_ns,
        now,
        clock_policy,
        error_code="owner_state_anchor_stale",
    )
    if not trust_store.verify(
        receipt,
        receipt.issuer,
        receipt.signing_identity,
        receipt.signature,
    ):
        raise EngineeringError("owner_state_anchor_signature")
    if receipt.store_snapshot_digest != store_snapshot_digest(store):
        raise EngineeringError("owner_state_anchor_snapshot_mismatch")
    return semantic_digest(asdict(receipt))
