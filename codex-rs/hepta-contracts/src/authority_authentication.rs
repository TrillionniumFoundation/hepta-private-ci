//! Host-pinned signature profiles. A wire version never chooses its own trust.

use std::collections::BTreeSet;
use std::sync::Arc;

use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;

use crate::pq_auth::PqNativeVerifier;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FinalUseAuthenticationProfile {
    ClassicalV1,
    MlDsa65V2,
}

impl FinalUseAuthenticationProfile {
    /// Maximum revocation set admitted by both durable ownership and its
    /// signed feed. Hosts must roll to a new authority epoch before capacity.
    pub const fn max_revocations(self) -> usize {
        match self {
            Self::ClassicalV1 => 16_384,
            Self::MlDsa65V2 => 256,
        }
    }

    pub(crate) const fn grant_schema(self) -> u32 {
        match self {
            Self::ClassicalV1 => 1,
            Self::MlDsa65V2 => 2,
        }
    }

    pub(crate) const fn feed_schema(self) -> u32 {
        match self {
            Self::ClassicalV1 => 2,
            Self::MlDsa65V2 => 3,
        }
    }
}

/// Independently pinned ML-DSA-65 public key, canonical SPKI and epoch window.
/// The public key digest uses the same canonical key identity as Trillionnium.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PqAuthorityTrustKey {
    pub key_id: String,
    pub public_key_id: [u8; 32],
    pub public_key_spki: Vec<u8>,
    pub not_before_authority_epoch: u64,
    pub not_after_authority_epoch: u64,
}

#[derive(Clone)]
pub(crate) enum PinnedAuthorityKey {
    Classical(VerifyingKey),
    MlDsa65(Arc<PqNativeVerifier>),
}

impl PinnedAuthorityKey {
    pub(crate) fn verify(&self, message: &[u8], signature: &[u8]) -> bool {
        match self {
            Self::Classical(key) => Signature::from_slice(signature)
                .is_ok_and(|signature| key.verify_strict(message, &signature).is_ok()),
            Self::MlDsa65(key) => key.verify_exact_message(message, signature).is_ok(),
        }
    }
}

pub(crate) struct PinnedPqTrustKey {
    pub(crate) key_id: String,
    pub(crate) public_key_id: [u8; 32],
    pub(crate) key: PinnedAuthorityKey,
    pub(crate) not_before_authority_epoch: u64,
    pub(crate) not_after_authority_epoch: u64,
}

pub(crate) fn pin_pq_keys(mut keys: Vec<PqAuthorityTrustKey>) -> Result<Vec<PinnedPqTrustKey>, ()> {
    if keys.is_empty() || keys.len() > 8 {
        return Err(());
    }
    keys.sort_by(|left, right| left.key_id.cmp(&right.key_id));
    let mut ids = BTreeSet::new();
    let mut public_keys = BTreeSet::new();
    let mut pinned = Vec::with_capacity(keys.len());
    for candidate in keys {
        if candidate.key_id.is_empty()
            || candidate.key_id.len() > 128
            || !candidate
                .key_id
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"._:-/".contains(&b))
            || candidate.not_before_authority_epoch == 0
            || candidate.not_after_authority_epoch < candidate.not_before_authority_epoch
            || !ids.insert(candidate.key_id.clone())
            || !public_keys.insert(candidate.public_key_id)
        {
            return Err(());
        }
        let key =
            PqNativeVerifier::from_pinned_spki(&candidate.public_key_spki, candidate.public_key_id)
                .map_err(|_| ())?;
        pinned.push(PinnedPqTrustKey {
            key_id: candidate.key_id,
            public_key_id: candidate.public_key_id,
            key: PinnedAuthorityKey::MlDsa65(Arc::new(key)),
            not_before_authority_epoch: candidate.not_before_authority_epoch,
            not_after_authority_epoch: candidate.not_after_authority_epoch,
        });
    }
    Ok(pinned)
}
