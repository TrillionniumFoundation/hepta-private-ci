//! Closed signature profiles for learning, installation and artifact ownership.
//! Every verifier pins one profile from host trust; signatures cannot select a
//! weaker algorithm. The legacy byte representation is preserved explicitly.

use std::ops::Deref;
use std::ops::DerefMut;

use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;

use crate::pq_auth::PqNativeError;
use crate::pq_auth::PqNativeVerifier;
use crate::pq_auth::ml_dsa_65_key_id_from_spki;

pub use crate::FinalUseAuthenticationProfile as LearningAuthenticationProfile;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "profile", content = "bytes", rename_all = "snake_case")]
pub enum LearningVerificationKey {
    ClassicalV1([u8; 32]),
    MlDsa65V2(Vec<u8>),
}

impl LearningVerificationKey {
    pub const fn profile(&self) -> LearningAuthenticationProfile {
        match self {
            Self::ClassicalV1(_) => LearningAuthenticationProfile::ClassicalV1,
            Self::MlDsa65V2(_) => LearningAuthenticationProfile::MlDsa65V2,
        }
    }

    pub fn validate(&self) -> Result<(), PqNativeError> {
        match self {
            Self::ClassicalV1(bytes) => {
                let key =
                    VerifyingKey::from_bytes(bytes).map_err(|_| PqNativeError::KeyAlgorithm)?;
                if key.is_weak() {
                    return Err(PqNativeError::KeyAlgorithm);
                }
                Ok(())
            }
            Self::MlDsa65V2(bytes) => {
                PqNativeVerifier::from_pinned_spki(bytes, ml_dsa_65_key_id_from_spki(bytes)?)?;
                Ok(())
            }
        }
    }

    pub fn verify(
        &self,
        message: &[u8],
        signature: &LearningSignature,
    ) -> Result<(), PqNativeError> {
        match (self, signature) {
            (Self::ClassicalV1(key), LearningSignature::ClassicalV1(bytes)) => {
                let key = VerifyingKey::from_bytes(key).map_err(|_| PqNativeError::KeyAlgorithm)?;
                if key.is_weak() {
                    return Err(PqNativeError::KeyAlgorithm);
                }
                let signature =
                    Signature::from_slice(bytes).map_err(|_| PqNativeError::SignatureRejected)?;
                key.verify_strict(message, &signature)
                    .map_err(|_| PqNativeError::SignatureRejected)
            }
            (Self::MlDsa65V2(key), LearningSignature::MlDsa65V2(bytes)) => {
                PqNativeVerifier::from_pinned_spki(key, ml_dsa_65_key_id_from_spki(key)?)?
                    .verify_exact_message(message, bytes)?;
                Ok(())
            }
            (Self::ClassicalV1(_), LearningSignature::MlDsa65V2(_))
            | (Self::MlDsa65V2(_), LearningSignature::ClassicalV1(_)) => {
                Err(PqNativeError::SignatureRejected)
            }
        }
    }
}

impl From<[u8; 32]> for LearningVerificationKey {
    fn from(value: [u8; 32]) -> Self {
        Self::ClassicalV1(value)
    }
}

impl Deref for LearningVerificationKey {
    type Target = [u8];
    fn deref(&self) -> &Self::Target {
        match self {
            Self::ClassicalV1(bytes) => bytes,
            Self::MlDsa65V2(bytes) => bytes,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "profile", content = "bytes", rename_all = "snake_case")]
pub enum LearningSignature {
    ClassicalV1(Vec<u8>),
    MlDsa65V2(Vec<u8>),
}

impl LearningSignature {
    pub const fn profile(&self) -> LearningAuthenticationProfile {
        match self {
            Self::ClassicalV1(_) => LearningAuthenticationProfile::ClassicalV1,
            Self::MlDsa65V2(_) => LearningAuthenticationProfile::MlDsa65V2,
        }
    }
}

impl From<[u8; 64]> for LearningSignature {
    fn from(value: [u8; 64]) -> Self {
        Self::ClassicalV1(value.to_vec())
    }
}

impl Deref for LearningSignature {
    type Target = [u8];
    fn deref(&self) -> &Self::Target {
        match self {
            Self::ClassicalV1(bytes) | Self::MlDsa65V2(bytes) => bytes,
        }
    }
}

impl DerefMut for LearningSignature {
    fn deref_mut(&mut self) -> &mut Self::Target {
        match self {
            Self::ClassicalV1(bytes) | Self::MlDsa65V2(bytes) => bytes,
        }
    }
}

impl LearningAuthenticationProfile {
    /// PQ v2 windows are half-open. Classic wire semantics stay unchanged.
    pub const fn expired_at(self, now: u64, expires_at: u64) -> bool {
        match self {
            Self::ClassicalV1 => now > expires_at,
            Self::MlDsa65V2 => now >= expires_at,
        }
    }

    pub fn learning_domain(self, classical: &[u8], pq: &[u8]) -> Vec<u8> {
        match self {
            Self::ClassicalV1 => classical.to_vec(),
            Self::MlDsa65V2 => pq.to_vec(),
        }
    }
}

/// Independently retained root-distribution floor for the learning owner.
/// This wire value carries no verified capability by itself.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LearningTrustFrontier {
    pub root_digest: [u8; 32],
    pub distribution_digest: [u8; 32],
    pub generation: u64,
    pub authority_epoch: u64,
}
