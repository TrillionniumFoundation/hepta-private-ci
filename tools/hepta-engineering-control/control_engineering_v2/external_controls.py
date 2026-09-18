"""Externally governed production controls for Lane G.

The repository cannot manufacture distributed HA, an immutable transparency log,
or HSM custody. It can, however, define and verify the exact authenticated
receipts a production worker must present before those claims are accepted.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import time

from .control_plane import (
    EngineeringError,
    EngineeringStore,
    LeaseReceipt,
    WorkEnvelope,
    checked_id,
    checked_sha256,
    semantic_digest,
)
from .evidence import SignatureTrustStore

MAX_KEY_CUSTODY_ROLES = 32


@dataclass(frozen=True)
class DistributedRevocationFrontierReceipt:
    cluster_id: str
    leader_id: str
    leader_term: int
    frontier_sequence: int
    frontier_digest: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class DistributedFenceReceipt:
    cluster_id: str
    leader_id: str
    leader_term: int
    lease_id: str
    holder: str
    authority_epoch: int
    fencing_token: int
    lease_revision: int
    lease_expires_unix_ns: int
    envelope_id: str
    envelope_revision: int
    paths_digest: str
    source_commit: str
    source_tree: str
    revocation_frontier_sequence: int
    revocation_frontier_digest: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class AuditAnchorAttestation:
    sequence: int
    event_digest: str
    envelope_id: str
    source_commit: str
    source_tree: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class KeyCustodyReceipt:
    provider: str
    key_id: str
    roles: tuple[str, ...]
    hardware_backed: bool
    external_to_engineering: bool
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class ProductionControlDecision:
    distributed_fence_verified: bool
    external_audit_anchor_verified: bool
    external_key_custody_verified: bool
    evidence_digest: str
    runtime_authority: bool = False
    merge_authority: bool = False
    release_authority: bool = False


def _window(observed: int, expires: int, now: int) -> bool:
    return (
        type(observed) is int
        and type(expires) is int
        and observed <= now < expires
        and expires > observed
    )


def verify_distributed_revocation_frontier(
    receipt: DistributedRevocationFrontierReceipt,
    trust_store: SignatureTrustStore,
    *,
    now_ns: int | None = None,
) -> str:
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or now < 0:
        raise EngineeringError("invalid_time")
    if not isinstance(receipt, DistributedRevocationFrontierReceipt):
        raise EngineeringError("distributed_revocation_frontier_required")
    checked_id(receipt.cluster_id, "cluster_id")
    checked_id(receipt.leader_id, "leader_id")
    if (
        type(receipt.leader_term) is not int
        or receipt.leader_term < 1
        or type(receipt.frontier_sequence) is not int
        or receipt.frontier_sequence < 1
    ):
        raise EngineeringError("distributed_revocation_frontier_order")
    checked_sha256(receipt.frontier_digest, "revocation_frontier_digest")
    if receipt.frontier_digest == "0" * 64:
        raise EngineeringError("distributed_revocation_frontier_digest")
    if receipt.issuer != "distributed_lease_authority":
        raise EngineeringError("distributed_revocation_frontier_issuer_role")
    if not _window(receipt.observed_unix_ns, receipt.expires_unix_ns, now):
        raise EngineeringError("distributed_revocation_frontier_stale")
    if not trust_store.verify(
        receipt,
        receipt.issuer,
        receipt.signing_identity,
        receipt.signature,
    ):
        raise EngineeringError("distributed_revocation_frontier_signature")
    return semantic_digest(asdict(receipt))


def verify_distributed_fence(
    lease: LeaseReceipt,
    envelope: WorkEnvelope,
    receipt: DistributedFenceReceipt,
    revocation_frontier: DistributedRevocationFrontierReceipt,
    trust_store: SignatureTrustStore,
    *,
    store: EngineeringStore,
    now_ns: int | None = None,
) -> str:
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or now < 0:
        raise EngineeringError("invalid_time")
    if not isinstance(store, EngineeringStore):
        raise EngineeringError("distributed_fence_store_required")
    if lease.state != "active":
        raise EngineeringError("distributed_fence_local_lease_inactive")
    if lease.envelope_id != envelope.envelope_id:
        raise EngineeringError("distributed_fence_envelope_mismatch")
    if lease.expires_unix_ns <= now or envelope.expires_unix_ns <= now:
        raise EngineeringError("distributed_fence_owner_state_stale")

    current = store.connection.execute(
        "SELECT envelope_id,holder,paths_json,state,authority_epoch,"
        "fencing_token,revision,expires_unix_ns "
        "FROM path_leases WHERE lease_id=?",
        (lease.lease_id,),
    ).fetchone()
    if current is None:
        raise EngineeringError("distributed_fence_local_lease_unknown")
    try:
        current_paths = tuple(
            json.loads(bytes(current["paths_json"]).decode("utf-8"))
        )
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise EngineeringError("distributed_fence_local_lease_invalid") from None
    if (
        str(current["envelope_id"]) != lease.envelope_id
        or str(current["holder"]) != lease.holder
        or str(current["state"]) != "active"
        or int(current["authority_epoch"]) != lease.epoch
        or int(current["fencing_token"]) != lease.fencing_token
        or int(current["revision"]) != lease.revision
        or int(current["expires_unix_ns"]) != lease.expires_unix_ns
        or current_paths != lease.paths
        or int(current["expires_unix_ns"]) <= now
    ):
        raise EngineeringError("distributed_fence_local_lease_stale")

    frontier_digest = verify_distributed_revocation_frontier(
        revocation_frontier,
        trust_store,
        now_ns=now,
    )
    for value, label in (
        (receipt.cluster_id, "cluster_id"),
        (receipt.leader_id, "leader_id"),
        (receipt.lease_id, "lease_id"),
        (receipt.holder, "holder"),
        (receipt.envelope_id, "envelope_id"),
    ):
        checked_id(value, label)
    if receipt.issuer != "distributed_lease_authority":
        raise EngineeringError("distributed_fence_issuer_role")
    if (
        type(receipt.leader_term) is not int
        or receipt.leader_term < 1
        or type(receipt.revocation_frontier_sequence) is not int
        or receipt.revocation_frontier_sequence < 1
    ):
        raise EngineeringError("distributed_fence_order")
    if (
        receipt.cluster_id != revocation_frontier.cluster_id
        or receipt.leader_id != revocation_frontier.leader_id
        or receipt.leader_term != revocation_frontier.leader_term
        or receipt.revocation_frontier_sequence
        != revocation_frontier.frontier_sequence
        or receipt.revocation_frontier_digest
        != revocation_frontier.frontier_digest
    ):
        raise EngineeringError("distributed_fence_revocation_frontier_mismatch")
    if revocation_frontier.observed_unix_ns < receipt.observed_unix_ns:
        raise EngineeringError("distributed_fence_revocation_frontier_older")
    if receipt.expires_unix_ns > revocation_frontier.expires_unix_ns:
        raise EngineeringError("distributed_fence_outlives_revocation_frontier")
    if (
        receipt.lease_id != lease.lease_id
        or receipt.holder != lease.holder
        or receipt.authority_epoch != lease.epoch
        or receipt.fencing_token != lease.fencing_token
        or receipt.lease_revision != lease.revision
        or receipt.lease_expires_unix_ns != lease.expires_unix_ns
        or receipt.envelope_id != envelope.envelope_id
        or receipt.envelope_revision != envelope.revision
        or receipt.source_commit != envelope.source_commit
        or receipt.source_tree != envelope.source_tree
    ):
        raise EngineeringError("distributed_fence_binding_mismatch")
    expected_paths = semantic_digest(lease.paths)
    if receipt.paths_digest != expected_paths:
        raise EngineeringError("distributed_fence_path_mismatch")
    checked_sha256(
        receipt.revocation_frontier_digest,
        "revocation_frontier_digest",
    )
    if receipt.revocation_frontier_digest == "0" * 64:
        raise EngineeringError("distributed_fence_revocation_frontier")
    if not _window(receipt.observed_unix_ns, receipt.expires_unix_ns, now):
        raise EngineeringError("distributed_fence_stale")
    if receipt.expires_unix_ns > min(
        lease.expires_unix_ns,
        envelope.expires_unix_ns,
    ):
        raise EngineeringError("distributed_fence_window_exceeds_owner")
    if not trust_store.verify(
        receipt,
        receipt.issuer,
        receipt.signing_identity,
        receipt.signature,
    ):
        raise EngineeringError("distributed_fence_signature")
    return semantic_digest(
        {
            "fence": asdict(receipt),
            "currentRevocationFrontierReceiptDigest": frontier_digest,
        }
    )


def verify_external_audit_anchor(
    store: EngineeringStore,
    envelope: WorkEnvelope,
    receipt: AuditAnchorAttestation,
    trust_store: SignatureTrustStore,
    *,
    now_ns: int | None = None,
) -> str:
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or now < 0:
        raise EngineeringError("invalid_time")
    if not isinstance(store, EngineeringStore):
        raise EngineeringError("audit_anchor_store_required")
    if not isinstance(receipt, AuditAnchorAttestation):
        raise EngineeringError("audit_anchor_receipt_required")
    if receipt.issuer != "audit_anchor_service":
        raise EngineeringError("audit_anchor_issuer_role")
    checked_id(receipt.envelope_id, "envelope_id")
    anchor = store.audit_anchor()
    if (
        type(anchor["sequence"]) is not int
        or anchor["sequence"] <= 0
        or anchor["eventDigest"] == "0" * 64
    ):
        raise EngineeringError("audit_anchor_empty")
    if envelope.expires_unix_ns <= now:
        raise EngineeringError("audit_anchor_envelope_stale")
    if (
        type(receipt.sequence) is not int
        or receipt.sequence != anchor["sequence"]
        or receipt.event_digest != anchor["eventDigest"]
        or receipt.envelope_id != envelope.envelope_id
        or receipt.source_commit != envelope.source_commit
        or receipt.source_tree != envelope.source_tree
    ):
        raise EngineeringError("audit_anchor_binding_mismatch")
    checked_sha256(receipt.event_digest, "audit_event_digest")
    if not _window(receipt.observed_unix_ns, receipt.expires_unix_ns, now):
        raise EngineeringError("audit_anchor_stale")
    if receipt.expires_unix_ns > envelope.expires_unix_ns:
        raise EngineeringError("audit_anchor_window_exceeds_envelope")
    if not trust_store.verify(
        receipt,
        receipt.issuer,
        receipt.signing_identity,
        receipt.signature,
    ):
        raise EngineeringError("audit_anchor_signature")
    return semantic_digest(asdict(receipt))


def verify_external_key_custody(
    receipt: KeyCustodyReceipt,
    trust_store: SignatureTrustStore,
    *,
    required_roles: tuple[str, ...] = (
        "source_authority",
        "ci_executor",
        "independent_evaluator",
        "engineering_evidence_binder",
    ),
    now_ns: int | None = None,
) -> str:
    now = time.time_ns() if now_ns is None else now_ns
    checked_id(receipt.provider, "key_provider")
    checked_id(receipt.key_id, "key_id")
    if receipt.issuer != "key_custody_authority":
        raise EngineeringError("key_custody_issuer_role")
    if (
        not isinstance(receipt.roles, tuple)
        or not receipt.roles
        or len(receipt.roles) > MAX_KEY_CUSTODY_ROLES
        or len(set(receipt.roles)) != len(receipt.roles)
    ):
        raise EngineeringError("key_custody_roles")
    for role in receipt.roles:
        checked_id(role, "key_custody_role")
    if (
        not isinstance(required_roles, tuple)
        or not required_roles
        or len(required_roles) > MAX_KEY_CUSTODY_ROLES
        or len(set(required_roles)) != len(required_roles)
    ):
        raise EngineeringError("key_custody_required_roles")
    for role in required_roles:
        checked_id(role, "required_key_custody_role")
    if (
        receipt.hardware_backed is not True
        or receipt.external_to_engineering is not True
    ):
        raise EngineeringError("key_custody_boundary")
    if not set(required_roles).issubset(set(receipt.roles)):
        raise EngineeringError("key_custody_roles")
    if not _window(receipt.observed_unix_ns, receipt.expires_unix_ns, now):
        raise EngineeringError("key_custody_stale")
    if not trust_store.verify(
        receipt,
        receipt.issuer,
        receipt.signing_identity,
        receipt.signature,
    ):
        raise EngineeringError("key_custody_signature")
    return semantic_digest(asdict(receipt))


def verify_production_controls(
    lease: LeaseReceipt,
    envelope: WorkEnvelope,
    distributed: DistributedFenceReceipt,
    revocation_frontier: DistributedRevocationFrontierReceipt,
    store: EngineeringStore,
    audit: AuditAnchorAttestation,
    custody: KeyCustodyReceipt,
    trust_store: SignatureTrustStore,
    *,
    now_ns: int | None = None,
) -> ProductionControlDecision:
    distributed_digest = verify_distributed_fence(
        lease,
        envelope,
        distributed,
        revocation_frontier,
        trust_store,
        store=store,
        now_ns=now_ns,
    )
    audit_digest = verify_external_audit_anchor(
        store,
        envelope,
        audit,
        trust_store,
        now_ns=now_ns,
    )
    custody_digest = verify_external_key_custody(
        custody,
        trust_store,
        now_ns=now_ns,
    )
    return ProductionControlDecision(
        True,
        True,
        True,
        semantic_digest(
            {
                "distributedFence": distributed_digest,
                "auditAnchor": audit_digest,
                "keyCustody": custody_digest,
            }
        ),
    )
