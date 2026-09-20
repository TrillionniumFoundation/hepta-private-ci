"""Named product owner composition for control.engineering.

This object is the source-level product composition point: one durable
EngineeringStore, one exact repository identity, one injected signature-verifier
port, resource-aware planning, and the worker claim lifecycle. It grants no merge,
release, deployment, or runtime capability authority.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .control_plane import EngineeringStore, WorkEnvelope
from .evidence import SignatureTrustStore
from .orchestration import (
    CompletionReceipt,
    EngineeringCapacity,
    EngineeringPlan,
    EngineeringWorkPackage,
    WorkerProfile,
    issue_repository_work_envelope,
    plan_engineering_work,
)
from .worker_lifecycle import (
    WorkerClaim,
    WorkerHeartbeatReceipt,
    WorkerRegistrationReceipt,
    WorkerResultReceipt,
    claim_assignment,
    heartbeat_claim,
    observe_claim_completion,
    register_worker,
    submit_worker_result,
)


class EngineeringControlProduct:
    def __init__(
        self,
        database: str | Path,
        repository: str | Path,
        *,
        expected_repository: str,
        trust_store: SignatureTrustStore,
    ):
        self.repository = Path(repository).resolve()
        self.expected_repository = expected_repository
        self.trust_store = trust_store
        self.store = EngineeringStore(database)

    def __enter__(self) -> "EngineeringControlProduct":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if exc_type is None:
            self.store.close()
        else:
            self.store.connection.rollback()
            self.store.connection.close()

    def close(self) -> None:
        self.store.close()

    def admit_repository_envelope(
        self,
        envelope: WorkEnvelope,
        *,
        now_ns: int | None = None,
    ) -> WorkEnvelope:
        return issue_repository_work_envelope(
            self.repository,
            self.store,
            envelope,
            expected_repository=self.expected_repository,
            now_ns=now_ns,
        )

    def plan_work(
        self,
        envelope: WorkEnvelope,
        packages: Iterable[EngineeringWorkPackage],
        workers: Iterable[WorkerProfile],
        completion_receipts: Iterable[CompletionReceipt],
        capacity: EngineeringCapacity,
        *,
        generation_id: str,
        now_ns: int | None = None,
    ) -> EngineeringPlan:
        return plan_engineering_work(
            self.store,
            envelope,
            packages,
            workers,
            completion_receipts,
            self.trust_store,
            capacity,
            generation_id=generation_id,
            now_ns=now_ns,
        )

    def register_worker(
        self,
        receipt: WorkerRegistrationReceipt,
        *,
        now_ns: int | None = None,
    ) -> str:
        return register_worker(
            self.store,
            receipt,
            self.trust_store,
            now_ns=now_ns,
        )

    def claim(
        self,
        generation_id: str,
        package_id: str,
        worker_id: str,
        lease_id: str,
        *,
        heartbeat_ttl_ns: int,
        now_ns: int | None = None,
    ) -> WorkerClaim:
        return claim_assignment(
            self.store,
            generation_id,
            package_id,
            worker_id,
            lease_id,
            heartbeat_ttl_ns=heartbeat_ttl_ns,
            now_ns=now_ns,
        )

    def heartbeat(
        self,
        receipt: WorkerHeartbeatReceipt,
        *,
        heartbeat_ttl_ns: int,
        now_ns: int | None = None,
    ) -> WorkerClaim:
        return heartbeat_claim(
            self.store,
            receipt,
            self.trust_store,
            heartbeat_ttl_ns=heartbeat_ttl_ns,
            now_ns=now_ns,
        )

    def submit_result(
        self,
        receipt: WorkerResultReceipt,
        *,
        now_ns: int | None = None,
    ) -> WorkerClaim:
        return submit_worker_result(
            self.store,
            receipt,
            self.trust_store,
            now_ns=now_ns,
        )

    def observe_completion(
        self,
        claim_id: str,
        envelope: WorkEnvelope,
        completion: CompletionReceipt,
        *,
        now_ns: int | None = None,
    ) -> WorkerClaim:
        return observe_claim_completion(
            self.store,
            claim_id,
            envelope,
            completion,
            self.trust_store,
            now_ns=now_ns,
        )

    def audit_anchor(self) -> dict[str, object]:
        return self.store.audit_anchor()
