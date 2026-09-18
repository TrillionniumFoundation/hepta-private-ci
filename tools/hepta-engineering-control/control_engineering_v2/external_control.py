"""External coordination, audit-anchor and key-custody verification ports.

SQLite remains a single-host owner store. Multi-host writes are therefore denied
unless an external coordinator supplies a fresh signed leader/fencing grant. Audit
integrity and production key custody are likewise external facts: this module
verifies receipts but does not pretend the local process can self-attest them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from collections.abc import Iterable, Protocol
import time

from .control_plane import (
    EngineeringError,
    EngineeringStore,
    canonical_paths,
    checked_id,
    checked_sha256,
    path_is_within,
    semantic_digest,
)


class SignatureVerifier(Protocol):
    def verify(
        self,
        value: object,
        issuer: str,
        signing_identity: str,
        signature: str,
    ) -> bool: ...


@dataclass(frozen=True)
class DistributedWriteGrant:
    coordinator_id: str
    leader_epoch: int
    fencing_token: int
    worker_id: str
    source_commit: str
    source_tree: str
    paths: tuple[str, ...]
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""
    authority_delta: bool = False


@dataclass(frozen=True)
class AuditAnchorReceipt:
    database_id: str
    sequence: int
    event_digest: str
    store_snapshot_digest: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class KeyCustodyReceipt:
    provider: str
    key_id: str
    purpose: str
    hardware_backed: bool
    exportable: bool
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


def _valid_window(observed: int, expires: int, now: int) -> bool:
    return (
        type(observed) is int
        and type(expires) is int
        and observed <= now < expires
        and expires > observed
    )


def _git_sha(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and value != "0" * 40
        and all(ch in "0123456789abcdef" for ch in value)
    )


def verify_distributed_write_grant(
    grant: DistributedWriteGrant,
    verifier: SignatureVerifier,
    *,
    worker_id: str,
    source_commit: str,
    source_tree: str,
    requested_paths: Iterable[str],
    minimum_leader_epoch: int,
    minimum_fencing_token: int,
    now_ns: int | None = None,
) -> DistributedWriteGrant:
    """Verify the external leader/fence at the real worker-write boundary."""
    now = time.time_ns() if now_ns is None else now_ns
    if not isinstance(grant, DistributedWriteGrant):
        raise EngineeringError("distributed_write_grant_required")
    checked_id(worker_id, "worker_id")
    checked_id(grant.coordinator_id, "coordinator_id")
    if grant.worker_id != worker_id:
        raise EngineeringError("distributed_worker_mismatch")
    if not _git_sha(source_commit) or not _git_sha(source_tree):
        raise EngineeringError("invalid_git_identity")
    if grant.source_commit != source_commit or grant.source_tree != source_tree:
        raise EngineeringError("distributed_source_mismatch")
    if (
        type(grant.leader_epoch) is not int
        or grant.leader_epoch < minimum_leader_epoch
        or type(grant.fencing_token) is not int
        or grant.fencing_token < minimum_fencing_token
    ):
        raise EngineeringError("distributed_fence_stale")
    if grant.authority_delta is not False:
        raise EngineeringError("distributed_authority_delta")
    admitted = canonical_paths(grant.paths)
    requested = canonical_paths(requested_paths)
    if not requested or any(not path_is_within(path, admitted) for path in requested):
        raise EngineeringError("distributed_path_scope")
    if not _valid_window(grant.observed_unix_ns, grant.expires_unix_ns, now):
        raise EngineeringError("distributed_write_grant_stale")
    if not verifier.verify(grant, grant.issuer, grant.signing_identity, grant.signature):
        raise EngineeringError("distributed_write_grant_signature")
    return replace(grant, paths=admitted)


def export_audit_anchor(
    store: EngineeringStore,
    *,
    database_id: str,
) -> AuditAnchorReceipt:
    """Export the current local audit head for signing by an external anchor."""
    checked_id(database_id, "database_id")
    store.verify_audit_chain()
    row = store.connection.execute(
        "SELECT sequence,event_digest FROM audit_events ORDER BY sequence DESC LIMIT 1"
    ).fetchone()
    sequence = 0 if row is None else int(row["sequence"])
    event_digest = "0" * 64 if row is None else str(row["event_digest"])
    snapshot_digest = semantic_digest(
        {
            "databaseId": database_id,
            "sequence": sequence,
            "eventDigest": event_digest,
        }
    )
    return AuditAnchorReceipt(
        database_id,
        sequence,
        event_digest,
        snapshot_digest,
        "external_audit_anchor",
        "",
        0,
        0,
        "",
    )


def verify_audit_anchor_receipt(
    receipt: AuditAnchorReceipt,
    verifier: SignatureVerifier,
    *,
    expected_database_id: str,
    minimum_sequence: int = 0,
    now_ns: int | None = None,
) -> AuditAnchorReceipt:
    now = time.time_ns() if now_ns is None else now_ns
    if not isinstance(receipt, AuditAnchorReceipt):
        raise EngineeringError("audit_anchor_receipt_required")
    checked_id(expected_database_id, "database_id")
    if receipt.database_id != expected_database_id:
        raise EngineeringError("audit_anchor_database_mismatch")
    if type(receipt.sequence) is not int or receipt.sequence < minimum_sequence:
        raise EngineeringError("audit_anchor_stale_sequence")
    checked_sha256(receipt.event_digest, "event_digest")
    checked_sha256(receipt.store_snapshot_digest, "store_snapshot_digest")
    if receipt.issuer != "external_audit_anchor" or not receipt.signing_identity:
        raise EngineeringError("audit_anchor_issuer")
    expected = semantic_digest(
        {
            "databaseId": receipt.database_id,
            "sequence": receipt.sequence,
            "eventDigest": receipt.event_digest,
        }
    )
    if receipt.store_snapshot_digest != expected:
        raise EngineeringError("audit_anchor_digest_mismatch")
    if not _valid_window(receipt.observed_unix_ns, receipt.expires_unix_ns, now):
        raise EngineeringError("audit_anchor_stale")
    if not verifier.verify(
        receipt, receipt.issuer, receipt.signing_identity, receipt.signature
    ):
        raise EngineeringError("audit_anchor_signature")
    return receipt


def verify_key_custody_receipt(
    receipt: KeyCustodyReceipt,
    verifier: SignatureVerifier,
    *,
    expected_purpose: str = "engineering-evidence-verification",
    now_ns: int | None = None,
) -> KeyCustodyReceipt:
    """Require externally controlled, non-exportable production verifier custody."""
    now = time.time_ns() if now_ns is None else now_ns
    if not isinstance(receipt, KeyCustodyReceipt):
        raise EngineeringError("key_custody_receipt_required")
    checked_id(receipt.provider, "key_provider")
    checked_id(receipt.key_id, "key_id")
    if receipt.purpose != expected_purpose:
        raise EngineeringError("key_custody_purpose")
    if receipt.hardware_backed is not True or receipt.exportable is not False:
        raise EngineeringError("key_custody_boundary")
    if receipt.issuer != "external_key_custodian" or not receipt.signing_identity:
        raise EngineeringError("key_custody_issuer")
    if not _valid_window(receipt.observed_unix_ns, receipt.expires_unix_ns, now):
        raise EngineeringError("key_custody_stale")
    if not verifier.verify(
        receipt, receipt.issuer, receipt.signing_identity, receipt.signature
    ):
        raise EngineeringError("key_custody_signature")
    return receipt
