//! Typed durable-owner capabilities and receipts.
//!
//! This module wraps the one existing [`LearningArtifactOwnerService`]. It does
//! not create a second registry, writer, journal or publication state machine.
//! Successful construction proves that the normal owner opened and validated
//! its trust, signed writer lease, writer fence and durable withdrawal floor.
//! All exported capabilities remain `DENY_ALL`: none grants selection,
//! activation, promotion or release authority.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::ArtifactOwnerHostError;
use crate::ArtifactOwnerVerifierV1;
use crate::ArtifactPublicationReceiptV1;
use crate::DatasetWithdrawalRegistry;
use crate::LearningArtifactOwnerService;
use crate::LearningArtifactOwnerServiceConfigV1;
use crate::LearningArtifactOwnerServiceError;
use crate::LearningArtifactPublishRequestV1;
use crate::SignedArtifactWriterLeaseV1;
use crate::SignedCurrentArtifactHeadV1;
use crate::VerifiedCurrentRegistryViewV1;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum DurablePublicationPhaseV1 {
    Validated,
    PayloadDurable,
    RegistryDurable,
    HeadDurable,
    RouteCommitted,
    Promoted,
}

impl DurablePublicationPhaseV1 {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Validated => "validated",
            Self::PayloadDurable => "payload_durable",
            Self::RegistryDurable => "registry_durable",
            Self::HeadDurable => "head_durable",
            Self::RouteCommitted => "route_committed",
            Self::Promoted => "promoted",
        }
    }

    #[must_use]
    pub const fn successor(self) -> Option<Self> {
        match self {
            Self::Validated => Some(Self::PayloadDurable),
            Self::PayloadDurable => Some(Self::RegistryDurable),
            Self::RegistryDurable => Some(Self::HeadDurable),
            Self::HeadDurable => Some(Self::RouteCommitted),
            Self::RouteCommitted => Some(Self::Promoted),
            Self::Promoted => None,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedWriterFenceV1 {
    lease_id: StableId,
    producer_id: StableId,
    registry_id: StableId,
    withdrawal_scope_digest: Digest32,
    lease_digest: Digest32,
    trust_digest: Digest32,
    authority_epoch: u64,
    lease_generation: u64,
    expires_at: u64,
    authority: AuthorityPosture,
}

impl VerifiedWriterFenceV1 {
    fn from_opened_service(
        lease: &SignedArtifactWriterLeaseV1,
        verifier: &ArtifactOwnerVerifierV1,
    ) -> Result<Self, DurableContractErrorV1> {
        if lease.authority_epoch == 0
            || lease.lease_generation == 0
            || lease.expires_at < lease.issued_at
            || lease.withdrawal_scope_digest.is_zero()
            || verifier.trust_digest().is_zero()
        {
            return Err(DurableContractErrorV1::WriterFenceMismatch);
        }
        let mut signed = lease.signing_bytes();
        signed.extend_from_slice(&lease.signature);
        let lease_digest = Digest32::of_bytes(&signed);
        if lease_digest.is_zero() {
            return Err(DurableContractErrorV1::WriterFenceMismatch);
        }
        Ok(Self {
            lease_id: lease.lease_id.clone(),
            producer_id: lease.producer_id.clone(),
            registry_id: lease.registry_id.clone(),
            withdrawal_scope_digest: lease.withdrawal_scope_digest,
            lease_digest,
            trust_digest: verifier.trust_digest(),
            authority_epoch: lease.authority_epoch,
            lease_generation: lease.lease_generation,
            expires_at: lease.expires_at,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    #[must_use]
    pub fn lease_id(&self) -> &StableId {
        &self.lease_id
    }

    #[must_use]
    pub fn producer_id(&self) -> &StableId {
        &self.producer_id
    }

    #[must_use]
    pub fn registry_id(&self) -> &StableId {
        &self.registry_id
    }

    #[must_use]
    pub const fn withdrawal_scope_digest(&self) -> Digest32 {
        self.withdrawal_scope_digest
    }

    #[must_use]
    pub const fn lease_digest(&self) -> Digest32 {
        self.lease_digest
    }

    #[must_use]
    pub const fn trust_digest(&self) -> Digest32 {
        self.trust_digest
    }

    #[must_use]
    pub const fn authority_epoch(&self) -> u64 {
        self.authority_epoch
    }

    #[must_use]
    pub const fn lease_generation(&self) -> u64 {
        self.lease_generation
    }

    #[must_use]
    pub const fn expires_at(&self) -> u64 {
        self.expires_at
    }

    #[must_use]
    pub const fn authority_posture(&self) -> AuthorityPosture {
        self.authority
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedWithdrawalFrontierV1 {
    scope_digest: Digest32,
    head_digest: Digest32,
    records: usize,
    storage_binding: Digest32,
    authority: AuthorityPosture,
}

impl VerifiedWithdrawalFrontierV1 {
    fn from_durable_service(
        registry: &DatasetWithdrawalRegistry,
        storage_binding: Digest32,
    ) -> Result<Self, DurableContractErrorV1> {
        let scope_digest = registry
            .scope_digest()
            .ok_or(DurableContractErrorV1::WithdrawalFrontierMismatch)?;
        if scope_digest.is_zero() || storage_binding.is_zero() {
            return Err(DurableContractErrorV1::WithdrawalFrontierMismatch);
        }
        Ok(Self {
            scope_digest,
            head_digest: registry.head_digest(),
            records: registry.snapshot().records().len(),
            storage_binding,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    #[must_use]
    pub const fn scope_digest(&self) -> Digest32 {
        self.scope_digest
    }

    #[must_use]
    pub const fn head_digest(&self) -> Digest32 {
        self.head_digest
    }

    #[must_use]
    pub const fn records(&self) -> usize {
        self.records
    }

    #[must_use]
    pub const fn storage_binding(&self) -> Digest32 {
        self.storage_binding
    }

    #[must_use]
    pub const fn authority_posture(&self) -> AuthorityPosture {
        self.authority
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MonotonicGenerationAnchorV1 {
    registry_id: StableId,
    minimum_generation: Generation,
    current_generation: Option<Generation>,
    current_head_digest: Option<Digest32>,
    genesis_predecessor_head_digest: Digest32,
    trust_digest: Digest32,
    minimum_authority_epoch: u64,
    current_is_exact: bool,
    authority: AuthorityPosture,
}

impl MonotonicGenerationAnchorV1 {
    fn from_validated_startup(
        registry_id: StableId,
        minimum_generation: Generation,
        genesis_predecessor_head_digest: Digest32,
        trust_digest: Digest32,
        minimum_authority_epoch: u64,
        required_current_head: Option<&SignedCurrentArtifactHeadV1>,
    ) -> Result<Self, DurableContractErrorV1> {
        if trust_digest.is_zero() || minimum_authority_epoch == 0 {
            return Err(DurableContractErrorV1::GenerationRollback);
        }
        let (current_generation, current_head_digest, current_is_exact) =
            required_current_head.map_or((None, None, true), |head| {
                (
                    Some(head.witness.generation),
                    Some(head.witness.head_digest),
                    false,
                )
            });
        if current_generation.is_some_and(|value| value < minimum_generation) {
            return Err(DurableContractErrorV1::GenerationRollback);
        }
        Ok(Self {
            registry_id,
            minimum_generation,
            current_generation,
            current_head_digest,
            genesis_predecessor_head_digest,
            trust_digest,
            minimum_authority_epoch,
            current_is_exact,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    fn observe_route(
        &mut self,
        route: &RouteCommitReceiptV1,
    ) -> Result<(), DurableContractErrorV1> {
        if route.registry_id != self.registry_id
            || route.trust_digest != self.trust_digest
            || route.generation < self.minimum_generation
            || route.authority_epoch < self.minimum_authority_epoch
        {
            return Err(DurableContractErrorV1::GenerationRollback);
        }
        match (self.current_generation, self.current_head_digest) {
            (Some(generation), Some(head_digest)) if route.generation == generation => {
                if route.head_digest != head_digest {
                    return Err(DurableContractErrorV1::GenerationRollback);
                }
            }
            (Some(generation), Some(head_digest)) => {
                if route.generation < generation
                    || (self.current_is_exact && route.predecessor_head_digest != head_digest)
                {
                    return Err(DurableContractErrorV1::GenerationRollback);
                }
            }
            (None, None) => {
                if route.predecessor_head_digest != self.genesis_predecessor_head_digest {
                    return Err(DurableContractErrorV1::GenerationRollback);
                }
            }
            (Some(_), None) | (None, Some(_)) => {
                return Err(DurableContractErrorV1::GenerationRollback);
            }
        }
        self.current_generation = Some(route.generation);
        self.current_head_digest = Some(route.head_digest);
        self.current_is_exact = true;
        Ok(())
    }

    #[must_use]
    pub fn registry_id(&self) -> &StableId {
        &self.registry_id
    }

    #[must_use]
    pub const fn minimum_generation(&self) -> Generation {
        self.minimum_generation
    }

    #[must_use]
    pub const fn current_generation(&self) -> Option<Generation> {
        self.current_generation
    }

    #[must_use]
    pub const fn current_head_digest(&self) -> Option<Digest32> {
        self.current_head_digest
    }

    #[must_use]
    pub const fn trust_digest(&self) -> Digest32 {
        self.trust_digest
    }

    #[must_use]
    pub const fn authority_posture(&self) -> AuthorityPosture {
        self.authority
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RouteCommitReceiptV1 {
    registry_id: StableId,
    generation: Generation,
    predecessor_head_digest: Digest32,
    head_digest: Digest32,
    witness_digest: Digest32,
    trust_digest: Digest32,
    authority_epoch: u64,
    route_digest: Digest32,
    authority: AuthorityPosture,
}

impl RouteCommitReceiptV1 {
    fn from_verified_current(
        current: &VerifiedCurrentRegistryViewV1,
        signed_head: &SignedCurrentArtifactHeadV1,
        publication: &ArtifactPublicationReceiptV1,
        expected_trust_digest: Digest32,
    ) -> Result<Self, DurableContractErrorV1> {
        let receipt = current.receipt();
        if receipt.binding != signed_head.binding
            || receipt.head_digest != signed_head.witness.head_digest
            || publication.registry_head_digest != signed_head.witness.head_digest
            || current.witness_digest() != publication.witness_digest
            || current.trust_digest() != expected_trust_digest
            || signed_head.witness.authority_epoch == 0
        {
            return Err(DurableContractErrorV1::RouteCommitMismatch);
        }
        let mut value = Self {
            registry_id: signed_head.witness.registry_id.clone(),
            generation: signed_head.witness.generation,
            predecessor_head_digest: signed_head.witness.predecessor_head_digest,
            head_digest: signed_head.witness.head_digest,
            witness_digest: publication.witness_digest,
            trust_digest: current.trust_digest(),
            authority_epoch: signed_head.witness.authority_epoch,
            route_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        value.route_digest = digest_route(&value);
        Ok(value)
    }

    #[must_use]
    pub fn registry_id(&self) -> &StableId {
        &self.registry_id
    }

    #[must_use]
    pub const fn generation(&self) -> Generation {
        self.generation
    }

    #[must_use]
    pub const fn predecessor_head_digest(&self) -> Digest32 {
        self.predecessor_head_digest
    }

    #[must_use]
    pub const fn head_digest(&self) -> Digest32 {
        self.head_digest
    }

    #[must_use]
    pub const fn witness_digest(&self) -> Digest32 {
        self.witness_digest
    }

    #[must_use]
    pub const fn trust_digest(&self) -> Digest32 {
        self.trust_digest
    }

    #[must_use]
    pub const fn authority_epoch(&self) -> u64 {
        self.authority_epoch
    }

    #[must_use]
    pub const fn route_digest(&self) -> Digest32 {
        self.route_digest
    }

    #[must_use]
    pub const fn authority_posture(&self) -> AuthorityPosture {
        self.authority
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableCommitReceiptV1 {
    operation_id: StableId,
    artifact_id: StableId,
    writer_fence_digest: Digest32,
    writer_lease_generation: u64,
    withdrawal_scope_digest: Digest32,
    admitted_withdrawal_head_digest: Digest32,
    observed_withdrawal_head_digest: Digest32,
    payload_digest: Digest32,
    payload_bytes: u64,
    registry_generation: Generation,
    registry_head_digest: Digest32,
    witness_digest: Digest32,
    route_digest: Digest32,
    state_digest: Digest32,
    acknowledged_at: u64,
    receipt_digest: Digest32,
    authority: AuthorityPosture,
}

impl DurableCommitReceiptV1 {
    fn from_acknowledged_publication(
        publication: &ArtifactPublicationReceiptV1,
        request: &LearningArtifactPublishRequestV1,
        writer_fence: &VerifiedWriterFenceV1,
        withdrawal_frontier: &VerifiedWithdrawalFrontierV1,
        route: &RouteCommitReceiptV1,
    ) -> Result<Self, DurableContractErrorV1> {
        let manifest = &request.admission.validated_manifest.manifest;
        if publication.operation_id != request.operation_id
            || publication.admission_digest != request.admission.admission_digest
            || publication.registry_head_digest != route.head_digest
            || publication.witness_digest != route.witness_digest
            || manifest.producer_id != *writer_fence.producer_id()
            || request.admission.withdrawal_scope_digest
                != writer_fence.withdrawal_scope_digest()
            || request.admission.withdrawal_scope_digest != withdrawal_frontier.scope_digest()
            || request.signed_current_head.binding != withdrawal_frontier.storage_binding()
            || request.signed_current_head.witness.registry_id != *writer_fence.registry_id()
            || manifest.bytes_digest.is_zero()
            || manifest.encoded_size_bytes == 0
            || publication.acknowledged_at > writer_fence.expires_at()
        {
            return Err(DurableContractErrorV1::CommitMismatch);
        }
        let mut receipt = Self {
            operation_id: publication.operation_id.clone(),
            artifact_id: manifest.artifact_id.clone(),
            writer_fence_digest: writer_fence.lease_digest(),
            writer_lease_generation: writer_fence.lease_generation(),
            withdrawal_scope_digest: request.admission.withdrawal_scope_digest,
            admitted_withdrawal_head_digest: request.admission.withdrawal_head_digest,
            observed_withdrawal_head_digest: withdrawal_frontier.head_digest(),
            payload_digest: manifest.bytes_digest,
            payload_bytes: manifest.encoded_size_bytes,
            registry_generation: route.generation,
            registry_head_digest: publication.registry_head_digest,
            witness_digest: publication.witness_digest,
            route_digest: route.route_digest,
            state_digest: publication.state_digest,
            acknowledged_at: publication.acknowledged_at,
            receipt_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        receipt.receipt_digest = digest_commit_receipt(&receipt);
        Ok(receipt)
    }

    #[must_use]
    pub fn operation_id(&self) -> &StableId {
        &self.operation_id
    }

    #[must_use]
    pub fn artifact_id(&self) -> &StableId {
        &self.artifact_id
    }

    #[must_use]
    pub const fn writer_fence_digest(&self) -> Digest32 {
        self.writer_fence_digest
    }

    #[must_use]
    pub const fn writer_lease_generation(&self) -> u64 {
        self.writer_lease_generation
    }

    #[must_use]
    pub const fn withdrawal_scope_digest(&self) -> Digest32 {
        self.withdrawal_scope_digest
    }

    #[must_use]
    pub const fn admitted_withdrawal_head_digest(&self) -> Digest32 {
        self.admitted_withdrawal_head_digest
    }

    #[must_use]
    pub const fn observed_withdrawal_head_digest(&self) -> Digest32 {
        self.observed_withdrawal_head_digest
    }

    #[must_use]
    pub const fn payload_digest(&self) -> Digest32 {
        self.payload_digest
    }

    #[must_use]
    pub const fn payload_bytes(&self) -> u64 {
        self.payload_bytes
    }

    #[must_use]
    pub const fn registry_generation(&self) -> Generation {
        self.registry_generation
    }

    #[must_use]
    pub const fn registry_head_digest(&self) -> Digest32 {
        self.registry_head_digest
    }

    #[must_use]
    pub const fn witness_digest(&self) -> Digest32 {
        self.witness_digest
    }

    #[must_use]
    pub const fn route_digest(&self) -> Digest32 {
        self.route_digest
    }

    #[must_use]
    pub const fn state_digest(&self) -> Digest32 {
        self.state_digest
    }

    #[must_use]
    pub const fn acknowledged_at(&self) -> u64 {
        self.acknowledged_at
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    #[must_use]
    pub const fn authority_posture(&self) -> AuthorityPosture {
        self.authority
    }

    #[must_use]
    pub fn response_json(&self) -> String {
        format!(
            concat!(
                "{{\"schema\":\"hepta.learning-artifactd.durable-commit.v1\",",
                "\"operationId\":\"{}\",\"artifactId\":\"{}\",",
                "\"writerFenceDigest\":\"{}\",\"writerLeaseGeneration\":{},",
                "\"withdrawalScopeDigest\":\"{}\",",
                "\"admittedWithdrawalHeadDigest\":\"{}\",",
                "\"observedWithdrawalHeadDigest\":\"{}\",",
                "\"payloadDigest\":\"{}\",\"payloadBytes\":{},",
                "\"registryGeneration\":{},\"registryHeadDigest\":\"{}\",",
                "\"witnessDigest\":\"{}\",\"routeDigest\":\"{}\",",
                "\"stateDigest\":\"{}\",\"acknowledgedAt\":{},",
                "\"receiptDigest\":\"{}\",\"authority\":\"deny_all\"}}"
            ),
            self.operation_id,
            self.artifact_id,
            self.writer_fence_digest,
            self.writer_lease_generation,
            self.withdrawal_scope_digest,
            self.admitted_withdrawal_head_digest,
            self.observed_withdrawal_head_digest,
            self.payload_digest,
            self.payload_bytes,
            self.registry_generation.get(),
            self.registry_head_digest,
            self.witness_digest,
            self.route_digest,
            self.state_digest,
            self.acknowledged_at,
            self.receipt_digest,
        )
    }
}

/// The typed durable composition over the one existing product owner service.
pub struct DurableLearningArtifactOwnerServiceV1 {
    inner: LearningArtifactOwnerService,
    writer_fence: VerifiedWriterFenceV1,
    withdrawal_frontier: VerifiedWithdrawalFrontierV1,
    generation_anchor: MonotonicGenerationAnchorV1,
    storage_binding: Digest32,
}

impl fmt::Debug for DurableLearningArtifactOwnerServiceV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("DurableLearningArtifactOwnerServiceV1")
            .field("inner", &self.inner)
            .field("writer_fence", &self.writer_fence)
            .field("withdrawal_frontier", &self.withdrawal_frontier)
            .field("generation_anchor", &self.generation_anchor)
            .finish()
    }
}

impl DurableLearningArtifactOwnerServiceV1 {
    pub fn open(
        config: LearningArtifactOwnerServiceConfigV1,
    ) -> Result<Self, DurableOwnerServiceErrorV1> {
        let verifier = ArtifactOwnerVerifierV1::new(config.trust.clone())?;
        let required_current_head = config.required_current_head.clone();
        let writer_fence =
            VerifiedWriterFenceV1::from_opened_service(&config.writer_lease, &verifier)?;
        let mut generation_anchor = MonotonicGenerationAnchorV1::from_validated_startup(
            config.trust.registry_id.clone(),
            config.trust.minimum_registry_generation,
            config.trust.genesis_predecessor_head_digest,
            verifier.trust_digest(),
            config.trust.minimum_authority_epoch,
            required_current_head.as_ref(),
        )?;
        let storage_binding = config.storage_binding;
        let inner = LearningArtifactOwnerService::open(config.clone())?;
        let current = match inner.current_registry_view(config.now) {
            Ok(view) => Some(view),
            Err(LearningArtifactOwnerServiceError::Host(
                ArtifactOwnerHostError::CurrentHeadContext,
            ))
            | Err(LearningArtifactOwnerServiceError::RecoveryRequired(_)) => None,
            Err(error) => return Err(error.into()),
        };
        if current.is_some() && required_current_head.is_none() {
            return Err(DurableContractErrorV1::RestartAnchorRequired.into());
        }
        if let Some(view) = current.as_ref() {
            if view.trust_digest() != verifier.trust_digest() {
                return Err(DurableContractErrorV1::GenerationRollback.into());
            }
            if let Some(required) = required_current_head.as_ref()
                && view.receipt().head_digest == required.witness.head_digest
            {
                generation_anchor.current_is_exact = true;
            }
        }
        let withdrawal_frontier = VerifiedWithdrawalFrontierV1::from_durable_service(
            inner.withdrawal_registry(),
            storage_binding,
        )?;
        Ok(Self {
            inner,
            writer_fence,
            withdrawal_frontier,
            generation_anchor,
            storage_binding,
        })
    }

    #[must_use]
    pub const fn service(&self) -> &LearningArtifactOwnerService {
        &self.inner
    }

    #[must_use]
    pub const fn writer_fence(&self) -> &VerifiedWriterFenceV1 {
        &self.writer_fence
    }

    #[must_use]
    pub const fn withdrawal_frontier(&self) -> &VerifiedWithdrawalFrontierV1 {
        &self.withdrawal_frontier
    }

    #[must_use]
    pub const fn generation_anchor(&self) -> &MonotonicGenerationAnchorV1 {
        &self.generation_anchor
    }

    pub fn current_registry_view(
        &self,
        now: u64,
    ) -> Result<VerifiedCurrentRegistryViewV1, DurableOwnerServiceErrorV1> {
        Ok(self.inner.current_registry_view(now)?)
    }

    pub fn install_withdrawal_frontier(
        &mut self,
        next: DatasetWithdrawalRegistry,
    ) -> Result<(), DurableOwnerServiceErrorV1> {
        self.inner.install_withdrawal_frontier(next)?;
        self.withdrawal_frontier = VerifiedWithdrawalFrontierV1::from_durable_service(
            self.inner.withdrawal_registry(),
            self.storage_binding,
        )?;
        Ok(())
    }

    pub fn begin_drain_durable(&mut self) -> Result<(), DurableOwnerServiceErrorV1> {
        Ok(self.inner.begin_drain_durable()?)
    }

    #[must_use]
    pub fn is_drained(&self) -> bool {
        self.inner.is_drained()
    }

    /// Publish through the existing owner state machine, then re-open the exact
    /// authenticated CURRENT view. The route receipt is therefore derived from
    /// durable state, not from the caller's requested head. Exact terminal
    /// retries, including post-restart retries, reconstruct the same route and
    /// durable commit receipt.
    pub fn publish_durable(
        &mut self,
        request: LearningArtifactPublishRequestV1,
    ) -> Result<DurableCommitReceiptV1, DurableOwnerServiceErrorV1> {
        let publication = self.inner.publish(request.clone())?;
        let current = self.inner.current_registry_view(request.now)?;
        let route = RouteCommitReceiptV1::from_verified_current(
            &current,
            &request.signed_current_head,
            &publication,
            self.writer_fence.trust_digest(),
        )?;
        self.generation_anchor.observe_route(&route)?;
        self.withdrawal_frontier = VerifiedWithdrawalFrontierV1::from_durable_service(
            self.inner.withdrawal_registry(),
            self.storage_binding,
        )?;
        Ok(DurableCommitReceiptV1::from_acknowledged_publication(
            &publication,
            &request,
            &self.writer_fence,
            &self.withdrawal_frontier,
            &route,
        )?)
    }
}

fn digest_route(receipt: &RouteCommitReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.learning-artifacts.route-commit.v1".to_vec();
    push_id(&mut bytes, &receipt.registry_id);
    bytes.extend_from_slice(&receipt.generation.get().to_be_bytes());
    bytes.extend_from_slice(receipt.predecessor_head_digest.as_array());
    bytes.extend_from_slice(receipt.head_digest.as_array());
    bytes.extend_from_slice(receipt.witness_digest.as_array());
    bytes.extend_from_slice(receipt.trust_digest.as_array());
    bytes.extend_from_slice(&receipt.authority_epoch.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn digest_commit_receipt(receipt: &DurableCommitReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.learning-artifacts.durable-commit-receipt.v1".to_vec();
    push_id(&mut bytes, &receipt.operation_id);
    push_id(&mut bytes, &receipt.artifact_id);
    bytes.extend_from_slice(receipt.writer_fence_digest.as_array());
    bytes.extend_from_slice(&receipt.writer_lease_generation.to_be_bytes());
    bytes.extend_from_slice(receipt.withdrawal_scope_digest.as_array());
    bytes.extend_from_slice(receipt.admitted_withdrawal_head_digest.as_array());
    bytes.extend_from_slice(receipt.observed_withdrawal_head_digest.as_array());
    bytes.extend_from_slice(receipt.payload_digest.as_array());
    bytes.extend_from_slice(&receipt.payload_bytes.to_be_bytes());
    bytes.extend_from_slice(&receipt.registry_generation.get().to_be_bytes());
    bytes.extend_from_slice(receipt.registry_head_digest.as_array());
    bytes.extend_from_slice(receipt.witness_digest.as_array());
    bytes.extend_from_slice(receipt.route_digest.as_array());
    bytes.extend_from_slice(receipt.state_digest.as_array());
    bytes.extend_from_slice(&receipt.acknowledged_at.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DurableContractErrorV1 {
    WriterFenceMismatch,
    WithdrawalFrontierMismatch,
    RestartAnchorRequired,
    GenerationRollback,
    RouteCommitMismatch,
    CommitMismatch,
}

impl fmt::Display for DurableContractErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for DurableContractErrorV1 {}

#[derive(Debug)]
pub enum DurableOwnerServiceErrorV1 {
    Host(ArtifactOwnerHostError),
    Service(LearningArtifactOwnerServiceError),
    Contract(DurableContractErrorV1),
}

impl fmt::Display for DurableOwnerServiceErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for DurableOwnerServiceErrorV1 {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Host(error) => Some(error),
            Self::Service(error) => Some(error),
            Self::Contract(error) => Some(error),
        }
    }
}

impl From<ArtifactOwnerHostError> for DurableOwnerServiceErrorV1 {
    fn from(value: ArtifactOwnerHostError) -> Self {
        Self::Host(value)
    }
}

impl From<LearningArtifactOwnerServiceError> for DurableOwnerServiceErrorV1 {
    fn from(value: LearningArtifactOwnerServiceError) -> Self {
        Self::Service(value)
    }
}

impl From<DurableContractErrorV1> for DurableOwnerServiceErrorV1 {
    fn from(value: DurableContractErrorV1) -> Self {
        Self::Contract(value)
    }
}

#[cfg(test)]
mod tests {
    use super::DurablePublicationPhaseV1;

    #[test]
    fn durable_publication_order_is_total_and_terminal() {
        let mut phase = DurablePublicationPhaseV1::Validated;
        for expected in [
            DurablePublicationPhaseV1::PayloadDurable,
            DurablePublicationPhaseV1::RegistryDurable,
            DurablePublicationPhaseV1::HeadDurable,
            DurablePublicationPhaseV1::RouteCommitted,
            DurablePublicationPhaseV1::Promoted,
        ] {
            phase = phase.successor().expect("next durable publication phase");
            assert_eq!(phase, expected);
        }
        assert_eq!(phase.successor(), None);
    }
}
