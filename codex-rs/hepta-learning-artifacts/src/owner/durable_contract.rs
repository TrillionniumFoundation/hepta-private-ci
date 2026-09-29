//! Typed durable-owner capabilities and receipts.
//!
//! These values make already-verified host facts explicit without granting
//! selection, activation, promotion or release authority. Constructors remain
//! crate-private so a caller cannot fabricate a writer fence, withdrawal
//! frontier, generation anchor or route commit from untrusted fields.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::ArtifactOwnerHostError;
use crate::ArtifactPublicationReceiptV1;
use crate::ArtifactPublicationTransactionV1;
use crate::DatasetWithdrawalRegistry;
use crate::LearningArtifactOwnerHost;
use crate::RegistryHeadWitnessReceipt;
use crate::SignedArtifactWriterLeaseV1;
use crate::SignedCurrentArtifactHeadV1;
use crate::VerifiedCurrentArtifactHeadV1;

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
    pub(crate) fn from_validated_host(
        host: &LearningArtifactOwnerHost,
        lease: &SignedArtifactWriterLeaseV1,
    ) -> Result<Self, DurableContractErrorV1> {
        let lease_digest = host.writer_lease_digest();
        if lease_digest.is_zero()
            || host.trust_digest().is_zero()
            || lease.lease_generation == 0
            || lease.authority_epoch == 0
            || lease.expires_at < lease.issued_at
            || host.producer_id() != &lease.producer_id
        {
            return Err(DurableContractErrorV1::WriterFenceMismatch);
        }
        let mut bytes = lease.signing_bytes();
        bytes.extend_from_slice(&lease.signature);
        if Digest32::of_bytes(&bytes) != lease_digest {
            return Err(DurableContractErrorV1::WriterFenceMismatch);
        }
        Ok(Self {
            lease_id: lease.lease_id.clone(),
            producer_id: lease.producer_id.clone(),
            registry_id: lease.registry_id.clone(),
            withdrawal_scope_digest: lease.withdrawal_scope_digest,
            lease_digest,
            trust_digest: host.trust_digest(),
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
    pub(crate) fn from_durable_registry(
        registry: &DatasetWithdrawalRegistry,
        storage_binding: Digest32,
    ) -> Result<Self, DurableContractErrorV1> {
        let scope_digest = registry
            .scope_digest()
            .ok_or(DurableContractErrorV1::WithdrawalFrontierMismatch)?;
        let snapshot = registry.snapshot();
        if scope_digest.is_zero() || storage_binding.is_zero() {
            return Err(DurableContractErrorV1::WithdrawalFrontierMismatch);
        }
        Ok(Self {
            scope_digest,
            head_digest: registry.head_digest(),
            records: snapshot.records().len(),
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
    generation: Generation,
    head_digest: Digest32,
    trust_digest: Digest32,
    authority_epoch: u64,
    authority: AuthorityPosture,
}

impl MonotonicGenerationAnchorV1 {
    pub(crate) fn from_verified_current(
        registry_id: StableId,
        minimum_generation: Generation,
        genesis_head_digest: Digest32,
        trust_digest: Digest32,
        current: Option<&VerifiedCurrentArtifactHeadV1>,
        minimum_authority_epoch: u64,
    ) -> Result<Self, DurableContractErrorV1> {
        if trust_digest.is_zero() || minimum_authority_epoch == 0 {
            return Err(DurableContractErrorV1::GenerationRollback);
        }
        let (generation, head_digest, authority_epoch) = current.map_or(
            (minimum_generation, genesis_head_digest, minimum_authority_epoch),
            |verified| {
                (
                    verified.signed.witness.generation,
                    verified.signed.witness.head_digest,
                    verified.signed.witness.authority_epoch,
                )
            },
        );
        if generation < minimum_generation || authority_epoch < minimum_authority_epoch {
            return Err(DurableContractErrorV1::GenerationRollback);
        }
        Ok(Self {
            registry_id,
            generation,
            head_digest,
            trust_digest,
            authority_epoch,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    pub(crate) fn observe_committed_head(
        &mut self,
        signed: &SignedCurrentArtifactHeadV1,
        trust_digest: Digest32,
    ) -> Result<(), DurableContractErrorV1> {
        if trust_digest != self.trust_digest
            || signed.witness.registry_id != self.registry_id
            || signed.witness.generation < self.generation
            || signed.witness.authority_epoch < self.authority_epoch
            || (signed.witness.generation == self.generation
                && signed.witness.head_digest != self.head_digest)
        {
            return Err(DurableContractErrorV1::GenerationRollback);
        }
        self.generation = signed.witness.generation;
        self.head_digest = signed.witness.head_digest;
        self.authority_epoch = signed.witness.authority_epoch;
        Ok(())
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
    pub const fn head_digest(&self) -> Digest32 {
        self.head_digest
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
    pub const fn authority_posture(&self) -> AuthorityPosture {
        self.authority
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableHeadReceiptV1 {
    witness_receipt: RegistryHeadWitnessReceipt,
    generation: Generation,
    head_digest: Digest32,
    predecessor_head_digest: Digest32,
    authority_epoch: u64,
    authority: AuthorityPosture,
}

impl DurableHeadReceiptV1 {
    #[must_use]
    pub const fn witness_receipt(&self) -> RegistryHeadWitnessReceipt {
        self.witness_receipt
    }

    #[must_use]
    pub const fn generation(&self) -> Generation {
        self.generation
    }

    #[must_use]
    pub const fn head_digest(&self) -> Digest32 {
        self.head_digest
    }

    #[must_use]
    pub const fn predecessor_head_digest(&self) -> Digest32 {
        self.predecessor_head_digest
    }

    #[must_use]
    pub const fn authority_epoch(&self) -> u64 {
        self.authority_epoch
    }

    #[must_use]
    pub const fn authority_posture(&self) -> AuthorityPosture {
        self.authority
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RouteCommitReceiptV1 {
    generation: Generation,
    head_digest: Digest32,
    witness_digest: Digest32,
    trust_digest: Digest32,
    route_digest: Digest32,
    authority: AuthorityPosture,
}

impl RouteCommitReceiptV1 {
    #[must_use]
    pub const fn generation(&self) -> Generation {
        self.generation
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
    pub const fn route_digest(&self) -> Digest32 {
        self.route_digest
    }

    #[must_use]
    pub const fn authority_posture(&self) -> AuthorityPosture {
        self.authority
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HeadAndRouteCommitReceiptV1 {
    pub head: DurableHeadReceiptV1,
    pub route: RouteCommitReceiptV1,
}

impl LearningArtifactOwnerHost {
    /// Persist the signed head, rediscover the canonical monotonic chain and
    /// return separate typed receipts for head durability and route commitment.
    /// The existing publication transaction remains the sole state machine.
    pub(crate) fn ensure_head_and_route_durable(
        &self,
        transaction: &mut ArtifactPublicationTransactionV1,
        signed: &SignedCurrentArtifactHeadV1,
        withdrawal_registry: &DatasetWithdrawalRegistry,
        now: u64,
    ) -> Result<HeadAndRouteCommitReceiptV1, ArtifactOwnerHostError> {
        let witness_receipt =
            self.ensure_witness_durable(transaction, signed, withdrawal_registry, now)?;
        let verified = self
            .discover_current_head(now)?
            .ok_or(ArtifactOwnerHostError::CurrentHeadConflict)?;
        if verified.signed != *signed || verified.witness_digest != witness_receipt.witness_digest {
            return Err(ArtifactOwnerHostError::CurrentHeadConflict);
        }
        let head = DurableHeadReceiptV1 {
            witness_receipt,
            generation: signed.witness.generation,
            head_digest: signed.witness.head_digest,
            predecessor_head_digest: signed.witness.predecessor_head_digest,
            authority_epoch: signed.witness.authority_epoch,
            authority: AuthorityPosture::DENY_ALL,
        };
        let route_digest = digest_route(&verified);
        let route = RouteCommitReceiptV1 {
            generation: verified.signed.witness.generation,
            head_digest: verified.signed.witness.head_digest,
            witness_digest: verified.witness_digest,
            trust_digest: verified.trust_digest,
            route_digest,
            authority: AuthorityPosture::DENY_ALL,
        };
        Ok(HeadAndRouteCommitReceiptV1 { head, route })
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

pub(crate) struct DurableCommitInputsV1<'a> {
    pub artifact_id: &'a StableId,
    pub producer_id: &'a StableId,
    pub admission_digest: Digest32,
    pub admitted_withdrawal_scope_digest: Digest32,
    pub admitted_withdrawal_head_digest: Digest32,
    pub payload_digest: Digest32,
    pub payload_bytes: u64,
    pub signed_head: &'a SignedCurrentArtifactHeadV1,
}

impl DurableCommitReceiptV1 {
    pub(crate) fn from_acknowledged_publication(
        publication: &ArtifactPublicationReceiptV1,
        inputs: DurableCommitInputsV1<'_>,
        writer_fence: &VerifiedWriterFenceV1,
        withdrawal_frontier: &VerifiedWithdrawalFrontierV1,
        anchor: &MonotonicGenerationAnchorV1,
        route: &RouteCommitReceiptV1,
    ) -> Result<Self, DurableContractErrorV1> {
        if publication.operation_id.as_str().is_empty()
            || publication.admission_digest != inputs.admission_digest
            || publication.registry_head_digest != inputs.signed_head.witness.head_digest
            || publication.witness_digest != route.witness_digest
            || inputs.producer_id != writer_fence.producer_id()
            || inputs.admitted_withdrawal_scope_digest != writer_fence.withdrawal_scope_digest()
            || inputs.admitted_withdrawal_scope_digest != withdrawal_frontier.scope_digest()
            || inputs.signed_head.binding != withdrawal_frontier.storage_binding()
            || inputs.signed_head.witness.registry_id != *writer_fence.registry_id()
            || inputs.signed_head.witness.generation != anchor.generation()
            || inputs.signed_head.witness.head_digest != anchor.head_digest()
            || route.generation != anchor.generation()
            || route.head_digest != anchor.head_digest()
            || route.trust_digest != writer_fence.trust_digest()
            || inputs.payload_digest.is_zero()
            || inputs.payload_bytes == 0
            || publication.acknowledged_at > writer_fence.expires_at()
        {
            return Err(DurableContractErrorV1::CommitMismatch);
        }

        let mut receipt = Self {
            operation_id: publication.operation_id.clone(),
            artifact_id: inputs.artifact_id.clone(),
            writer_fence_digest: writer_fence.lease_digest(),
            writer_lease_generation: writer_fence.lease_generation(),
            withdrawal_scope_digest: inputs.admitted_withdrawal_scope_digest,
            admitted_withdrawal_head_digest: inputs.admitted_withdrawal_head_digest,
            observed_withdrawal_head_digest: withdrawal_frontier.head_digest(),
            payload_digest: inputs.payload_digest,
            payload_bytes: inputs.payload_bytes,
            registry_generation: inputs.signed_head.witness.generation,
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
}

fn digest_route(verified: &VerifiedCurrentArtifactHeadV1) -> Digest32 {
    let mut bytes = b"hepta.learning-artifacts.route-commit.v1".to_vec();
    bytes.extend_from_slice(&verified.signed.witness.generation.get().to_be_bytes());
    bytes.extend_from_slice(verified.signed.witness.head_digest.as_array());
    bytes.extend_from_slice(verified.witness_digest.as_array());
    bytes.extend_from_slice(verified.trust_digest.as_array());
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
    GenerationRollback,
    CommitMismatch,
}

impl fmt::Display for DurableContractErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for DurableContractErrorV1 {}

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
