"""Named product owner composition for control.engineering.

This object is the source-level product composition point: one durable
EngineeringStore, one exact repository identity, one injected signature-verifier
port, resource-aware planning, and the worker claim lifecycle. It grants no merge,
release, deployment, or runtime capability authority.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable, TypeVar

from .audit_checkpoint import (
    AuditCheckpoint,
    advance_audit_checkpoint,
    create_audit_checkpoint,
    verify_audit_checkpoint,
)
from .capacity_policy import (
    DatabaseCapacityDecision,
    DatabaseCapacityPolicy,
    enforce_database_capacity,
    evaluate_database_capacity,
)
from .clock_policy import ClockPolicy
from .control_plane import EngineeringError, EngineeringStore, WorkEnvelope
from .evidence import SignatureTrustStore
from .git_security import run_git
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
    EngineeringCapacity,
    EngineeringPlan,
    EngineeringWorkPackage,
    WorkerProfile,
    issue_repository_work_envelope,
    plan_engineering_work,
)
from .worker_identity import (
    WorkerRegistrationRenewalDecision,
    WorkerRegistrationRenewalReceipt,
    renew_worker_registration,
)
from .worker_lifecycle import (
    WorkerClaim,
    WorkerHeartbeatReceipt,
    WorkerRecoveryReport,
    WorkerRegistrationReceipt,
    WorkerResultReceipt,
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

_T = TypeVar("_T")


class EngineeringControlProduct:
    def __init__(
        self,
        database: str | Path,
        repository: str | Path,
        *,
        expected_repository: str,
        trust_store: SignatureTrustStore,
        clock_policy: ClockPolicy = ClockPolicy(),
        capacity_policy: DatabaseCapacityPolicy | None = None,
    ):
        if not isinstance(clock_policy, ClockPolicy):
            raise EngineeringError("invalid_clock_policy")
        if capacity_policy is not None and not isinstance(
            capacity_policy, DatabaseCapacityPolicy
        ):
            raise EngineeringError("invalid_capacity_policy")
        self.repository = Path(repository).resolve()
        self.expected_repository = expected_repository
        self.trust_store = trust_store
        self.clock_policy = clock_policy
        self.capacity_policy = capacity_policy or DatabaseCapacityPolicy()
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

    def _capacity_guarded_write(self, operation: Callable[[], _T]) -> _T:
        """Run one product mutation inside a capacity-checked owner transaction.

        Lower-level operations already use the store transaction helper.  The helper
        is deliberately re-entrant, so this outer boundary makes the post-mutation
        capacity check part of the same commit.  A write that crosses a hard ceiling
        is rolled back rather than retained with a later warning.
        """
        with self.store._transaction():
            enforce_database_capacity(self.store, self.capacity_policy)
            result = operation()
            enforce_database_capacity(self.store, self.capacity_policy)
            return result

    def admit_repository_envelope(
        self,
        envelope: WorkEnvelope,
        *,
        now_ns: int | None = None,
    ) -> WorkEnvelope:
        return self._capacity_guarded_write(
            lambda: issue_repository_work_envelope(
                self.repository,
                self.store,
                envelope,
                expected_repository=self.expected_repository,
                now_ns=now_ns,
            )
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
        paths_value = tuple(paths)
        return self._capacity_guarded_write(
            lambda: self.store.acquire_path_lease(
                lease_id,
                envelope_id,
                holder,
                paths_value,
                authority_epoch=authority_epoch,
                expires_unix_ns=expires_unix_ns,
                now_ns=now_ns,
            )
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
        packages_value = tuple(packages)
        workers_value = tuple(workers)
        completions_value = tuple(completion_receipts)
        return self._capacity_guarded_write(
            lambda: plan_engineering_work(
                self.store,
                envelope,
                packages_value,
                workers_value,
                completions_value,
                self.trust_store,
                capacity,
                generation_id=generation_id,
                now_ns=now_ns,
            )
        )

    def startup_reconcile(
        self,
        *,
        now_ns: int | None = None,
    ) -> WorkerRecoveryReport:
        report = self._capacity_guarded_write(
            lambda: recover_worker_lifecycle(self.store, now_ns=now_ns)
        )
        self._startup_reconciled = True
        return report

    def database_capacity(self) -> DatabaseCapacityDecision:
        return evaluate_database_capacity(self.store, self.capacity_policy)

    def create_audit_checkpoint(self, *, observed_unix_ns: int) -> AuditCheckpoint:
        source_commit = run_git(self.repository, "rev-parse", "HEAD")
        source_tree = run_git(self.repository, "rev-parse", "HEAD^{tree}")
        return create_audit_checkpoint(
            self.store,
            source_commit=source_commit,
            source_tree=source_tree,
            observed_unix_ns=observed_unix_ns,
        )

    def advance_audit_checkpoint(
        self,
        checkpoint: AuditCheckpoint,
        *,
        observed_unix_ns: int,
    ) -> AuditCheckpoint:
        source_commit = run_git(self.repository, "rev-parse", "HEAD")
        source_tree = run_git(self.repository, "rev-parse", "HEAD^{tree}")
        return advance_audit_checkpoint(
            self.store,
            checkpoint,
            source_commit=source_commit,
            source_tree=source_tree,
            observed_unix_ns=observed_unix_ns,
        )

    def verify_audit_checkpoint(
        self,
        checkpoint: AuditCheckpoint,
        *,
        require_current_state: bool = True,
    ) -> None:
        verify_audit_checkpoint(
            self.store,
            checkpoint,
            require_current_state=require_current_state,
        )

    def worker_capacity(self, worker_id: str):
        return worker_capacity_usage(self.store, worker_id)

    def register_worker(
        self,
        receipt: WorkerRegistrationReceipt,
        *,
        now_ns: int | None = None,
    ) -> str:
        return self._capacity_guarded_write(
            lambda: register_worker(
                self.store,
                receipt,
                self.trust_store,
                now_ns=now_ns,
            )
        )

    def renew_worker(
        self,
        receipt: WorkerRegistrationRenewalReceipt,
        *,
        now_ns: int,
    ) -> WorkerRegistrationRenewalDecision:
        return self._capacity_guarded_write(
            lambda: renew_worker_registration(
                self.store,
                receipt,
                self.trust_store,
                now_ns=now_ns,
                clock_policy=self.clock_policy,
            )
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
        return self._capacity_guarded_write(
            lambda: claim_assignment(
                self.store,
                generation_id,
                package_id,
                worker_id,
                lease_id,
                heartbeat_ttl_ns=heartbeat_ttl_ns,
                now_ns=now_ns,
            )
        )

    def heartbeat(
        self,
        receipt: WorkerHeartbeatReceipt,
        *,
        heartbeat_ttl_ns: int,
        now_ns: int | None = None,
    ) -> WorkerClaim:
        return self._capacity_guarded_write(
            lambda: heartbeat_claim(
                self.store,
                receipt,
                self.trust_store,
                heartbeat_ttl_ns=heartbeat_ttl_ns,
                now_ns=now_ns,
            )
        )

    def submit_result(
        self,
        receipt: WorkerResultReceipt,
        *,
        now_ns: int | None = None,
    ) -> WorkerClaim:
        return self._capacity_guarded_write(
            lambda: submit_worker_result(
                self.store,
                receipt,
                self.trust_store,
                now_ns=now_ns,
            )
        )

    def observe_completion(
        self,
        claim_id: str,
        envelope: WorkEnvelope,
        completion: CompletionReceipt,
        *,
        now_ns: int | None = None,
    ) -> WorkerClaim:
        return self._capacity_guarded_write(
            lambda: observe_claim_completion(
                self.store,
                claim_id,
                envelope,
                completion,
                self.trust_store,
                now_ns=now_ns,
            )
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
        return self._capacity_guarded_write(
            lambda: publish_integration_queue(
                self.store,
                plan,
                queue_generation_id=queue_generation_id,
                base_commit=base_commit,
                base_tree=base_tree,
                now_ns=now_ns,
            )
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
            return self._capacity_guarded_write(
                lambda: observe_integration_stage(
                    self.store,
                    queue_generation_id,
                    package_id,
                    current_base_commit=current_base_commit,
                    current_base_tree=current_base_tree,
                    receipt=stage_receipt,
                    trust_store=self.trust_store,
                    now_ns=now_ns,
                )
            )
        return self._capacity_guarded_write(
            lambda: reconcile_integration_item(
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
        )

    def integration_item(
        self, queue_generation_id: str, package_id: str
    ) -> IntegrationQueueItem:
        return integration_queue_item(self.store, queue_generation_id, package_id)

    def audit_anchor(self) -> dict[str, object]:
        return self.store.audit_anchor()
