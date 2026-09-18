//! Versioned production trust-root and signer distribution activation.
//!
//! The host still owns the authority source and distribution transport. This
//! module turns one immutable host distribution into a content-addressed,
//! generation-bound verifier snapshot and enforces monotonic rotation before a
//! production LedgerWriter can consume it.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::LearningEvidenceTrustV1;
use crate::LearningEvidenceVerifierV1;
use crate::SignedEvidenceError;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningTrustDistributionV1 {
    pub distribution_id: StableId,
    pub generation: u64,
    pub effective_at: u64,
    pub trust: LearningEvidenceTrustV1,
}

#[derive(Clone, Debug)]
pub struct ActivatedLearningTrustV1 {
    distribution_id: StableId,
    generation: u64,
    effective_at: u64,
    distribution_digest: Digest32,
    verifier: LearningEvidenceVerifierV1,
}

impl ActivatedLearningTrustV1 {
    #[must_use]
    pub fn distribution_id(&self) -> &StableId {
        &self.distribution_id
    }

    #[must_use]
    pub const fn generation(&self) -> u64 {
        self.generation
    }

    #[must_use]
    pub const fn effective_at(&self) -> u64 {
        self.effective_at
    }

    #[must_use]
    pub const fn distribution_digest(&self) -> Digest32 {
        self.distribution_digest
    }

    #[must_use]
    pub fn verifier(&self) -> &LearningEvidenceVerifierV1 {
        &self.verifier
    }
}

pub fn activate_learning_trust(
    distribution: LearningTrustDistributionV1,
    previous: Option<&ActivatedLearningTrustV1>,
    now: u64,
) -> Result<ActivatedLearningTrustV1, LearningTrustDistributionError> {
    if distribution.generation == 0 || distribution.effective_at > now {
        return Err(LearningTrustDistributionError::InvalidGeneration);
    }
    if let Some(previous) = previous {
        let expected = previous
            .generation
            .checked_add(1)
            .ok_or(LearningTrustDistributionError::InvalidGeneration)?;
        if distribution.generation != expected
            || distribution.effective_at < previous.effective_at
            || distribution.trust.authority_epoch < previous.verifier.authority_epoch()
        {
            return Err(LearningTrustDistributionError::NonMonotonicRotation);
        }
    }
    let distribution_id = distribution.distribution_id;
    let generation = distribution.generation;
    let effective_at = distribution.effective_at;
    let verifier = LearningEvidenceVerifierV1::new(distribution.trust)?;
    let distribution_digest = digest_distribution(
        &distribution_id,
        generation,
        effective_at,
        &verifier,
    );
    Ok(ActivatedLearningTrustV1 {
        distribution_id,
        generation,
        effective_at,
        distribution_digest,
        verifier,
    })
}

fn digest_distribution(
    distribution_id: &StableId,
    generation: u64,
    effective_at: u64,
    verifier: &LearningEvidenceVerifierV1,
) -> Digest32 {
    let mut bytes = b"hepta.learning-ledger.trust-distribution.v1".to_vec();
    let raw = distribution_id.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
    bytes.extend_from_slice(raw);
    bytes.extend_from_slice(&generation.to_be_bytes());
    bytes.extend_from_slice(&effective_at.to_be_bytes());
    bytes.extend_from_slice(verifier.trust_digest().as_array());
    bytes.extend_from_slice(verifier.scope_digest().as_array());
    bytes.extend_from_slice(verifier.objective_digest().as_array());
    bytes.extend_from_slice(&verifier.authority_epoch().to_be_bytes());
    Digest32::of_bytes(&bytes)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LearningTrustDistributionError {
    Evidence(SignedEvidenceError),
    InvalidGeneration,
    NonMonotonicRotation,
}

impl fmt::Display for LearningTrustDistributionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for LearningTrustDistributionError {}

impl From<SignedEvidenceError> for LearningTrustDistributionError {
    fn from(value: SignedEvidenceError) -> Self {
        Self::Evidence(value)
    }
}

#[cfg(test)]
#[path = "trust_distribution_tests.rs"]
mod tests;
