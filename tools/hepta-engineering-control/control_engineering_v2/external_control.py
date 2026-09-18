"""External coordination, audit-anchor and key-custody verification ports.

SQLite remains the single-host engineering owner store. Multi-host writes are
therefore admitted only with a fresh signed external leader/fencing grant, and
the highest observed worker frontier is persisted locally so an older grant
cannot be replayed after failover. Audit integrity and production key custody
remain externally governed facts: this module verifies and binds receipts but
does not manufacture those external authorities.
"""

from __future__ import annotations

from collections.abc import Iterable, Protocol
from dataclasses import asdict, dataclass, replace
import hashlib
import time

from .control_plane import (
    EngineeringError,
    EngineeringStore,
    canonical_json,
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
    subject_signing_identity: str = ""
    algorithm: str = ""
    public_key_digest: str = ""
    attestation_digest: str = ""


class CustodiedSignatureProvider(SignatureVerifier, Protocol):
    """Production signer/verifier whose private key never enters this process."""

    @property
    def signing_identity(self) -> str: ...

    @property
    def custody_receipt(self) -> KeyCustodyReceipt: ...

    def sign(
        self,
        value: object,
        issuer: str,
        signing_identity: str,
    ) -> str: ...


_STATE_TABLES = (
    "work_envelopes",
    "path_leases",
    "assignment_generations",
    "orchestration_generations",
    "assignment_generation_frontiers",
    "distributed_write_frontiers",
    "integration_decisions",
    "integration_decision_bindings",
    "integration_decision_seals",
    "engineering_schema_meta",
)


def _valid_window(observed: int, expires: int, now: int) -> bool:
    return (
        type(observed) is int
        and type(expires) is int
        and type(now) is int
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
    """Digest authoritative owner state independently of the in-file audit chain."""

    store.verify_audit_chain()
    tables = {
        str(row[0])
        for row in store.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    missing = tuple(table for table in _STATE_TABLES if table not in tables)
    if missing:
        raise EngineeringError("audit_anchor_store_incomplete")

    digest = hashlib.sha256()
    for table in _STATE_TABLES:
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
        order = ",".join(f'"{column}"' for column in (primary or columns))
        digest.update(canonical_json({"table": table, "columns": columns}))
        digest.update(b"\n")
        rows = store.connection.execute(
            f'SELECT * FROM "{table}" ORDER BY {order}'
        ).fetchall()
        for row in rows:
            body = {
                column: _sql_value(row[column])
                for column in columns
            }
            digest.update(canonical_json({"table": table, "row": body}))
            digest.update(b"\n")
    return digest.hexdigest()


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
    """Verify one external leader/fence at a worker-write boundary."""

    now = time.time_ns() if now_ns is None else now_ns
    if not isinstance(grant, DistributedWriteGrant):
        raise EngineeringError("distributed_write_grant_required")
    checked_id(worker_id, "worker_id")
    checked_id(grant.coordinator_id, "coordinator_id")
    if grant.worker_id != worker_id:
        raise EngineeringError("distributed_worker_mismatch")
    if grant.issuer != "external_coordinator" or not grant.signing_identity:
        raise EngineeringError("distributed_coordinator_issuer")
    if not _git_sha(source_commit) or not _git_sha(source_tree):
        raise EngineeringError("invalid_git_identity")
    if grant.source_commit != source_commit or grant.source_tree != source_tree:
        raise EngineeringError("distributed_source_mismatch")
    if (
        type(minimum_leader_epoch) is not int
        or minimum_leader_epoch < 1
        or type(minimum_fencing_token) is not int
        or minimum_fencing_token < 1
        or type(grant.leader_epoch) is not int
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
    if not verifier.verify(
        grant, grant.issuer, grant.signing_identity, grant.signature
    ):
        raise EngineeringError("distributed_write_grant_signature")
    return replace(grant, paths=admitted)


def admit_distributed_write_grant(
    store: EngineeringStore,
    grant: DistributedWriteGrant,
    verifier: SignatureVerifier,
    *,
    worker_id: str,
    source_commit: str,
    source_tree: str,
    requested_paths: Iterable[str],
    now_ns: int | None = None,
) -> DistributedWriteGrant:
    """Persist the highest observed worker fence and reject stale replay.

    The external coordinator remains the consensus/leader authority. The local
    owner only remembers the highest admitted (leader_epoch, fencing_token) for a
    worker, so a process restart cannot make a superseded grant valid again.
    """

    now = store._now(now_ns)
    verified = verify_distributed_write_grant(
        grant,
        verifier,
        worker_id=worker_id,
        source_commit=source_commit,
        source_tree=source_tree,
        requested_paths=requested_paths,
        minimum_leader_epoch=1,
        minimum_fencing_token=1,
        now_ns=now,
    )
    grant_digest = semantic_digest(asdict(verified))
    with store._transaction():
        row = store.connection.execute(
            "SELECT * FROM distributed_write_frontiers WHERE worker_id=?",
            (worker_id,),
        ).fetchone()
        if row is not None:
            current_epoch = int(row["leader_epoch"])
            current_token = int(row["fencing_token"])
            incoming = (verified.leader_epoch, verified.fencing_token)
            current = (current_epoch, current_token)
            if incoming < current:
                raise EngineeringError("distributed_fence_stale")
            if (
                verified.coordinator_id != str(row["coordinator_id"])
                and verified.leader_epoch <= current_epoch
            ):
                raise EngineeringError("distributed_coordinator_conflict")
            if incoming == current:
                if grant_digest != str(row["grant_digest"]):
                    raise EngineeringError("distributed_fence_conflict")
                return verified

        store.connection.execute(
            "INSERT INTO distributed_write_frontiers("
            "worker_id,coordinator_id,leader_epoch,fencing_token,source_commit,"
            "source_tree,grant_digest,issuer,signing_identity,observed_unix_ns,"
            "expires_unix_ns,updated_unix_ns"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(worker_id) DO UPDATE SET "
            "coordinator_id=excluded.coordinator_id,"
            "leader_epoch=excluded.leader_epoch,"
            "fencing_token=excluded.fencing_token,"
            "source_commit=excluded.source_commit,"
            "source_tree=excluded.source_tree,"
            "grant_digest=excluded.grant_digest,"
            "issuer=excluded.issuer,"
            "signing_identity=excluded.signing_identity,"
            "observed_unix_ns=excluded.observed_unix_ns,"
            "expires_unix_ns=excluded.expires_unix_ns,"
            "updated_unix_ns=excluded.updated_unix_ns",
            (
                worker_id,
                verified.coordinator_id,
                verified.leader_epoch,
                verified.fencing_token,
                verified.source_commit,
                verified.source_tree,
                grant_digest,
                verified.issuer,
                verified.signing_identity,
                verified.observed_unix_ns,
                verified.expires_unix_ns,
                now,
            ),
        )
        store._append_audit(
            "distributed_write_grant_admitted",
            {
                "workerId": worker_id,
                "coordinatorId": verified.coordinator_id,
                "leaderEpoch": verified.leader_epoch,
                "fencingToken": verified.fencing_token,
                "sourceCommit": verified.source_commit,
                "sourceTree": verified.source_tree,
                "grantDigest": grant_digest,
            },
            now,
        )
    return verified


def distributed_write_frontier(
    store: EngineeringStore,
    worker_id: str,
) -> dict[str, object]:
    checked_id(worker_id, "worker_id")
    row = store.connection.execute(
        "SELECT * FROM distributed_write_frontiers WHERE worker_id=?",
        (worker_id,),
    ).fetchone()
    if row is None:
        raise EngineeringError("unknown_distributed_write_frontier")
    return {
        "workerId": str(row["worker_id"]),
        "coordinatorId": str(row["coordinator_id"]),
        "leaderEpoch": int(row["leader_epoch"]),
        "fencingToken": int(row["fencing_token"]),
        "sourceCommit": str(row["source_commit"]),
        "sourceTree": str(row["source_tree"]),
        "grantDigest": str(row["grant_digest"]),
        "issuer": str(row["issuer"]),
        "signingIdentity": str(row["signing_identity"]),
        "observedUnixNs": int(row["observed_unix_ns"]),
        "expiresUnixNs": int(row["expires_unix_ns"]),
        "updatedUnixNs": int(row["updated_unix_ns"]),
    }


def export_audit_anchor(
    store: EngineeringStore,
    *,
    database_id: str,
) -> AuditAnchorReceipt:
    """Export the local audit head plus authoritative-state digest for signing."""

    checked_id(database_id, "database_id")
    store.verify_audit_chain()
    row = store.connection.execute(
        "SELECT sequence,event_digest FROM audit_events ORDER BY sequence DESC LIMIT 1"
    ).fetchone()
    sequence = 0 if row is None else int(row["sequence"])
    event_digest = "0" * 64 if row is None else str(row["event_digest"])
    snapshot_digest = store_snapshot_digest(store)
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
    if (
        type(minimum_sequence) is not int
        or minimum_sequence < 0
        or type(receipt.sequence) is not int
        or receipt.sequence < minimum_sequence
    ):
        raise EngineeringError("audit_anchor_stale_sequence")
    checked_sha256(receipt.event_digest, "event_digest")
    checked_sha256(receipt.store_snapshot_digest, "store_snapshot_digest")
    if receipt.issuer != "external_audit_anchor" or not receipt.signing_identity:
        raise EngineeringError("audit_anchor_issuer")
    if not _valid_window(receipt.observed_unix_ns, receipt.expires_unix_ns, now):
        raise EngineeringError("audit_anchor_stale")
    if not verifier.verify(
        receipt, receipt.issuer, receipt.signing_identity, receipt.signature
    ):
        raise EngineeringError("audit_anchor_signature")
    return receipt


def verify_store_audit_anchor(
    store: EngineeringStore,
    receipt: AuditAnchorReceipt,
    verifier: SignatureVerifier,
    *,
    expected_database_id: str,
    minimum_sequence: int = 0,
    now_ns: int | None = None,
) -> AuditAnchorReceipt:
    """Verify the external receipt and bind it back to the current owner state."""

    verified = verify_audit_anchor_receipt(
        receipt,
        verifier,
        expected_database_id=expected_database_id,
        minimum_sequence=minimum_sequence,
        now_ns=now_ns,
    )
    store.verify_audit_chain()
    row = store.connection.execute(
        "SELECT sequence,event_digest FROM audit_events ORDER BY sequence DESC LIMIT 1"
    ).fetchone()
    sequence = 0 if row is None else int(row["sequence"])
    event_digest = "0" * 64 if row is None else str(row["event_digest"])
    if (
        sequence != verified.sequence
        or event_digest != verified.event_digest
        or store_snapshot_digest(store) != verified.store_snapshot_digest
    ):
        raise EngineeringError("audit_anchor_store_mismatch")
    return verified


def verify_key_custody_receipt(
    receipt: KeyCustodyReceipt,
    verifier: SignatureVerifier,
    *,
    expected_purpose: str = "engineering-evidence-verification",
    expected_subject_signing_identity: str | None = None,
    now_ns: int | None = None,
) -> KeyCustodyReceipt:
    """Require external, hardware-backed, non-exportable signing-key custody."""

    now = time.time_ns() if now_ns is None else now_ns
    if not isinstance(receipt, KeyCustodyReceipt):
        raise EngineeringError("key_custody_receipt_required")
    checked_id(receipt.provider, "key_provider")
    checked_id(receipt.key_id, "key_id")
    checked_id(receipt.subject_signing_identity, "custodied_signing_identity")
    checked_id(receipt.algorithm, "key_algorithm")
    checked_sha256(receipt.public_key_digest, "public_key_digest")
    checked_sha256(receipt.attestation_digest, "attestation_digest")
    if receipt.purpose != expected_purpose:
        raise EngineeringError("key_custody_purpose")
    if (
        expected_subject_signing_identity is not None
        and receipt.subject_signing_identity != expected_subject_signing_identity
    ):
        raise EngineeringError("key_custody_identity_mismatch")
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


def verify_custodied_signature_provider(
    provider: CustodiedSignatureProvider,
    custody_verifier: SignatureVerifier,
    *,
    expected_purpose: str = "engineering-evidence-verification",
    now_ns: int | None = None,
) -> CustodiedSignatureProvider:
    """Bind a production signing port to its independently attested key identity."""

    if not isinstance(provider.signing_identity, str) or not provider.signing_identity:
        raise EngineeringError("custodied_signing_identity")
    verify_key_custody_receipt(
        provider.custody_receipt,
        custody_verifier,
        expected_purpose=expected_purpose,
        expected_subject_signing_identity=provider.signing_identity,
        now_ns=now_ns,
    )
    return provider
