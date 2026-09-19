"""Externally governed production controls for Lane G.

The repository cannot manufacture distributed HA, an immutable transparency log,
or HSM custody. It can, however, define and verify the exact authenticated
receipts a production worker must present before those claims are accepted.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
import hashlib
import json
import time

from .control_plane import (
    EngineeringError,
    EngineeringStore,
    bounded_tuple,
    LeaseReceipt,
    WorkEnvelope,
    checked_id,
    checked_sha256,
    semantic_digest,
)
from .evidence import SignatureTrustStore

MAX_KEY_CUSTODY_ROLES = 32

_AUDIT_STATE_TABLES = (
    "work_envelopes",
    "path_leases",
    "assignment_generations",
    "assignment_generation_frontiers",
    "distributed_fence_frontiers",
    "integration_decisions",
    "integration_decision_bindings",
    "integration_decision_seals",
    "engineering_schema_meta",
)


def _sql_value(value: object) -> object:
    if value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        return {
            "byteLength": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    raise EngineeringError("audit_anchor_store_value")


def store_snapshot_digest(store: EngineeringStore) -> str:
    """Digest durable owner facts independently of the in-file audit chain."""
    if not isinstance(store, EngineeringStore):
        raise EngineeringError("audit_anchor_store_required")
    store.verify_audit_chain()
    tables = {
        str(row[0])
        for row in store.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if any(table not in tables for table in _AUDIT_STATE_TABLES):
        raise EngineeringError("audit_anchor_store_incomplete")

    digest = hashlib.sha256()
    for table in _AUDIT_STATE_TABLES:
        info = store.connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        columns = tuple(str(row[1]) for row in info)
        primary = tuple(
            str(row[1])
            for row in sorted(
                (row for row in info if int(row[5]) > 0),
                key=lambda row: int(row[5]),
            )
        )
        if not columns:
            raise EngineeringError("audit_anchor_store_incomplete")
        order_columns = primary or columns
        order = ",".join(f'"{column}"' for column in order_columns)
        digest.update(
            semantic_digest({"table": table, "columns": columns}).encode("ascii")
        )
        digest.update(b"\n")
        rows = store.connection.execute(
            f'SELECT * FROM "{table}" ORDER BY {order}'
        ).fetchall()
        for row in rows:
            body = {column: _sql_value(row[column]) for column in columns}
            digest.update(
                semantic_digest({"table": table, "row": body}).encode("ascii")
            )
            digest.update(b"\n")
    return digest.hexdigest()


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
    roles: tuple[str, ...]
    hardware_backed: bool
    external_to_engineering: bool
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""
    subject_signing_identity: str = ""
    algorithm: str = ""
    public_key_digest: str = ""
    attestation_digest: str = ""


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


def admit_distributed_fence(
    lease: LeaseReceipt,
    envelope: WorkEnvelope,
    receipt: DistributedFenceReceipt,
    revocation_frontier: DistributedRevocationFrontierReceipt,
    trust_store: SignatureTrustStore,
    *,
    store: EngineeringStore,
    now_ns: int | None = None,
) -> str:
    """Persist the highest accepted external fence for one cluster/holder.

    The external lease authority remains the consensus/leader source. This local
    high-water mark only prevents a process restart from making an older, still
    cryptographically valid grant acceptable again.
    """
    now = store._now(now_ns)
    with store._transaction():
        digest = verify_distributed_fence(
            lease,
            envelope,
            receipt,
            revocation_frontier,
            trust_store,
            store=store,
            now_ns=now,
        )
        row = store.connection.execute(
            "SELECT * FROM distributed_fence_frontiers "
            "WHERE cluster_id=? AND holder=?",
            (receipt.cluster_id, receipt.holder),
        ).fetchone()
        incoming = (receipt.leader_term, receipt.revocation_frontier_sequence)
        if row is not None:
            current = (
                int(row["leader_term"]),
                int(row["revocation_frontier_sequence"]),
            )
            if incoming < current:
                raise EngineeringError("distributed_fence_frontier_stale")
            if (
                receipt.leader_id != str(row["leader_id"])
                and receipt.leader_term <= int(row["leader_term"])
            ):
                raise EngineeringError("distributed_fence_leader_conflict")
            if incoming == current:
                if (
                    digest != str(row["fence_receipt_digest"])
                    or receipt.revocation_frontier_digest
                    != str(row["revocation_frontier_digest"])
                ):
                    raise EngineeringError("distributed_fence_frontier_conflict")
                return digest

        store.connection.execute(
            "INSERT INTO distributed_fence_frontiers("
            "cluster_id,holder,leader_id,leader_term,revocation_frontier_sequence,"
            "revocation_frontier_digest,fence_receipt_digest,lease_id,"
            "authority_epoch,fencing_token,lease_revision,source_commit,source_tree,"
            "observed_unix_ns,expires_unix_ns,updated_unix_ns"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(cluster_id,holder) DO UPDATE SET "
            "leader_id=excluded.leader_id,"
            "leader_term=excluded.leader_term,"
            "revocation_frontier_sequence=excluded.revocation_frontier_sequence,"
            "revocation_frontier_digest=excluded.revocation_frontier_digest,"
            "fence_receipt_digest=excluded.fence_receipt_digest,"
            "lease_id=excluded.lease_id,"
            "authority_epoch=excluded.authority_epoch,"
            "fencing_token=excluded.fencing_token,"
            "lease_revision=excluded.lease_revision,"
            "source_commit=excluded.source_commit,"
            "source_tree=excluded.source_tree,"
            "observed_unix_ns=excluded.observed_unix_ns,"
            "expires_unix_ns=excluded.expires_unix_ns,"
            "updated_unix_ns=excluded.updated_unix_ns",
            (
                receipt.cluster_id,
                receipt.holder,
                receipt.leader_id,
                receipt.leader_term,
                receipt.revocation_frontier_sequence,
                receipt.revocation_frontier_digest,
                digest,
                receipt.lease_id,
                receipt.authority_epoch,
                receipt.fencing_token,
                receipt.lease_revision,
                receipt.source_commit,
                receipt.source_tree,
                receipt.observed_unix_ns,
                receipt.expires_unix_ns,
                now,
            ),
        )
        store._append_audit(
            "distributed_fence_admitted",
            {
                "clusterId": receipt.cluster_id,
                "holder": receipt.holder,
                "leaderId": receipt.leader_id,
                "leaderTerm": receipt.leader_term,
                "revocationFrontierSequence": receipt.revocation_frontier_sequence,
                "revocationFrontierDigest": receipt.revocation_frontier_digest,
                "fenceReceiptDigest": digest,
                "leaseId": receipt.lease_id,
                "fencingToken": receipt.fencing_token,
            },
            now,
        )
    return digest


def verify_persisted_distributed_fence(
    lease: LeaseReceipt,
    envelope: WorkEnvelope,
    receipt: DistributedFenceReceipt,
    revocation_frontier: DistributedRevocationFrontierReceipt,
    trust_store: SignatureTrustStore,
    *,
    store: EngineeringStore,
    now_ns: int | None = None,
) -> str:
    """Require the presented fence to equal the current persisted high-water mark."""
    now = store._now(now_ns)
    with store._transaction():
        digest = verify_distributed_fence(
            lease,
            envelope,
            receipt,
            revocation_frontier,
            trust_store,
            store=store,
            now_ns=now,
        )
        row = store.connection.execute(
            "SELECT * FROM distributed_fence_frontiers "
            "WHERE cluster_id=? AND holder=?",
            (receipt.cluster_id, receipt.holder),
        ).fetchone()
        if row is None:
            raise EngineeringError("distributed_fence_not_admitted")
        if (
            str(row["leader_id"]) != receipt.leader_id
            or int(row["leader_term"]) != receipt.leader_term
            or int(row["revocation_frontier_sequence"])
            != receipt.revocation_frontier_sequence
            or str(row["revocation_frontier_digest"])
            != receipt.revocation_frontier_digest
            or str(row["fence_receipt_digest"]) != digest
            or str(row["lease_id"]) != receipt.lease_id
            or int(row["authority_epoch"]) != receipt.authority_epoch
            or int(row["fencing_token"]) != receipt.fencing_token
            or int(row["lease_revision"]) != receipt.lease_revision
            or str(row["source_commit"]) != receipt.source_commit
            or str(row["source_tree"]) != receipt.source_tree
        ):
            raise EngineeringError("distributed_fence_frontier_not_current")
        return digest


def distributed_fence_frontier(
    store: EngineeringStore,
    cluster_id: str,
    holder: str,
) -> dict[str, object]:
    checked_id(cluster_id, "cluster_id")
    checked_id(holder, "holder")
    row = store.connection.execute(
        "SELECT * FROM distributed_fence_frontiers "
        "WHERE cluster_id=? AND holder=?",
        (cluster_id, holder),
    ).fetchone()
    if row is None:
        raise EngineeringError("unknown_distributed_fence_frontier")
    return {
        "clusterId": str(row["cluster_id"]),
        "holder": str(row["holder"]),
        "leaderId": str(row["leader_id"]),
        "leaderTerm": int(row["leader_term"]),
        "revocationFrontierSequence": int(row["revocation_frontier_sequence"]),
        "revocationFrontierDigest": str(row["revocation_frontier_digest"]),
        "fenceReceiptDigest": str(row["fence_receipt_digest"]),
        "leaseId": str(row["lease_id"]),
        "authorityEpoch": int(row["authority_epoch"]),
        "fencingToken": int(row["fencing_token"]),
        "leaseRevision": int(row["lease_revision"]),
        "sourceCommit": str(row["source_commit"]),
        "sourceTree": str(row["source_tree"]),
        "observedUnixNs": int(row["observed_unix_ns"]),
        "expiresUnixNs": int(row["expires_unix_ns"]),
        "updatedUnixNs": int(row["updated_unix_ns"]),
    }


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
    checked_sha256(receipt.event_digest, "audit_event_digest")
    checked_sha256(receipt.store_snapshot_digest, "store_snapshot_digest")
    if receipt.store_snapshot_digest == "0" * 64:
        raise EngineeringError("audit_anchor_store_snapshot")
    anchor = store.audit_anchor()
    snapshot = store_snapshot_digest(store)
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
        or receipt.store_snapshot_digest != snapshot
    ):
        raise EngineeringError("audit_anchor_binding_mismatch")
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
    receipts: KeyCustodyReceipt | Iterable[KeyCustodyReceipt],
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
    """Verify external hardware custody with role-separated production keys.

    The custody authority may attest several keys with one of its own signing
    identities, but the keys *being custodied* for the critical engineering
    roles must be distinct. Hardware-backing a single omnipotent key does not
    satisfy generator/evaluator/evidence separation.
    """
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or now < 0:
        raise EngineeringError("invalid_time")
    if (
        not isinstance(required_roles, tuple)
        or not required_roles
        or len(required_roles) > MAX_KEY_CUSTODY_ROLES
        or len(set(required_roles)) != len(required_roles)
    ):
        raise EngineeringError("key_custody_required_roles")
    for role in required_roles:
        checked_id(role, "required_key_custody_role")

    if isinstance(receipts, KeyCustodyReceipt):
        values = (receipts,)
    else:
        values = bounded_tuple(
            receipts,
            MAX_KEY_CUSTODY_ROLES,
            "key_custody_receipt_limit",
        )
    if not values or any(not isinstance(value, KeyCustodyReceipt) for value in values):
        raise EngineeringError("key_custody_receipts")

    required = set(required_roles)
    bindings: dict[str, tuple[str, str, str]] = {}
    seen_receipt_keys: set[tuple[str, str]] = set()
    seen_subject_identities: set[str] = set()
    canonical: list[KeyCustodyReceipt] = []
    for receipt in values:
        checked_id(receipt.provider, "key_provider")
        checked_id(receipt.key_id, "key_id")
        checked_id(receipt.subject_signing_identity, "custodied_signing_identity")
        checked_id(receipt.algorithm, "key_algorithm")
        checked_sha256(receipt.public_key_digest, "public_key_digest")
        checked_sha256(receipt.attestation_digest, "attestation_digest")
        if (
            receipt.public_key_digest == "0" * 64
            or receipt.attestation_digest == "0" * 64
        ):
            raise EngineeringError("key_custody_attestation")
        if receipt.subject_signing_identity == receipt.signing_identity:
            raise EngineeringError("key_custody_attestor_collision")
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
            receipt.hardware_backed is not True
            or receipt.external_to_engineering is not True
        ):
            raise EngineeringError("key_custody_boundary")
        if not _window(receipt.observed_unix_ns, receipt.expires_unix_ns, now):
            raise EngineeringError("key_custody_stale")
        if not trust_store.verify(
            receipt,
            receipt.issuer,
            receipt.signing_identity,
            receipt.signature,
        ):
            raise EngineeringError("key_custody_signature")

        key = (receipt.provider, receipt.key_id)
        critical_roles = required.intersection(receipt.roles)
        if len(critical_roles) > 1:
            raise EngineeringError("key_custody_role_separation")
        if critical_roles:
            role = next(iter(critical_roles))
            if role in bindings:
                raise EngineeringError("key_custody_roles")
            if (
                key in seen_receipt_keys
                or receipt.subject_signing_identity in seen_subject_identities
            ):
                raise EngineeringError("key_custody_role_separation")
            bindings[role] = (
                receipt.provider,
                receipt.key_id,
                receipt.subject_signing_identity,
            )
            seen_receipt_keys.add(key)
            seen_subject_identities.add(receipt.subject_signing_identity)
        canonical.append(receipt)

    if set(bindings) != required:
        raise EngineeringError("key_custody_roles")
    if len(set(bindings.values())) != len(required_roles):
        raise EngineeringError("key_custody_role_separation")
    canonical.sort(key=lambda item: (item.provider, item.key_id, item.roles))
    return semantic_digest([asdict(item) for item in canonical])

def verify_production_controls(
    lease: LeaseReceipt,
    envelope: WorkEnvelope,
    distributed: DistributedFenceReceipt,
    revocation_frontier: DistributedRevocationFrontierReceipt,
    store: EngineeringStore,
    audit: AuditAnchorAttestation,
    custody: KeyCustodyReceipt | Iterable[KeyCustodyReceipt],
    trust_store: SignatureTrustStore,
    *,
    now_ns: int | None = None,
) -> ProductionControlDecision:
    distributed_digest = verify_persisted_distributed_fence(
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
