//! Durable publication contract for a generation-bound vector owner.
//!
//! This module does not pretend to be a durable store or a text encoder. It
//! defines the immutable object and compare-and-publish contract that a real
//! owner must persist atomically. A runtime can query only an active publication
//! for the exact tenant and at least the required withdrawal/revocation fronts.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;

use crate::GenerationBoundVectorOwnerV1;
use crate::RetrievalGeneratorBatchV1;
use crate::VectorIndexSnapshotV1;
use crate::VectorOwnerErrorV1;
use crate::VectorQueryV1;

pub const MAX_VECTOR_WITHDRAWALS: usize = 16_384;

const ENCODER_RELEASE_DOMAIN: &[u8] = b"hepta.memory-retrieval.encoder-release.v1";
const VECTOR_PUBLICATION_DOMAIN: &[u8] = b"hepta.memory-retrieval.vector-publication.v1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EncoderReleaseIdentityV1 {
    model_digest: Digest32,
    weights_digest: Digest32,
    runtime_digest: Digest32,
    preprocessor_digest: Digest32,
    dimensions: u32,
    release_digest: Digest32,
}

impl EncoderReleaseIdentityV1 {
    pub fn new(
        model_digest: Digest32,
        weights_digest: Digest32,
        runtime_digest: Digest32,
        preprocessor_digest: Digest32,
        dimensions: u32,
    ) -> Result<Self, VectorPublicationErrorV1> {
        let mut value = Self {
            model_digest,
            weights_digest,
            runtime_digest,
            preprocessor_digest,
            dimensions,
            release_digest: Digest32::ZERO,
        };
        value.release_digest = value.compute_digest();
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), VectorPublicationErrorV1> {
        for (name, digest) in [
            ("model", self.model_digest),
            ("weights", self.weights_digest),
            ("runtime", self.runtime_digest),
            ("preprocessor", self.preprocessor_digest),
        ] {
            if digest.is_zero() {
                return Err(VectorPublicationErrorV1::EmptyDigest(name));
            }
        }
        if self.dimensions == 0 {
            return Err(VectorPublicationErrorV1::InvalidDimensions);
        }
        if self.release_digest != self.compute_digest() {
            return Err(VectorPublicationErrorV1::DigestMismatch(
                "encoder release",
            ));
        }
        Ok(())
    }

    #[must_use]
    pub fn model_digest(&self) -> Digest32 {
        self.model_digest
    }

    #[must_use]
    pub fn preprocessor_digest(&self) -> Digest32 {
        self.preprocessor_digest
    }

    #[must_use]
    pub fn dimensions(&self) -> u32 {
        self.dimensions
    }

    #[must_use]
    pub fn release_digest(&self) -> Digest32 {
        self.release_digest
    }

    #[must_use]
    pub fn compute_digest(&self) -> Digest32 {
        let mut bytes = ENCODER_RELEASE_DOMAIN.to_vec();
        push_digest(&mut bytes, self.model_digest);
        push_digest(&mut bytes, self.weights_digest);
        push_digest(&mut bytes, self.runtime_digest);
        push_digest(&mut bytes, self.preprocessor_digest);
        bytes.extend_from_slice(&self.dimensions.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum VectorPublicationStateV1 {
    Active,
    Withdrawn,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VectorIndexPublicationV1 {
    tenant_digest: Digest32,
    sequence: u64,
    generation: u64,
    previous_publication_digest: Option<Digest32>,
    encoder: EncoderReleaseIdentityV1,
    snapshot: VectorIndexSnapshotV1,
    withdrawal_frontier: u64,
    revocation_frontier: u64,
    withdrawn_record_digests: Vec<Digest32>,
    state: VectorPublicationStateV1,
    publication_digest: Digest32,
}

impl VectorIndexPublicationV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        tenant_digest: Digest32,
        sequence: u64,
        generation: u64,
        previous_publication_digest: Option<Digest32>,
        encoder: EncoderReleaseIdentityV1,
        snapshot: VectorIndexSnapshotV1,
        withdrawal_frontier: u64,
        revocation_frontier: u64,
        mut withdrawn_record_digests: Vec<Digest32>,
        state: VectorPublicationStateV1,
    ) -> Result<Self, VectorPublicationErrorV1> {
        withdrawn_record_digests.sort();
        let mut value = Self {
            tenant_digest,
            sequence,
            generation,
            previous_publication_digest,
            encoder,
            snapshot,
            withdrawal_frontier,
            revocation_frontier,
            withdrawn_record_digests,
            state,
            publication_digest: Digest32::ZERO,
        };
        value.publication_digest = value.compute_digest();
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), VectorPublicationErrorV1> {
        if self.tenant_digest.is_zero() {
            return Err(VectorPublicationErrorV1::EmptyDigest("tenant"));
        }
        if self.sequence == 0 || self.generation == 0 {
            return Err(VectorPublicationErrorV1::InvalidSequence);
        }
        if (self.sequence == 1) != self.previous_publication_digest.is_none()
            || self
                .previous_publication_digest
                .is_some_and(Digest32::is_zero)
        {
            return Err(VectorPublicationErrorV1::InvalidPreviousPublication);
        }
        self.encoder.validate()?;
        self.snapshot
            .validate()
            .map_err(VectorPublicationErrorV1::Vector)?;
        if self.snapshot.model_digest != self.encoder.model_digest()
            || self.snapshot.encoder_preprocessor_digest != self.encoder.preprocessor_digest()
            || self.snapshot.dimensions != self.encoder.dimensions()
        {
            return Err(VectorPublicationErrorV1::EncoderSnapshotMismatch);
        }
        if self.withdrawn_record_digests.len() > MAX_VECTOR_WITHDRAWALS
            || self.withdrawn_record_digests.iter().any(|digest| digest.is_zero())
            || !strictly_sorted_unique(&self.withdrawn_record_digests)
        {
            return Err(VectorPublicationErrorV1::InvalidWithdrawalSet);
        }
        let withdrawn = self
            .withdrawn_record_digests
            .iter()
            .copied()
            .collect::<BTreeSet<_>>();
        if self
            .snapshot
            .records
            .iter()
            .any(|record| withdrawn.contains(&record.record.record_digest()))
        {
            return Err(VectorPublicationErrorV1::WithdrawnRecordPublished);
        }
        if self.publication_digest != self.compute_digest() {
            return Err(VectorPublicationErrorV1::DigestMismatch(
                "vector publication",
            ));
        }
        Ok(())
    }

    /// Validate an atomic successor. Index or encoder changes require a strict
    /// generation increment; policy-only frontier changes may remain within the
    /// same generation but still advance the durable sequence.
    pub fn validate_successor(
        &self,
        next: &Self,
    ) -> Result<(), VectorPublicationErrorV1> {
        self.validate()?;
        next.validate()?;
        if self.tenant_digest != next.tenant_digest
            || next.sequence != self.sequence.saturating_add(1)
            || next.previous_publication_digest != Some(self.publication_digest)
        {
            return Err(VectorPublicationErrorV1::InvalidSuccessor);
        }
        if next.generation < self.generation
            || next.withdrawal_frontier < self.withdrawal_frontier
            || next.revocation_frontier < self.revocation_frontier
        {
            return Err(VectorPublicationErrorV1::Rollback);
        }
        if self.state == VectorPublicationStateV1::Withdrawn
            && next.state == VectorPublicationStateV1::Active
        {
            return Err(VectorPublicationErrorV1::WithdrawnPublicationReactivated);
        }
        let object_changed = next.snapshot.index_digest != self.snapshot.index_digest
            || next.encoder.release_digest() != self.encoder.release_digest();
        if object_changed && next.generation <= self.generation {
            return Err(VectorPublicationErrorV1::GenerationNotAdvanced);
        }
        let old_withdrawals = self
            .withdrawn_record_digests
            .iter()
            .copied()
            .collect::<BTreeSet<_>>();
        let new_withdrawals = next
            .withdrawn_record_digests
            .iter()
            .copied()
            .collect::<BTreeSet<_>>();
        if !old_withdrawals.is_subset(&new_withdrawals) {
            return Err(VectorPublicationErrorV1::WithdrawalRollback);
        }
        Ok(())
    }

    #[must_use]
    pub fn tenant_digest(&self) -> Digest32 {
        self.tenant_digest
    }

    #[must_use]
    pub fn sequence(&self) -> u64 {
        self.sequence
    }

    #[must_use]
    pub fn generation(&self) -> u64 {
        self.generation
    }

    #[must_use]
    pub fn withdrawal_frontier(&self) -> u64 {
        self.withdrawal_frontier
    }

    #[must_use]
    pub fn revocation_frontier(&self) -> u64 {
        self.revocation_frontier
    }

    #[must_use]
    pub fn state(&self) -> VectorPublicationStateV1 {
        self.state
    }

    #[must_use]
    pub fn publication_digest(&self) -> Digest32 {
        self.publication_digest
    }

    #[must_use]
    pub fn snapshot(&self) -> &VectorIndexSnapshotV1 {
        &self.snapshot
    }

    #[must_use]
    pub fn compute_digest(&self) -> Digest32 {
        let mut bytes = VECTOR_PUBLICATION_DOMAIN.to_vec();
        push_digest(&mut bytes, self.tenant_digest);
        bytes.extend_from_slice(&self.sequence.to_be_bytes());
        bytes.extend_from_slice(&self.generation.to_be_bytes());
        push_optional_digest(&mut bytes, self.previous_publication_digest);
        push_digest(&mut bytes, self.encoder.release_digest());
        push_digest(&mut bytes, self.snapshot.index_digest);
        bytes.extend_from_slice(&self.withdrawal_frontier.to_be_bytes());
        bytes.extend_from_slice(&self.revocation_frontier.to_be_bytes());
        bytes.extend_from_slice(
            &u64::try_from(self.withdrawn_record_digests.len())
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
        );
        for digest in &self.withdrawn_record_digests {
            push_digest(&mut bytes, *digest);
        }
        bytes.push(match self.state {
            VectorPublicationStateV1::Active => 0,
            VectorPublicationStateV1::Withdrawn => 1,
        });
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PublishedVectorQueryV1 {
    pub tenant_digest: Digest32,
    pub minimum_withdrawal_frontier: u64,
    pub minimum_revocation_frontier: u64,
    pub query: VectorQueryV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PublishedVectorOwnerV1 {
    publication: VectorIndexPublicationV1,
    owner: GenerationBoundVectorOwnerV1,
}

impl PublishedVectorOwnerV1 {
    pub fn new(publication: VectorIndexPublicationV1) -> Result<Self, VectorPublicationErrorV1> {
        publication.validate()?;
        if publication.state != VectorPublicationStateV1::Active {
            return Err(VectorPublicationErrorV1::PublicationNotActive);
        }
        let owner = GenerationBoundVectorOwnerV1::new(publication.snapshot.clone())
            .map_err(VectorPublicationErrorV1::Vector)?;
        Ok(Self { publication, owner })
    }

    pub fn generate(
        &self,
        request: &PublishedVectorQueryV1,
    ) -> Result<RetrievalGeneratorBatchV1, VectorPublicationErrorV1> {
        if request.tenant_digest != self.publication.tenant_digest {
            return Err(VectorPublicationErrorV1::TenantMismatch);
        }
        if request.minimum_withdrawal_frontier > self.publication.withdrawal_frontier
            || request.minimum_revocation_frontier > self.publication.revocation_frontier
        {
            return Err(VectorPublicationErrorV1::FrontierTooOld);
        }
        self.owner
            .generate(&request.query)
            .map_err(VectorPublicationErrorV1::Vector)
    }

    #[must_use]
    pub fn publication(&self) -> &VectorIndexPublicationV1 {
        &self.publication
    }
}

/// A product implementation must map this contract to one durable writer and
/// use a real compare-and-swap transaction. An uncertain commit result must be
/// reconciled by loading the current publication; it must never be retried as a
/// blind second publish.
pub trait DurableVectorPublicationPortV1 {
    type Error: StdError + Send + Sync + 'static;

    fn load_current(
        &self,
        tenant_digest: Digest32,
    ) -> Result<Option<VectorIndexPublicationV1>, Self::Error>;

    fn compare_and_publish(
        &mut self,
        tenant_digest: Digest32,
        expected_current: Option<Digest32>,
        next: &VectorIndexPublicationV1,
    ) -> Result<(), Self::Error>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum VectorPublicationErrorV1 {
    EmptyDigest(&'static str),
    InvalidDimensions,
    InvalidSequence,
    InvalidPreviousPublication,
    InvalidWithdrawalSet,
    WithdrawnRecordPublished,
    EncoderSnapshotMismatch,
    InvalidSuccessor,
    Rollback,
    GenerationNotAdvanced,
    WithdrawalRollback,
    WithdrawnPublicationReactivated,
    PublicationNotActive,
    TenantMismatch,
    FrontierTooOld,
    DigestMismatch(&'static str),
    Vector(VectorOwnerErrorV1),
}

impl fmt::Display for VectorPublicationErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for VectorPublicationErrorV1 {}

fn strictly_sorted_unique(values: &[Digest32]) -> bool {
    values.windows(2).all(|window| window[0] < window[1])
}

fn push_digest(bytes: &mut Vec<u8>, digest: Digest32) {
    bytes.extend_from_slice(digest.as_array());
}

fn push_optional_digest(bytes: &mut Vec<u8>, digest: Option<Digest32>) {
    match digest {
        Some(digest) => {
            bytes.push(1);
            push_digest(bytes, digest);
        }
        None => bytes.push(0),
    }
}

#[cfg(test)]
#[path = "vector_publication_tests.rs"]
mod tests;
