"""Real-provider production composition for ``control.engineering``.

The composition calls externally configured HTTPS providers, verifies their
signed receipts through the existing trust-store ports, persists distributed
fencing frontiers, and hands independently observed completion/terminal receipts
to the named product owner. It has no fixture fallback and grants no authority.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

from .control_plane import (
    EngineeringError,
    EngineeringStore,
    LeaseReceipt,
    WorkEnvelope,
    checked_id,
    semantic_digest,
)
from .evidence import SignatureTrustStore
from .external_controls import (
    AuditAnchorAttestation,
    DistributedFenceReceipt,
    DistributedRevocationFrontierReceipt,
    KeyCustodyReceipt,
    ProductionControlDecision,
    admit_distributed_fence,
    store_snapshot_digest,
    verify_production_controls,
)
from .external_runtime import (
    ExternalProviderObservation,
    ExternalReceiptClient,
    JsonTransport,
    ProductionProviderSet,
    decode_external_receipt,
)
from .integration_controller import IntegrationQueueItem, IntegrationTerminalReceipt
from .orchestration import CompletionReceipt
from .product_runtime import EngineeringControlProduct
from .worker_lifecycle import WorkerClaim

_REQUIRED_KEY_ROLES = (
    "source_authority",
    "ci_executor",
    "independent_evaluator",
    "engineering_evidence_binder",
)


@dataclass(frozen=True)
class ProductionExternalEvidence:
    provider_configuration_digest: str
    revocation_frontier_receipt_digest: str
    distributed_fence_receipt_digest: str
    admitted_fence_digest: str
    audit_anchor_receipt_digest: str
    key_custody_receipt_digests: tuple[str, ...]
    production_control_digest: str
    provider_observation_digests: tuple[str, ...]
    runtime_authority: bool = False
    merge_authority: bool = False
    deployment_authority: bool = False
    release_authority: bool = False


@dataclass(frozen=True)
class IndependentCompletionObservation:
    provider_observation_digest: str
    completion_receipt_digest: str
    claim: WorkerClaim
    runtime_authority: bool = False
    merge_authority: bool = False


@dataclass(frozen=True)
class IndependentTerminalObservation:
    provider_observation_digest: str
    terminal_receipt_digest: str
    item: IntegrationQueueItem
    runtime_authority: bool = False
    merge_authority: bool = False


class ProductionExternalControlClient:
    def __init__(
        self,
        providers: ProductionProviderSet,
        trust_store: SignatureTrustStore,
        *,
        transport: JsonTransport | None = None,
    ):
        if not isinstance(providers, ProductionProviderSet):
            raise EngineeringError("production_provider_set_required")
        self.providers = providers
        self.trust_store = trust_store
        self.transport = transport

    def _client(self, endpoint) -> ExternalReceiptClient:
        return ExternalReceiptClient(endpoint, transport=self.transport)

    @staticmethod
    def _observation_digest(observation: ExternalProviderObservation) -> str:
        return semantic_digest(asdict(observation))

    def verify_controls(
        self,
        store: EngineeringStore,
        lease: LeaseReceipt,
        envelope: WorkEnvelope,
        *,
        key_subjects: Mapping[str, str],
        now_ns: int,
    ) -> tuple[ProductionControlDecision, ProductionExternalEvidence]:
        if not isinstance(store, EngineeringStore):
            raise EngineeringError("production_external_store_required")
        if not isinstance(key_subjects, Mapping):
            raise EngineeringError("production_key_subjects_required")
        if set(key_subjects) != set(_REQUIRED_KEY_ROLES):
            raise EngineeringError("production_key_subject_roles")
        for role, identity in key_subjects.items():
            checked_id(role, "production_key_role")
            checked_id(identity, "production_key_subject")
        if len(set(key_subjects.values())) != len(key_subjects):
            raise EngineeringError("production_key_subject_collision")

        source = {
            "sourceCommit": envelope.source_commit,
            "sourceTree": envelope.source_tree,
            "envelopeId": envelope.envelope_id,
            "envelopeRevision": envelope.revision,
        }
        lease_context = {
            **source,
            "leaseId": lease.lease_id,
            "holder": lease.holder,
            "epoch": lease.epoch,
            "fencingToken": lease.fencing_token,
            "revision": lease.revision,
            "paths": lease.paths,
            "expiresUnixNs": lease.expires_unix_ns,
        }
        lease_client = self._client(self.providers.distributed_lease)
        frontier_observation = lease_client.invoke(
            "revocation-frontier",
            lease_context,
            source_commit=envelope.source_commit,
            source_tree=envelope.source_tree,
            now_ns=now_ns,
        )
        frontier = decode_external_receipt(
            frontier_observation, "distributed_revocation_frontier"
        )
        if not isinstance(frontier, DistributedRevocationFrontierReceipt):
            raise EngineeringError("distributed_revocation_frontier_required")
        fence_observation = lease_client.invoke(
            "distributed-fence",
            {
                **lease_context,
                "revocationFrontierReceiptDigest": semantic_digest(asdict(frontier)),
            },
            source_commit=envelope.source_commit,
            source_tree=envelope.source_tree,
            now_ns=now_ns,
        )
        fence = decode_external_receipt(fence_observation, "distributed_fence")
        if not isinstance(fence, DistributedFenceReceipt):
            raise EngineeringError("distributed_fence_receipt_required")
        admitted_fence_digest = admit_distributed_fence(
            lease,
            envelope,
            fence,
            frontier,
            self.trust_store,
            store=store,
            now_ns=now_ns,
        )

        anchor_context = {
            **source,
            "auditAnchor": store.audit_anchor(),
            "ownerSnapshotDigest": store_snapshot_digest(store),
        }
        audit_observation = self._client(self.providers.immutable_audit).invoke(
            "audit-anchor",
            anchor_context,
            source_commit=envelope.source_commit,
            source_tree=envelope.source_tree,
            now_ns=now_ns,
        )
        anchor = decode_external_receipt(audit_observation, "audit_anchor")
        if not isinstance(anchor, AuditAnchorAttestation):
            raise EngineeringError("external_audit_anchor_required")

        custody_receipts: list[KeyCustodyReceipt] = []
        custody_observations: list[ExternalProviderObservation] = []
        custody_client = self._client(self.providers.key_custody)
        for role in _REQUIRED_KEY_ROLES:
            observation = custody_client.invoke(
                "key-custody",
                {
                    **source,
                    "role": role,
                    "subjectSigningIdentity": key_subjects[role],
                },
                source_commit=envelope.source_commit,
                source_tree=envelope.source_tree,
                now_ns=now_ns,
            )
            receipt = decode_external_receipt(observation, "key_custody")
            if not isinstance(receipt, KeyCustodyReceipt):
                raise EngineeringError("key_custody_receipt_required")
            if role not in receipt.roles:
                raise EngineeringError("key_custody_role_mismatch")
            if receipt.subject_signing_identity != key_subjects[role]:
                raise EngineeringError("key_custody_subject_mismatch")
            custody_receipts.append(receipt)
            custody_observations.append(observation)

        decision = verify_production_controls(
            store,
            lease,
            envelope,
            fence,
            frontier,
            anchor,
            tuple(custody_receipts),
            self.trust_store,
            now_ns=now_ns,
        )
        if not (
            decision.distributed_fence_verified
            and decision.external_audit_anchor_verified
            and decision.external_key_custody_verified
        ):
            raise EngineeringError("production_external_controls_incomplete")
        observations = (
            frontier_observation,
            fence_observation,
            audit_observation,
            *custody_observations,
        )
        evidence = ProductionExternalEvidence(
            self.providers.configuration_digest,
            semantic_digest(asdict(frontier)),
            semantic_digest(asdict(fence)),
            admitted_fence_digest,
            semantic_digest(asdict(anchor)),
            tuple(semantic_digest(asdict(value)) for value in custody_receipts),
            decision.evidence_digest,
            tuple(self._observation_digest(value) for value in observations),
        )
        return decision, evidence

    def observe_completion(
        self,
        product: EngineeringControlProduct,
        claim_id: str,
        envelope: WorkEnvelope,
        *,
        expected_result_digest: str,
        now_ns: int,
    ) -> IndependentCompletionObservation:
        checked_id(claim_id, "claim_id")
        observation = self._client(self.providers.independent_completion).invoke(
            "completion-observation",
            {
                "claimId": claim_id,
                "envelopeId": envelope.envelope_id,
                "sourceCommit": envelope.source_commit,
                "sourceTree": envelope.source_tree,
                "expectedResultDigest": expected_result_digest,
            },
            source_commit=envelope.source_commit,
            source_tree=envelope.source_tree,
            now_ns=now_ns,
        )
        receipt = decode_external_receipt(observation, "completion")
        if not isinstance(receipt, CompletionReceipt):
            raise EngineeringError("completion_receipt_required")
        if receipt.result_digest != expected_result_digest:
            raise EngineeringError("completion_result_digest_mismatch")
        claim = product.observe_completion(
            claim_id,
            envelope,
            receipt,
            now_ns=now_ns,
        )
        return IndependentCompletionObservation(
            self._observation_digest(observation),
            semantic_digest(asdict(receipt)),
            claim,
        )

    def observe_terminal(
        self,
        product: EngineeringControlProduct,
        queue_generation_id: str,
        package_id: str,
        *,
        current_base_commit: str,
        current_base_tree: str,
        terminal_outcome: str,
        source_commit: str,
        source_tree: str,
        now_ns: int,
    ) -> IndependentTerminalObservation:
        if terminal_outcome not in {"merged", "failed"}:
            raise EngineeringError("integration_terminal_outcome")
        observation = self._client(self.providers.integration_terminal).invoke(
            "integration-terminal-observation",
            {
                "queueGenerationId": queue_generation_id,
                "packageId": package_id,
                "currentBaseCommit": current_base_commit,
                "currentBaseTree": current_base_tree,
                "terminalOutcome": terminal_outcome,
            },
            source_commit=source_commit,
            source_tree=source_tree,
            now_ns=now_ns,
        )
        receipt = decode_external_receipt(observation, "integration_terminal")
        if not isinstance(receipt, IntegrationTerminalReceipt):
            raise EngineeringError("integration_terminal_receipt_required")
        item = product.reconcile_integration(
            queue_generation_id,
            package_id,
            current_base_commit=current_base_commit,
            current_base_tree=current_base_tree,
            terminal_outcome=terminal_outcome,
            terminal_receipt=receipt,
            now_ns=now_ns,
        )
        return IndependentTerminalObservation(
            self._observation_digest(observation),
            semantic_digest(asdict(receipt)),
            item,
        )
