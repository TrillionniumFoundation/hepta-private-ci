"""Named product owner composition for control.engineering.

One durable EngineeringStore owns coordination facts. The TEMP capacity monitor
is rebuildable connection-local data, never a second authority or result store.
No merge, release, deployment, or runtime capability authority is granted here.
"""
from __future__ import annotations

from pathlib import Path
from types import TracebackType
from typing import Iterable

from .audit_checkpoint import (
    AuditCheckpoint,
    AuditReadCut,
    AuditSuffixPage,
    AuditVerificationBudget,
    create_audit_checkpoint,
    verify_audit_suffix,
    verify_audit_suffix_page,
)
from .capacity_policy import (
    StoreCapacityMonitor,
    StoreCapacityPolicy,
    evaluate_store_capacity,
)
from .control_plane import EngineeringError, EngineeringStore, LeaseReceipt, WorkEnvelope
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
    EngineeringCapacity,
    EngineeringPlan,
    EngineeringWorkPackage,
    WorkerProfile,
    issue_repository_work_envelope,
    plan_engineering_work,
)
from .time_policy import ClockSkewPolicy, STRICT_CLOCK_SKEW_POLICY
from .worker_registration import WorkerRegistrationRenewalReceipt, renew_worker_registration
from .worker_lifecycle import (
    WorkerCapacityUsage,
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


class EngineeringControlProduct:
    def __init__(
        self,
        database: str | Path,
        repository: str | Path,
        *,
        expected_repository: str,
        trust_store: SignatureTrustStore,
    ) -> None:
        self.repository = Path(repository).resolve()
        self.expected_repository = expected_repository
        self.trust_store = trust_store
        self.store = EngineeringStore(database)
        try:
            self._capacity_monitor = StoreCapacityMonitor(self.store)
        except BaseException:
            self.store.connection.close()
            raise
        self._startup_reconciled = False
        self._startup_recovery_report: WorkerRecoveryReport | None = None

    @classmethod
    def open_and_reconcile(
        cls,
        database: str | Path,
        repository: str | Path,
        *,
        expected_repository: str,
        trust_store: SignatureTrustStore,
        now_ns: int | None = None,
    ) -> "EngineeringControlProduct":
        """Open the durable owner and complete startup recovery atomically.

        Product callers should prefer this constructor.  A returned object has
        validated/opened its store and reconciled stale registrations, leases,
        claims, envelopes and durable capacity reservations.  Failure closes the
        connection before the error escapes, so a partially reconciled owner is
        never returned to the caller.
        """
        product = cls(
            database,
            repository,
            expected_repository=expected_repository,
            trust_store=trust_store,
        )
        try:
            product.startup_reconcile(now_ns=now_ns)
        except BaseException:
            try:
                product.store.connection.rollback()
            finally:
                product.store.connection.close()
            raise
        return product

    @property
    def ready(self) -> bool:
        """Whether startup recovery completed for this process instance."""
        return self._startup_reconciled

    @property
    def startup_recovery_report(self) -> WorkerRecoveryReport:
        if not self._startup_reconciled or self._startup_recovery_report is None:
            raise EngineeringError("product_startup_reconciliation_required")
        return self._startup_recovery_report

    def __enter__(self) -> "EngineeringControlProduct":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is None:
            self.store.close()
        else:
            self.store.connection.rollback()
            self.store.connection.close()

    def close(self) -> None:
        self.store.close()

    def capacity_state(
        self,
        policy: StoreCapacityPolicy = StoreCapacityPolicy(),
        *,
        calibrate: bool = False,
    ) -> dict[str, object]:
        if type(calibrate) is not bool:
            raise EngineeringError("invalid_capacity_calibration_request")
        if calibrate:
            self._capacity_monitor.reconcile()
        return evaluate_store_capacity(self.store, policy, monitor=self._capacity_monitor)

    def create_audit_checkpoint(self, *, now_ns: int | None = None) -> AuditCheckpoint:
        return create_audit_checkpoint(self.store, now_ns=now_ns)

    def verify_audit_suffix(
        self,
        checkpoint: AuditCheckpoint,
        *,
        budget: AuditVerificationBudget = AuditVerificationBudget(),
        through: AuditReadCut | None = None,
    ) -> dict[str, object]:
        return verify_audit_suffix(self.store, checkpoint, budget=budget, through=through)

    def verify_audit_suffix_page(
        self,
        checkpoint: AuditCheckpoint,
        *,
        budget: AuditVerificationBudget = AuditVerificationBudget(),
        through: AuditReadCut | None = None,
    ) -> AuditSuffixPage:
        return verify_audit_suffix_page(self.store, checkpoint, budget=budget, through=through)

    def renew_worker_registration(
        self,
        receipt: WorkerRegistrationRenewalReceipt,
        *,
        now_ns: int | None = None,
        clock_policy: ClockSkewPolicy = STRICT_CLOCK_SKEW_POLICY,
    ) -> str:
        return renew_worker_registration(
            self.store, receipt, self.trust_store, now_ns=now_ns,
            clock_policy=clock_policy,
        )

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
    ) -> LeaseReceipt:
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

    def startup_reconcile(
        self,
        *,
        now_ns: int | None = None,
    ) -> WorkerRecoveryReport:
        self._startup_reconciled = False
        report = recover_worker_lifecycle(self.store, now_ns=now_ns)
        self._capacity_monitor.reconcile()
        self._startup_recovery_report = report
        self._startup_reconciled = True
        return report

    def worker_capacity(self, worker_id: str) -> WorkerCapacityUsage:
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
