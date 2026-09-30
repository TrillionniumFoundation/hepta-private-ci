//! Typed publication authority and one durable commit receipt.
//!
//! These values prove only that the named artifact owner authenticated the
//! writer, generation, withdrawal frontier and route target for one local
//! publication. They deliberately carry DENY_ALL authority for selection,
//! activation, promotion and release.

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::ArtifactOwnerHostError;
use crate::ArtifactPublicationReceiptV1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ArtifactDurableCommitPhaseV1 {
    Authorized,
    PayloadDurable,
    RegistryDurable,
    CurrentHeadDurable,
    RouteCommitted,
    PublicationAcknowledged,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactPublicationCapabilityV1 {
    writer_lease_digest: Digest32,
    writer_lease_generation: u64,
    writer_authority_epoch: u64,
    producer_id: StableId,
    trust_digest: Digest32,
    registry_generation: Generation,
    expected_predecessor_head_digest: Digest32,
    target_head_digest: Digest32,
    withdrawal_scope_digest: Digest32,
    withdrawal_head_digest: Digest32,
    withdrawal_records: usize,
    capability_digest: Digest32,
}

impl ArtifactPublicationCapabilityV1 {
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn new(
        writer_lease_digest: Digest32,
        writer_lease_generation: u64,
        writer_authority_epoch: u64,
        producer_id: StableId,
        trust_digest: Digest32,
        registry_generation: Generation,
        expected_predecessor_head_digest: Digest32,
        target_head_digest: Digest32,
        withdrawal_scope_digest: Digest32,
        withdrawal_head_digest: Digest32,
        withdrawal_records: usize,
    ) -> Self {
        let mut bytes = b"hepta.learning-artifacts.publication-capability.v1".to_vec();
        bytes.extend_from_slice(writer_lease_digest.as_array());
        bytes.extend_from_slice(&writer_lease_generation.to_be_bytes());
        bytes.extend_from_slice(&writer_authority_epoch.to_be_bytes());
        push_id(&mut bytes, &producer_id);
        bytes.extend_from_slice(trust_digest.as_array());
        bytes.extend_from_slice(&registry_generation.get().to_be_bytes());
        bytes.extend_from_slice(expected_predecessor_head_digest.as_array());
        bytes.extend_from_slice(target_head_digest.as_array());
        bytes.extend_from_slice(withdrawal_scope_digest.as_array());
        bytes.extend_from_slice(withdrawal_head_digest.as_array());
        bytes.extend_from_slice(&(withdrawal_records as u64).to_be_bytes());
        let capability_digest = Digest32::of_bytes(&bytes);
        Self {
            writer_lease_digest,
            writer_lease_generation,
            writer_authority_epoch,
            producer_id,
            trust_digest,
            registry_generation,
            expected_predecessor_head_digest,
            target_head_digest,
            withdrawal_scope_digest,
            withdrawal_head_digest,
            withdrawal_records,
            capability_digest,
        }
    }

    #[must_use]
    pub const fn writer_lease_digest(&self) -> Digest32 {
        self.writer_lease_digest
    }

    #[must_use]
    pub const fn writer_lease_generation(&self) -> u64 {
        self.writer_lease_generation
    }

    #[must_use]
    pub const fn writer_authority_epoch(&self) -> u64 {
        self.writer_authority_epoch
    }

    #[must_use]
    pub fn producer_id(&self) -> &StableId {
        &self.producer_id
    }

    #[must_use]
    pub const fn trust_digest(&self) -> Digest32 {
        self.trust_digest
    }

    #[must_use]
    pub const fn registry_generation(&self) -> Generation {
        self.registry_generation
    }

    #[must_use]
    pub const fn expected_predecessor_head_digest(&self) -> Digest32 {
        self.expected_predecessor_head_digest
    }

    #[must_use]
    pub const fn target_head_digest(&self) -> Digest32 {
        self.target_head_digest
    }

    #[must_use]
    pub const fn withdrawal_scope_digest(&self) -> Digest32 {
        self.withdrawal_scope_digest
    }

    #[must_use]
    pub const fn withdrawal_head_digest(&self) -> Digest32 {
        self.withdrawal_head_digest
    }

    #[must_use]
    pub const fn withdrawal_records(&self) -> usize {
        self.withdrawal_records
    }

    #[must_use]
    pub const fn capability_digest(&self) -> Digest32 {
        self.capability_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableCommitReceiptV1 {
    publication: ArtifactPublicationReceiptV1,
    capability_digest: Digest32,
    writer_lease_digest: Digest32,
    writer_lease_generation: u64,
    registry_generation: Generation,
    withdrawal_head_digest: Digest32,
    route_head_digest: Digest32,
    phase: ArtifactDurableCommitPhaseV1,
    receipt_digest: Digest32,
    authority: AuthorityPosture,
}

impl DurableCommitReceiptV1 {
    pub(crate) fn from_publication(
        publication: ArtifactPublicationReceiptV1,
        capability: &ArtifactPublicationCapabilityV1,
    ) -> Result<Self, ArtifactOwnerHostError> {
        if publication.registry_head_digest != capability.target_head_digest
            || publication.admission_digest.is_zero()
            || publication.witness_digest.is_zero()
            || publication.state_digest.is_zero()
        {
            return Err(ArtifactOwnerHostError::CurrentHeadConflict);
        }
        let phase = ArtifactDurableCommitPhaseV1::PublicationAcknowledged;
        let mut bytes = b"hepta.learning-artifacts.durable-commit-receipt.v1".to_vec();
        push_id(&mut bytes, &publication.operation_id);
        bytes.extend_from_slice(publication.admission_digest.as_array());
        bytes.extend_from_slice(publication.registry_head_digest.as_array());
        bytes.extend_from_slice(publication.witness_digest.as_array());
        bytes.extend_from_slice(publication.state_digest.as_array());
        bytes.extend_from_slice(&publication.acknowledged_at.to_be_bytes());
        bytes.extend_from_slice(capability.capability_digest.as_array());
        bytes.extend_from_slice(capability.writer_lease_digest.as_array());
        bytes.extend_from_slice(&capability.writer_lease_generation.to_be_bytes());
        bytes.extend_from_slice(&capability.registry_generation.get().to_be_bytes());
        bytes.extend_from_slice(capability.withdrawal_head_digest.as_array());
        bytes.extend_from_slice(capability.target_head_digest.as_array());
        bytes.push(5);
        let receipt_digest = Digest32::of_bytes(&bytes);
        Ok(Self {
            publication,
            capability_digest: capability.capability_digest,
            writer_lease_digest: capability.writer_lease_digest,
            writer_lease_generation: capability.writer_lease_generation,
            registry_generation: capability.registry_generation,
            withdrawal_head_digest: capability.withdrawal_head_digest,
            route_head_digest: capability.target_head_digest,
            phase,
            receipt_digest,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    #[must_use]
    pub const fn publication(&self) -> &ArtifactPublicationReceiptV1 {
        &self.publication
    }

    #[must_use]
    pub fn into_publication(self) -> ArtifactPublicationReceiptV1 {
        self.publication
    }

    #[must_use]
    pub const fn capability_digest(&self) -> Digest32 {
        self.capability_digest
    }

    #[must_use]
    pub const fn writer_lease_digest(&self) -> Digest32 {
        self.writer_lease_digest
    }

    #[must_use]
    pub const fn writer_lease_generation(&self) -> u64 {
        self.writer_lease_generation
    }

    #[must_use]
    pub const fn registry_generation(&self) -> Generation {
        self.registry_generation
    }

    #[must_use]
    pub const fn withdrawal_head_digest(&self) -> Digest32 {
        self.withdrawal_head_digest
    }

    #[must_use]
    pub const fn route_head_digest(&self) -> Digest32 {
        self.route_head_digest
    }

    #[must_use]
    pub const fn phase(&self) -> ArtifactDurableCommitPhaseV1 {
        self.phase
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    bytes.extend_from_slice(&(value.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_str().as_bytes());
}
