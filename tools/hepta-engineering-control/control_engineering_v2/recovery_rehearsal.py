"""Online backup, restore, and rollback rehearsal for the SQLite owner."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
from pathlib import Path
import sqlite3
import time

from .clock import Clock, ClockPolicy, validate_observation_window
from .control_plane import EngineeringError, EngineeringStore, checked_id, semantic_digest
from .evidence import SignatureTrustStore
from .external_controls import store_snapshot_digest


@dataclass(frozen=True)
class RecoveryRehearsalReceipt:
    source_commit: str
    source_tree: str
    database_digest: str
    backup_digest: str
    restored_snapshot_digest: str
    audit_sequence: int
    audit_event_digest: str
    schema_version: int
    backup_millis: int
    restore_verify_millis: int
    rollback_rehearsed: bool
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""
    deployment_authority: bool = False
    release_authority: bool = False


def _checked_sha1(value: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or value == "0" * 40
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise EngineeringError("invalid_" + label)
    return value


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def recovery_rehearsal_digest(receipt: RecoveryRehearsalReceipt) -> str:
    if not isinstance(receipt, RecoveryRehearsalReceipt):
        raise EngineeringError("recovery_rehearsal_required")
    return semantic_digest(asdict(receipt))


def rehearse_backup_restore(
    database: str | Path,
    backup: str | Path,
    *,
    source_commit: str,
    source_tree: str,
    issuer: str,
    signing_identity: str,
    trust_store: SignatureTrustStore,
    clock_policy: ClockPolicy,
    observed_unix_ns: int,
    expires_unix_ns: int,
    clock: Clock | None = None,
    now_ns: int | None = None,
) -> RecoveryRehearsalReceipt:
    source_path = Path(database).resolve()
    backup_path = Path(backup).resolve()
    _checked_sha1(source_commit, "source_commit")
    _checked_sha1(source_tree, "source_tree")
    checked_id(issuer, "issuer")
    checked_id(signing_identity, "signing_identity")
    validate_observation_window(
        observed_unix_ns,
        expires_unix_ns,
        clock_policy,
        clock=clock,
        now_ns=now_ns,
    )
    if not source_path.is_file() or backup_path == source_path:
        raise EngineeringError("recovery_rehearsal_path")
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    if backup_path.exists():
        raise EngineeringError("recovery_backup_already_exists")

    with EngineeringStore(source_path) as store:
        store.verify_audit_chain()
        source_snapshot = store_snapshot_digest(store)
        anchor = store.audit_anchor()
        schema_version = int(store.connection.execute("PRAGMA user_version").fetchone()[0])
        started = time.perf_counter_ns()
        with sqlite3.connect(backup_path) as destination:
            store.connection.backup(destination)
        backup_millis = max(0, (time.perf_counter_ns() - started) // 1_000_000)

    database_digest = _file_digest(source_path)
    backup_digest = _file_digest(backup_path)
    restore_started = time.perf_counter_ns()
    with EngineeringStore(backup_path) as restored:
        restored.verify_audit_chain()
        restored_snapshot = store_snapshot_digest(restored)
        restored_anchor = restored.audit_anchor()
        restored_schema = int(
            restored.connection.execute("PRAGMA user_version").fetchone()[0]
        )
    restore_millis = max(0, (time.perf_counter_ns() - restore_started) // 1_000_000)
    if (
        restored_snapshot != source_snapshot
        or restored_anchor != anchor
        or restored_schema != schema_version
    ):
        raise EngineeringError("recovery_restore_mismatch")

    unsigned = RecoveryRehearsalReceipt(
        source_commit=source_commit,
        source_tree=source_tree,
        database_digest=database_digest,
        backup_digest=backup_digest,
        restored_snapshot_digest=restored_snapshot,
        audit_sequence=int(anchor["sequence"]),
        audit_event_digest=str(anchor["eventDigest"]),
        schema_version=schema_version,
        backup_millis=int(backup_millis),
        restore_verify_millis=int(restore_millis),
        rollback_rehearsed=True,
        issuer=issuer,
        signing_identity=signing_identity,
        observed_unix_ns=observed_unix_ns,
        expires_unix_ns=expires_unix_ns,
    )
    return replace(
        unsigned,
        signature=trust_store.sign(unsigned, issuer, signing_identity),
    )


def verify_recovery_rehearsal(
    receipt: RecoveryRehearsalReceipt,
    trust_store: SignatureTrustStore,
    clock_policy: ClockPolicy,
    *,
    expected_source_commit: str,
    expected_source_tree: str,
    clock: Clock | None = None,
    now_ns: int | None = None,
) -> str:
    if not isinstance(receipt, RecoveryRehearsalReceipt):
        raise EngineeringError("recovery_rehearsal_required")
    if (
        receipt.source_commit != expected_source_commit
        or receipt.source_tree != expected_source_tree
        or receipt.rollback_rehearsed is not True
        or receipt.schema_version < 1
        or receipt.audit_sequence < 1
    ):
        raise EngineeringError("recovery_rehearsal_binding")
    for value in (
        receipt.database_digest,
        receipt.backup_digest,
        receipt.restored_snapshot_digest,
        receipt.audit_event_digest,
    ):
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise EngineeringError("recovery_rehearsal_digest")
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
        raise EngineeringError("recovery_rehearsal_signature")
    return recovery_rehearsal_digest(receipt)
