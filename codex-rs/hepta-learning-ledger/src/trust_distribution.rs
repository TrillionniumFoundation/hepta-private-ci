//! Root-authenticated production signer distribution activation.
//!
//! A product LedgerWriter never accepts a bare signer list as production trust.
//! The host pins a root public key and supplies a root-signed immutable signer
//! distribution. This module verifies that signature, scope and validity window,
//! enforces monotonic generation/authority rotation, and returns the only
//! ActivatedLearningTrustV1 value accepted by LedgerWriter.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;

use crate::LearningEvidenceTrustV1;
use crate::LearningEvidenceVerifierV1;
use crate::SignedEvidenceError;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningTrustRootV1 {
    pub root_id: StableId,
    pub scope_digest: Digest32,
    pub verifying_key: [u8; 32],
    pub valid_from: u64,
    pub expires_at: u64,
    pub revoked_at: Option<u64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningTrustDistributionV1 {
    pub distribution_id: StableId,
    pub generation: u64,
    pub effective_at: u64,
    pub trust: LearningEvidenceTrustV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedLearningTrustDistributionV1 {
    pub distribution: LearningTrustDistributionV1,
    pub root_id: StableId,
    pub issued_at: u64,
    pub expires_at: u64,
    pub signature: [u8; 64],
}

impl SignedLearningTrustDistributionV1 {
    pub fn signing_bytes(&self) -> Result<Vec<u8>, LearningTrustDistributionError> {
        distribution_signing_bytes(
            &self.root_id,
            &self.distribution,
            self.issued_at,
            self.expires_at,
        )
    }
}

#[derive(Clone, Debug)]
pub struct ActivatedLearningTrustV1 {
    root_id: StableId,
    root_digest: Digest32,
    root_key_digest: Digest32,
    distribution_id: StableId,
    generation: u64,
    effective_at: u64,
    distribution_digest: Digest32,
    verifier: LearningEvidenceVerifierV1,
}

impl ActivatedLearningTrustV1 {
    #[must_use]
    pub fn root_id(&self) -> &StableId {
        &self.root_id
    }

    #[must_use]
    pub const fn root_digest(&self) -> Digest32 {
        self.root_digest
    }

    /// Public key identity already authenticated at trust activation.
    #[must_use]
    pub const fn root_key_digest(&self) -> Digest32 {
        self.root_key_digest
    }

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
    root: &LearningTrustRootV1,
    signed: SignedLearningTrustDistributionV1,
    previous: Option<&ActivatedLearningTrustV1>,
    now: u64,
) -> Result<ActivatedLearningTrustV1, LearningTrustDistributionError> {
    let root_digest = validate_root(root, now)?;
    if signed.root_id != root.root_id {
        return Err(LearningTrustDistributionError::RootMismatch);
    }
    if signed.issued_at > now
        || signed.issued_at > signed.expires_at
        || signed.issued_at > signed.distribution.effective_at
        || now > signed.expires_at
        || signed.issued_at < root.valid_from
        || signed.expires_at > root.expires_at
    {
        return Err(LearningTrustDistributionError::DistributionWindow);
    }

    let distribution = &signed.distribution;
    if distribution.generation == 0
        || distribution.effective_at > now
        || distribution.trust.scope_digest != root.scope_digest
    {
        return Err(LearningTrustDistributionError::InvalidGeneration);
    }

    let mut verifier = LearningEvidenceVerifierV1::new(distribution.trust.clone())?;
    let payload = distribution_signing_bytes(
        &signed.root_id,
        distribution,
        signed.issued_at,
        signed.expires_at,
    )?;
    VerifyingKey::from_bytes(&root.verifying_key)
        .map_err(|_| LearningTrustDistributionError::InvalidRoot)?
        .verify_strict(&payload, &Signature::from_bytes(&signed.signature))
        .map_err(|_| LearningTrustDistributionError::InvalidSignature)?;

    if let Some(previous) = previous {
        let expected = previous
            .generation
            .checked_add(1)
            .ok_or(LearningTrustDistributionError::InvalidGeneration)?;
        if previous.root_digest != root_digest || previous.root_id != root.root_id {
            return Err(LearningTrustDistributionError::RootRotationRequiresCeremony);
        }
        if distribution.generation != expected
            || distribution.effective_at < previous.effective_at
            || verifier.authority_epoch() < previous.verifier.authority_epoch()
        {
            return Err(LearningTrustDistributionError::NonMonotonicRotation);
        }
    }

    // Activation is not a perpetual grant. Distribution expiry is already
    // bounded by root expiry above; retain the scheduled root revocation too.
    verifier.bind_distribution_window(
        distribution.effective_at,
        signed.expires_at,
        root.revoked_at,
    );
    let distribution_digest = digest_distribution(
        root_digest,
        &distribution.distribution_id,
        distribution.generation,
        distribution.effective_at,
        signed.issued_at,
        signed.expires_at,
        &verifier,
    );
    Ok(ActivatedLearningTrustV1 {
        root_id: root.root_id.clone(),
        root_digest,
        root_key_digest: Digest32::of_bytes(&root.verifying_key),
        distribution_id: distribution.distribution_id.clone(),
        generation: distribution.generation,
        effective_at: distribution.effective_at,
        distribution_digest,
        verifier,
    })
}

fn validate_root(
    root: &LearningTrustRootV1,
    now: u64,
) -> Result<Digest32, LearningTrustDistributionError> {
    if root.scope_digest.is_zero()
        || root.valid_from > root.expires_at
        || now < root.valid_from
        || now > root.expires_at
        || root.revoked_at.is_some_and(|at| now >= at)
    {
        return Err(LearningTrustDistributionError::InvalidRoot);
    }
    let key = VerifyingKey::from_bytes(&root.verifying_key)
        .map_err(|_| LearningTrustDistributionError::InvalidRoot)?;
    if key.is_weak() {
        return Err(LearningTrustDistributionError::InvalidRoot);
    }
    let mut bytes = b"hepta.learning-ledger.trust-root.v1".to_vec();
    push_id(&mut bytes, &root.root_id);
    bytes.extend_from_slice(root.scope_digest.as_array());
    bytes.extend_from_slice(&root.verifying_key);
    bytes.extend_from_slice(&root.valid_from.to_be_bytes());
    bytes.extend_from_slice(&root.expires_at.to_be_bytes());
    match root.revoked_at {
        Some(at) => {
            bytes.push(1);
            bytes.extend_from_slice(&at.to_be_bytes());
        }
        None => bytes.push(0),
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn distribution_signing_bytes(
    root_id: &StableId,
    distribution: &LearningTrustDistributionV1,
    issued_at: u64,
    expires_at: u64,
) -> Result<Vec<u8>, LearningTrustDistributionError> {
    let verifier = LearningEvidenceVerifierV1::new(distribution.trust.clone())?;
    let mut bytes = b"hepta.learning-ledger.trust-distribution-signature.v1".to_vec();
    push_id(&mut bytes, root_id);
    push_id(&mut bytes, &distribution.distribution_id);
    bytes.extend_from_slice(&distribution.generation.to_be_bytes());
    bytes.extend_from_slice(&distribution.effective_at.to_be_bytes());
    bytes.extend_from_slice(&issued_at.to_be_bytes());
    bytes.extend_from_slice(&expires_at.to_be_bytes());
    bytes.extend_from_slice(verifier.trust_digest().as_array());
    bytes.extend_from_slice(verifier.scope_digest().as_array());
    bytes.extend_from_slice(verifier.objective_digest().as_array());
    bytes.extend_from_slice(&verifier.authority_epoch().to_be_bytes());
    Ok(bytes)
}

fn digest_distribution(
    root_digest: Digest32,
    distribution_id: &StableId,
    generation: u64,
    effective_at: u64,
    issued_at: u64,
    expires_at: u64,
    verifier: &LearningEvidenceVerifierV1,
) -> Digest32 {
    let mut bytes = b"hepta.learning-ledger.trust-distribution.v2".to_vec();
    bytes.extend_from_slice(root_digest.as_array());
    push_id(&mut bytes, distribution_id);
    bytes.extend_from_slice(&generation.to_be_bytes());
    bytes.extend_from_slice(&effective_at.to_be_bytes());
    bytes.extend_from_slice(&issued_at.to_be_bytes());
    bytes.extend_from_slice(&expires_at.to_be_bytes());
    bytes.extend_from_slice(verifier.trust_digest().as_array());
    bytes.extend_from_slice(verifier.scope_digest().as_array());
    bytes.extend_from_slice(verifier.objective_digest().as_array());
    bytes.extend_from_slice(&verifier.authority_epoch().to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LearningTrustDistributionError {
    Evidence(SignedEvidenceError),
    InvalidRoot,
    RootMismatch,
    RootRotationRequiresCeremony,
    InvalidGeneration,
    NonMonotonicRotation,
    DistributionWindow,
    InvalidSignature,
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

#[cfg(test)]
#[path = "trust_distribution_live_tests.rs"]
mod live_tests;
