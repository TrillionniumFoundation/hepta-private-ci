//! Cryptographic admission for owner summaries consumed by global planning.
//!
//! The trusted host pins one Ed25519 key per producer. Control verifies the
//! complete summary bytes but never holds the producer signing key.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;

use crate::AuthenticatedOwnerSummaryV1;
use crate::OwnerReadinessV1;
use crate::OwnerSummaryV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedOwnerSummaryV1 {
    pub producer_id: StableId,
    pub signature: Vec<u8>,
}

#[derive(Clone)]
pub struct OwnerSummaryVerifierV1 {
    producer_id: StableId,
    key: VerifyingKey,
}

impl fmt::Debug for OwnerSummaryVerifierV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("OwnerSummaryVerifierV1")
            .field("producer_id", &self.producer_id)
            .field("key", &"[PINNED TRUST]")
            .finish()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OwnerSummaryVerificationError {
    InvalidTrust,
    ProducerMismatch,
    InvalidSignature,
}

impl fmt::Display for OwnerSummaryVerificationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for OwnerSummaryVerificationError {}

impl OwnerSummaryVerifierV1 {
    pub fn new(
        producer_id: StableId,
        verifying_key: [u8; 32],
    ) -> Result<Self, OwnerSummaryVerificationError> {
        let key = VerifyingKey::from_bytes(&verifying_key)
            .map_err(|_| OwnerSummaryVerificationError::InvalidTrust)?;
        if key.is_weak() {
            return Err(OwnerSummaryVerificationError::InvalidTrust);
        }
        Ok(Self { producer_id, key })
    }

    pub fn verify(
        &self,
        summary: OwnerSummaryV1,
        signed: &SignedOwnerSummaryV1,
    ) -> Result<AuthenticatedOwnerSummaryV1, OwnerSummaryVerificationError> {
        if summary.owner_id != self.producer_id || signed.producer_id != self.producer_id {
            return Err(OwnerSummaryVerificationError::ProducerMismatch);
        }
        let signature = Signature::from_slice(&signed.signature)
            .map_err(|_| OwnerSummaryVerificationError::InvalidSignature)?;
        self.key
            .verify_strict(&owner_summary_signing_bytes_v1(&summary), &signature)
            .map_err(|_| OwnerSummaryVerificationError::InvalidSignature)?;
        Ok(AuthenticatedOwnerSummaryV1::from_verified(summary))
    }
}

#[must_use]
pub fn owner_summary_signing_bytes_v1(summary: &OwnerSummaryV1) -> Vec<u8> {
    let mut bytes = b"hepta.control.owner-summary.v1\0".to_vec();
    push_id(&mut bytes, &summary.owner_id);
    bytes.extend_from_slice(&summary.revision.get().to_be_bytes());
    bytes.extend_from_slice(summary.objective_digest.as_array());
    bytes.extend_from_slice(&summary.body_generation.get().to_be_bytes());
    bytes.extend_from_slice(summary.configuration_digest.as_array());
    bytes.extend_from_slice(&summary.observed_at_micros.to_be_bytes());
    bytes.extend_from_slice(&summary.expires_at_micros.to_be_bytes());
    bytes.push(match summary.readiness {
        OwnerReadinessV1::Ready => 0,
        OwnerReadinessV1::Degraded => 1,
        OwnerReadinessV1::Unavailable => 2,
    });
    bytes.extend_from_slice(summary.source_frontier_digest.as_array());
    bytes.extend_from_slice(summary.support_digest.as_array());
    bytes
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    let raw = id.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::Digest32;
    use codex_hepta_types::Generation;
    use codex_hepta_types::Revision;
    use ed25519_dalek::Signer as _;
    use ed25519_dalek::SigningKey;

    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn summary() -> OwnerSummaryV1 {
        OwnerSummaryV1 {
            owner_id: id("fleet-owner"),
            revision: Revision::new(7).expect("revision"),
            objective_digest: digest("objective"),
            body_generation: Generation::new(11).expect("generation"),
            configuration_digest: digest("configuration"),
            observed_at_micros: 1_000,
            expires_at_micros: 2_000,
            readiness: OwnerReadinessV1::Ready,
            source_frontier_digest: digest("frontier"),
            support_digest: digest("support"),
        }
    }

    #[test]
    fn pinned_ed25519_owner_key_admits_only_the_exact_summary() {
        let signing = SigningKey::from_bytes(&[9_u8; 32]);
        let verifier = OwnerSummaryVerifierV1::new(
            id("fleet-owner"),
            signing.verifying_key().to_bytes(),
        )
        .expect("verifier");
        let original = summary();
        let proof = SignedOwnerSummaryV1 {
            producer_id: id("fleet-owner"),
            signature: signing
                .sign(&owner_summary_signing_bytes_v1(&original))
                .to_bytes()
                .to_vec(),
        };

        let admitted = verifier
            .verify(original.clone(), &proof)
            .expect("signed summary");
        assert_eq!(admitted.summary(), &original);

        let mut changed = original;
        changed.support_digest = digest("changed-support");
        assert_eq!(
            verifier.verify(changed, &proof),
            Err(OwnerSummaryVerificationError::InvalidSignature)
        );
    }

    #[test]
    fn signer_identity_is_pinned_outside_request_metadata() {
        let signing = SigningKey::from_bytes(&[7_u8; 32]);
        let verifier =
            OwnerSummaryVerifierV1::new(id("fleet-owner"), signing.verifying_key().to_bytes())
                .expect("verifier");
        let value = summary();
        let proof = SignedOwnerSummaryV1 {
            producer_id: id("other-owner"),
            signature: signing
                .sign(&owner_summary_signing_bytes_v1(&value))
                .to_bytes()
                .to_vec(),
        };
        assert_eq!(
            verifier.verify(value, &proof),
            Err(OwnerSummaryVerificationError::ProducerMismatch)
        );
    }
}
