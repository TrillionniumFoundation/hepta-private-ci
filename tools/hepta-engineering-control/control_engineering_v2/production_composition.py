"""Production-oriented composition over the source-level engineering product.

This class exposes renewal, checkpoint, capacity, and provider-adapter boundaries
without changing the module's authority ceiling.  External receipts still require
independent verification and operator acceptance before any deployment controller
may act.
"""

from __future__ import annotations

from .audit_checkpoint import (
    AuditCheckpointReceipt,
    OwnerStateAnchor,
    build_audit_checkpoint,
)
from .capacity_policy import (
    SQLiteCapacityDecision,
    SQLiteCapacityObservation,
    SQLiteCapacityPolicy,
    evaluate_sqlite_capacity,
)
from .clock import Clock, ClockPolicy
from .product_runtime import EngineeringControlProduct
from .worker_registration_governance import (
    WorkerKeyRotationReceipt,
    WorkerRegistrationRenewalReceipt,
    WorkerRegistrationState,
    renew_worker_registration,
    rotate_worker_signing_identity,
)


class EngineeringControlProductionProduct(EngineeringControlProduct):
    def renew_worker_registration(
        self,
        receipt: WorkerRegistrationRenewalReceipt,
        clock_policy: ClockPolicy,
        *,
        clock: Clock | None = None,
        now_ns: int | None = None,
    ) -> WorkerRegistrationState:
        return renew_worker_registration(
            self.store,
            receipt,
            self.trust_store,
            clock_policy,
            clock=clock,
            now_ns=now_ns,
        )

    def rotate_worker_signing_identity(
        self,
        receipt: WorkerKeyRotationReceipt,
        clock_policy: ClockPolicy,
        *,
        clock: Clock | None = None,
        now_ns: int | None = None,
    ) -> WorkerRegistrationState:
        return rotate_worker_signing_identity(
            self.store,
            receipt,
            self.trust_store,
            clock_policy,
            clock=clock,
            now_ns=now_ns,
        )

    def build_audit_checkpoint(
        self,
        *,
        source_commit: str,
        source_tree: str,
        issuer: str,
        signing_identity: str,
        clock_policy: ClockPolicy,
        observed_unix_ns: int,
        expires_unix_ns: int,
        previous_checkpoint: AuditCheckpointReceipt | None = None,
        previous_owner_anchor: OwnerStateAnchor | None = None,
        clock: Clock | None = None,
        now_ns: int | None = None,
    ) -> tuple[AuditCheckpointReceipt, OwnerStateAnchor]:
        return build_audit_checkpoint(
            self.store,
            source_commit=source_commit,
            source_tree=source_tree,
            issuer=issuer,
            signing_identity=signing_identity,
            trust_store=self.trust_store,
            clock_policy=clock_policy,
            observed_unix_ns=observed_unix_ns,
            expires_unix_ns=expires_unix_ns,
            previous_checkpoint=previous_checkpoint,
            previous_owner_anchor=previous_owner_anchor,
            clock=clock,
            now_ns=now_ns,
        )

    @staticmethod
    def evaluate_capacity(
        policy: SQLiteCapacityPolicy,
        observation: SQLiteCapacityObservation,
    ) -> SQLiteCapacityDecision:
        return evaluate_sqlite_capacity(policy, observation)
