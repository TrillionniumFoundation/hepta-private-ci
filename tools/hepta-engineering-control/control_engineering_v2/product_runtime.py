"""Named product owner composition for control.engineering.

This object is the source-level product composition point: one durable
EngineeringStore, one exact repository identity, one injected signature-verifier
port, resource-aware planning, measured capacity admission, and the worker claim
lifecycle. It grants no merge, release, deployment, or runtime capability authority.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .capacity_policy import (
    ControlCapacityDecision,
    ControlCapacityPolicy,
    REFERENCE_CONTROL_CAPACITY_POLICY,
    evaluate_control_capacity,
    require_new_work_capacity,
)
from .clock_policy import (
    ClockSkewPolicy,
    STRICT_CLOCK_POLICY,
    checked_now,
    validate_signed_window,
)
from .control_plane import EngineeringError, EngineeringStore, WorkEnvelope
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
from .worker_registration import (
    WorkerRegistrationRenewalReceipt,
    renew_worker_registration,
)


class EngineeringControlProduct:
    def __init__(
        self,
        database: str | Path,
        repository: str | Path,
        *,
        expected_repository: str,
        trust_store: SignatureTrustStore,
        clock_policy: ClockSkewPolicy = STRICT_CLOCK_POLICY,
        capacity_policy: ControlCapacityPolicy = REFERENCE_CONTROL_CAPACITY_POLICY,
    ):
        if not isinstance(clock_policy, ClockSkewPolicy):
            raise EngineeringError("clock_policy_required")
        if not isinstance(capacity_policy, ControlCapacityPolicy):
            raise EngineeringError("control_capacity_policy_required")
        self.repository = Path(repository).resolve()
        self.expected_repository = expected_repository
        self.trust_store = trust_store
        self.clock_policy = clock_policy
        self.capacity_policy = capacity_policy
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

    def capacity_status(self, *, now_ns: int | None = None) -> ControlCapacityDecision:
        return evaluate_control_capacity(
            self.store,
            self.capacity_policy,
            now_ns=now_ns,
        )

    def _admit_new_work(self, *, now_ns: int | None = None) -> None:
        require_new_work_capacity(
            self.store,
            self.capacity_policy,
            now_ns=now_ns,
        )

    def _validate_receipt_window(
        self,
        receipt: object,
        *,
        error_code: str,
        now_ns: int | None = None,
    ) -> None:
        try:
            observed = getattr(receipt, "observed_unix_ns")
            expires = getattr(receipt, "expires_unix_ns")
        except AttributeError:
            raise EngineeringError(error_code) from None
        validate_signed_window(
            observed,
            expires,
            checked_now(now_ns),
            self.clock_policy,
            error_code=error_code,
        )

    def admit_repository_envelope(
        self,
        envelope: WorkEnvelope,
        *,
        now_ns: int | None = None,
    ) -> WorkEnvelope:
        self._admit_new_work(now_ns=now_ns)
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
        self._admit_new_work(now_ns=now_ns)
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
        self._admit_new_work(now_ns=now_ns)
        completion_values = tuple(completion_receipts)
        for receipt in completion_values:
            self._validate_receipt_window(
                receipt,
                error_code="product_completion_receipt_stale",
                now_ns=now_ns,
            )
        return plan_engineering_work(
            self.store,
            envelope,
            packages,
            workers,
            completion_values,
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
        self._admit_new_work(now_ns=now_ns)
        self._validate_receipt_window(
            receipt,
            error_code="product_worker_registration_stale",
            now_ns=now_ns,
        )
        return register_worker(
            self.store,
            receipt,
            self.trust_store,
            now_ns=now_ns,
        )

    def renew_worker(
        self,
        receipt: WorkerRegistrationRenewalReceipt,
        *,
        now_ns: int | None = None,
    ) -> str:
        return renew_worker_registration(
            self.store,
            receipt,
            self.trust_store,
            clock_policy=self.clock_policy,
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
        self._admit_new_work(now_ns=now_ns)
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
        self._validate_receipt_window(
            receipt,
            error_code="product_worker_heartbeat_stale",
            now_ns=now_ns,
        )
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
        self._validate_receipt_window(
            receipt,
            error_code="product_worker_result_stale",
            now_ns=now_ns,
        )
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
        self._validate_receipt_window(
            completion,
            error_code="product_completion_receipt_stale",
            now_ns=now_ns,
        )
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
        self._admit_new_work(now_ns=now_ns)
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
            self._validate_receipt_window(
                stage_receipt,
                error_code="product_integration_stage_receipt_stale",
                now_ns=now_ns,
            )
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
        if terminal_receipt is not None:
            self._validate_receipt_window(
                terminal_receipt,
                error_code="product_integration_terminal_receipt_stale",
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
