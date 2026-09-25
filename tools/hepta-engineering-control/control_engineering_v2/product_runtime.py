"""Named product owner composition for control.engineering.

This object is the source-level product composition point: one durable
EngineeringStore, one exact repository identity, one injected signature-verifier
port, resource-aware planning, and the worker claim lifecycle. It grants no merge,
release, deployment, or runtime capability authority.
"""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Iterable

from .control_plane import EngineeringError, EngineeringStore, WorkEnvelope, semantic_digest
from .evidence import SignatureTrustStore
from .integration_controller import (
    IntegrationQueueGeneration,
    IntegrationQueueItem,
    IntegrationStageReceipt,
    IntegrationTerminalReceipt,
    integration_queue_item,
    observe_integration_stage,
    publish_integration_queue,
    reconcile_integration_item,
)
from .orchestration import (
    CompletionReceipt,
    EngineeringAssignment,
    EngineeringCapacity,
    MergeQueueProposal,
    EngineeringPlan,
    EngineeringWorkPackage,
    WorkerProfile,
    issue_repository_work_envelope,
    plan_engineering_work,
)
from .worker_lifecycle import (
    WorkerClaim,
    WorkerHeartbeatReceipt,
    WorkerRecoveryReport,
    WorkerRegistrationReceipt,
    WorkerResultReceipt,
    _load_plan,
    claim_assignment,
    heartbeat_claim,
    observe_claim_completion,
    recover_worker_lifecycle,
    register_worker,
    submit_worker_result,
    worker_capacity_usage,
    worker_claim,
    worker_completion_observation_digest,
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
        self._startup_reconciled = False

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

    def acquire_lease(
        self,
        lease_id: str,
        envelope_id: str,
        holder: str,
        paths: Iterable[str],
        *,
        authority_epoch: int,
        expires_unix_ns: int,
        now_ns: int | None = None,
    ):
        return self.store.acquire_path_lease(
            lease_id,
            envelope_id,
            holder,
            paths,
            authority_epoch=authority_epoch,
            expires_unix_ns=expires_unix_ns,
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

    def plan_state(self, generation_id: str) -> EngineeringPlan:
        """Recover the immutable plan, rather than recomputing historical choices."""
        with self.store._transaction():
            plan = _load_plan(self.store, generation_id)
            return EngineeringPlan(
                generation_id, plan["envelopeId"],
                tuple(EngineeringAssignment(**{**row, "review_roles": tuple(row["review_roles"])}) for row in plan["assignments"]),
                tuple(tuple(row) for row in plan["blocked"]),
                tuple(plan["integrationOrder"]),
                tuple(MergeQueueProposal(**row) for row in plan["mergeQueue"]),
                semantic_digest(plan), plan["completionFrontierDigest"],
            )

    def observe_external_completion(self, claim_id: str, completion: CompletionReceipt) -> WorkerClaim:
        """Bind an external observation to the envelope owned by this claim."""
        with self.store._transaction():
            row = self.store.connection.execute(
                "SELECT e.* FROM work_envelopes e "
                "JOIN assignment_generations a ON a.envelope_id=e.envelope_id "
                "JOIN worker_claims c ON c.generation_id=a.generation_id WHERE c.claim_id=?",
                (claim_id,),
            ).fetchone()
            if row is None:
                raise EngineeringError("unknown_worker_claim")
            envelope = WorkEnvelope(
                row["envelope_id"], row["source_commit"], row["source_tree"],
                row["objective_digest"], row["contract_digest"], row["owner"],
                tuple(json.loads(row["allowed_paths_json"])),
                tuple(json.loads(row["denied_authorities_json"])),
                row["maximum_assignments"], row["expires_unix_ns"], row["revision"],
            )
            if semantic_digest(asdict(envelope)) != row["semantic_digest"]:
                raise EngineeringError("completion_envelope_binding_mismatch")
            return self.observe_completion(claim_id, envelope, completion)

    def startup_reconcile(
        self,
        *,
        now_ns: int | None = None,
    ) -> WorkerRecoveryReport:
        report = recover_worker_lifecycle(self.store, now_ns=now_ns)
        self._startup_reconciled = True
        return report

    def worker_capacity(self, worker_id: str):
        return worker_capacity_usage(self.store, worker_id)

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
        if not self._startup_reconciled:
            raise EngineeringError("product_startup_reconciliation_required")
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

    def claim_state(self, claim_id: str) -> WorkerClaim:
        return worker_claim(self.store, claim_id)

    def completion_observation_digest(self, claim_id: str) -> str:
        return worker_completion_observation_digest(self.store, claim_id)

    def publish_integration_queue(
        self,
        plan: EngineeringPlan,
        *,
        queue_generation_id: str,
        base_commit: str,
        base_tree: str,
        now_ns: int | None = None,
    ) -> IntegrationQueueGeneration:
        return publish_integration_queue(
            self.store,
            plan,
            queue_generation_id=queue_generation_id,
            base_commit=base_commit,
            base_tree=base_tree,
            now_ns=now_ns,
        )

    def reconcile_integration(
        self,
        queue_generation_id: str,
        package_id: str,
        *,
        current_base_commit: str,
        current_base_tree: str,
        stage_receipt: IntegrationStageReceipt | None = None,
        terminal_outcome: str | None = None,
        terminal_receipt: IntegrationTerminalReceipt | None = None,
        now_ns: int | None = None,
    ) -> IntegrationQueueItem:
        if stage_receipt is not None:
            if terminal_outcome is not None or terminal_receipt is not None:
                raise ValueError("integration_stage_terminal_mix")
            return observe_integration_stage(
                self.store,
                queue_generation_id,
                package_id,
                current_base_commit=current_base_commit,
                current_base_tree=current_base_tree,
                receipt=stage_receipt,
                trust_store=self.trust_store,
                now_ns=now_ns,
            )
        return reconcile_integration_item(
            self.store,
            queue_generation_id,
            package_id,
            current_base_commit=current_base_commit,
            current_base_tree=current_base_tree,
            terminal_outcome=terminal_outcome,
            terminal_receipt=terminal_receipt,
            trust_store=self.trust_store,
            now_ns=now_ns,
        )

    def integration_item(
        self, queue_generation_id: str, package_id: str
    ) -> IntegrationQueueItem:
        return integration_queue_item(self.store, queue_generation_id, package_id)

    def audit_anchor(self) -> dict[str, object]:
        return self.store.audit_anchor()
