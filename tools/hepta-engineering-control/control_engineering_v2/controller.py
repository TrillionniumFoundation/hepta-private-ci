"""Named repository engineering-control composition.

The controller is the source-level product composition boundary for Lane G. It
owns one EngineeringStore connection and a verification-only trust boundary.
It still has no merge, deployment, activation, promotion, release, or external
effect capability.
"""

from __future__ import annotations

from pathlib import Path

from .audit import AuditAnchorReceipt, prepare_audit_anchor, verify_audit_anchor
from .assignment import (
    WorkerIdentityReceipt,
    acquire_worker_path_lease,
    assignment_status,
    begin_assignment,
    claim_assignment,
    complete_assignment,
    completed_packages,
    fail_assignment,
    heartbeat_assignment,
    heartbeat_worker,
    refresh_authenticated_worker,
    register_authenticated_worker,
    requeue_assignment,
    revoke_worker,
)
from .control_plane import (
    EngineeringError,
    EngineeringStore,
    WorkEnvelope,
    WorkPackage,
    checked_id,
    checked_sha256,
    semantic_digest,
)
from .evidence import (
    CanonicalSourceReceipt,
    EvaluatorIndependenceReceipt,
    ExecutionReceipt,
    HmacTrustStore,
    SignatureVerifier,
    verify_integration_evidence,
)


class EngineeringController:
    """Single-writer source composition for repository engineering control."""

    def __init__(
        self,
        database: str | Path,
        repository_root: str | Path,
        repository_full_name: str,
        verifier: SignatureVerifier,
        *,
        writer_instance_id: str,
        writer_credential_chain_digest: str,
        allow_fixture_verifier: bool = False,
    ):
        self.repository_root = Path(repository_root).resolve()
        if not self.repository_root.is_dir():
            raise EngineeringError("repository_root_unavailable")
        self.repository_full_name = checked_id(
            repository_full_name, "repository_full_name"
        )
        self.writer_instance_id = checked_id(
            writer_instance_id, "writer_instance_id"
        )
        checked_sha256(
            writer_credential_chain_digest, "writer_credential_chain_digest"
        )
        if writer_credential_chain_digest == "0" * 64:
            raise EngineeringError("invalid_writer_credential_chain_digest")
        if isinstance(verifier, HmacTrustStore) and not allow_fixture_verifier:
            raise EngineeringError("fixture_verifier_forbidden")
        if not hasattr(verifier, "verify"):
            raise EngineeringError("invalid_signature_verifier")
        self.writer_credential_chain_digest = writer_credential_chain_digest
        self.verifier = verifier
        self.store = EngineeringStore(database)
        try:
            self._bind_writer()
        except BaseException:
            self.store.close()
            raise

    def _bind_writer(self) -> None:
        now = self.store._now(None)
        payload = {
            "repositoryFullName": self.repository_full_name,
            "writerInstanceId": self.writer_instance_id,
            "writerCredentialChainDigest": self.writer_credential_chain_digest,
        }
        digest = semantic_digest(payload)
        with self.store._transaction():
            row = self.store.connection.execute(
                "SELECT * FROM engineering_writer_bindings WHERE singleton=1"
            ).fetchone()
            if row is not None:
                if str(row["semantic_digest"]) != digest:
                    raise EngineeringError("writer_binding_conflict")
                return
            self.store.connection.execute(
                "INSERT INTO engineering_writer_bindings VALUES(1,?,?,?,?,?)",
                (
                    self.repository_full_name,
                    self.writer_instance_id,
                    self.writer_credential_chain_digest,
                    now,
                    digest,
                ),
            )
            self.store._append_audit(
                "engineering_writer_bound",
                {
                    "repositoryFullName": self.repository_full_name,
                    "writerInstanceId": self.writer_instance_id,
                    "writerCredentialChainDigest": self.writer_credential_chain_digest,
                },
                now,
            )

    def __enter__(self) -> "EngineeringController":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.store.__exit__(exc_type, exc, traceback)

    def close(self) -> None:
        self.store.close()

    def issue_and_schedule(
        self,
        envelope: WorkEnvelope,
        packages: tuple[WorkPackage, ...],
        *,
        generation_id: str,
        now_ns: int | None = None,
    ):
        return self.schedule_from_state(
            envelope,
            packages,
            generation_id=generation_id,
            now_ns=now_ns,
        )

    def schedule_from_state(
        self,
        envelope: WorkEnvelope,
        packages: tuple[WorkPackage, ...],
        *,
        generation_id: str,
        now_ns: int | None = None,
    ):
        self.store.issue_work_envelope(envelope, now_ns=now_ns)
        completed = completed_packages(
            self.store,
            envelope.envelope_id,
            packages,
            now_ns=now_ns,
        )
        return self.store.schedule_ready_packages(
            envelope.envelope_id,
            packages,
            completed,
            generation_id=generation_id,
            now_ns=now_ns,
        )

    def register_worker(
        self,
        identity: WorkerIdentityReceipt,
        *,
        now_ns: int | None = None,
    ):
        return register_authenticated_worker(
            self.store,
            identity,
            self.verifier,
            now_ns=now_ns,
        )

    def refresh_worker_identity(
        self,
        identity: WorkerIdentityReceipt,
        *,
        expected_revision: int,
        now_ns: int | None = None,
    ):
        return refresh_authenticated_worker(
            self.store,
            identity,
            self.verifier,
            expected_revision=expected_revision,
            now_ns=now_ns,
        )

    def acquire_worker_path_lease(self, *args, **kwargs):
        return acquire_worker_path_lease(self.store, *args, **kwargs)

    def heartbeat_worker(self, *args, **kwargs):
        return heartbeat_worker(self.store, *args, **kwargs)

    def revoke_worker(self, *args, **kwargs):
        return revoke_worker(self.store, *args, **kwargs)

    def claim_assignment(self, *args, **kwargs):
        return claim_assignment(self.store, *args, **kwargs)

    def begin_assignment(self, *args, **kwargs):
        return begin_assignment(self.store, *args, **kwargs)

    def heartbeat_assignment(self, *args, **kwargs):
        return heartbeat_assignment(self.store, *args, **kwargs)

    def complete_assignment(self, *args, **kwargs):
        return complete_assignment(self.store, *args, **kwargs)

    def fail_assignment(self, *args, **kwargs):
        return fail_assignment(self.store, *args, **kwargs)

    def requeue_assignment(self, *args, **kwargs):
        return requeue_assignment(self.store, *args, **kwargs)

    def assignment_status(self, *args, **kwargs):
        return assignment_status(self.store, *args, **kwargs)

    def verify_repository_evidence(
        self,
        source: CanonicalSourceReceipt,
        source_execution: ExecutionReceipt,
        merge_execution: ExecutionReceipt,
        independence: EvaluatorIndependenceReceipt,
        *,
        expected_document_set_digest: str,
        now_ns: int | None = None,
    ):
        return verify_integration_evidence(
            self.repository_root,
            self.repository_full_name,
            source,
            source_execution,
            merge_execution,
            independence,
            self.verifier,
            expected_document_set_digest=expected_document_set_digest,
            now_ns=now_ns,
        )

    def prepare_audit_anchor(
        self,
        *,
        signing_identity: str,
        expires_unix_ns: int,
        observed_unix_ns: int | None = None,
    ) -> AuditAnchorReceipt:
        return prepare_audit_anchor(
            self.store,
            issuer="engineering_audit_witness",
            signing_identity=signing_identity,
            observed_unix_ns=observed_unix_ns,
            expires_unix_ns=expires_unix_ns,
        )

    def verify_audit_anchor(
        self,
        anchor: AuditAnchorReceipt,
        *,
        minimum_sequence: int = 0,
        now_ns: int | None = None,
    ) -> None:
        return verify_audit_anchor(
            self.store,
            anchor,
            self.verifier,
            minimum_sequence=minimum_sequence,
            now_ns=now_ns,
        )

    def audit_projection(self, *, after_sequence: int = 0, limit: int = 512):
        return self.store.audit_projection(
            after_sequence=after_sequence,
            limit=limit,
        )
