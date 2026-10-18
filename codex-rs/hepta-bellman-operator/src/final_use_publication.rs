//! Borrowed candidate facts for the existing artifact owner's publication path.
//! A view exposes immutable data and cannot issue a manifest, selector proof,
//! owner currentness witness or publication authorization.

use super::FinalUseTabularCandidateV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

/// Immutable data needed to bind an externally admitted manifest to its bytes.
/// The artifact owner remains responsible for authorization and currentness.
#[derive(Clone, Copy, Debug)]
pub struct TabularCandidatePublicationViewV1<'a> {
    candidate: &'a FinalUseTabularCandidateV1,
}

impl FinalUseTabularCandidateV1 {
    #[must_use]
    pub const fn publication_view(&self) -> TabularCandidatePublicationViewV1<'_> {
        TabularCandidatePublicationViewV1 { candidate: self }
    }
}

impl<'a> TabularCandidatePublicationViewV1<'a> {
    #[must_use]
    pub fn payload(&self) -> &'a [u8] {
        self.candidate.payload.as_ref()
    }

    #[must_use]
    pub const fn artifact_id(&self) -> &'a StableId {
        &self.candidate.artifact.artifact_id
    }

    #[must_use]
    pub const fn producer_id(&self) -> &'a StableId {
        &self.candidate.artifact.producer_id
    }

    #[must_use]
    pub const fn generation(&self) -> Generation {
        self.candidate.artifact.generation
    }

    #[must_use]
    pub const fn objective_digest(&self) -> Digest32 {
        self.candidate.artifact.objective_digest
    }

    #[must_use]
    pub const fn dataset_digest(&self) -> Digest32 {
        self.candidate.artifact.dataset_digest
    }

    #[must_use]
    pub const fn artifact_digest(&self) -> Digest32 {
        self.candidate.artifact.artifact_digest
    }

    #[must_use]
    pub fn payload_digest(&self) -> Digest32 {
        self.candidate.payload_digest()
    }

    #[must_use]
    pub const fn training_profile_digest(&self) -> Digest32 {
        self.candidate.artifact.training_profile_digest
    }

    #[must_use]
    pub const fn runtime_profile_digest(&self) -> Digest32 {
        self.candidate.runtime_profile_digest
    }

    #[must_use]
    pub const fn trust_digest(&self) -> Digest32 {
        self.candidate.trust_digest
    }

    #[must_use]
    pub const fn ledger_head_digest(&self) -> Digest32 {
        self.candidate.ledger_head_digest
    }

    #[must_use]
    pub const fn authority_epoch(&self) -> u64 {
        self.candidate.authority_epoch
    }

    #[must_use]
    pub const fn stop_epoch(&self) -> u64 {
        self.candidate.stop_epoch
    }

    #[must_use]
    pub const fn published_at_unix_micros(&self) -> u64 {
        self.candidate.published_at_unix_micros
    }
}
