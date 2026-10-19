//! Independently authenticated provider terminal acknowledgement.
//!
//! The attestation binds the exact attempt and encoded provider-body digest.
//! Agentd verifies it through a host-owned capability; it cannot mint or sign
//! an acknowledgement itself.

use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const ATTESTATION_DOMAIN: &[u8] = b"hepta.context-provider-terminal-attestation.v3";
const VERIFICATION_DOMAIN: &[u8] = b"hepta.context-provider-terminal-verification.v3";
const MAX_SIGNATURE_BYTES: usize = 16 * 1024;

#[derive(Clone, Eq, PartialEq)]
pub struct IndependentProviderTerminalAttestationV3 {
    key_id: StableId,
    key_epoch: u64,
    issuer: StableId,
    audience: StableId,
    algorithm: StableId,
    attempt_id: StableId,
    exact_body_digest: Digest32,
    provider_receipt_digest: Digest32,
    terminal_observation_digest: Digest32,
    revocation_frontier: u64,
    observed_unix_ms: u64,
    expires_unix_ms: u64,
    signature: Vec<u8>,
}

impl IndependentProviderTerminalAttestationV3 {
    #[allow(clippy::too_many_arguments)]
    pub fn from_external_attestor(
        key_id: StableId,
        key_epoch: u64,
        issuer: StableId,
        audience: StableId,
        algorithm: StableId,
        attempt_id: StableId,
        exact_body_digest: Digest32,
        provider_receipt_digest: Digest32,
        terminal_observation_digest: Digest32,
        revocation_frontier: u64,
        observed_unix_ms: u64,
        expires_unix_ms: u64,
        signature: Vec<u8>,
    ) -> Result<Self, ProviderTerminalAttestationErrorV3> {
        let value = Self {
            key_id,
            key_epoch,
            issuer,
            audience,
            algorithm,
            attempt_id,
            exact_body_digest,
            provider_receipt_digest,
            terminal_observation_digest,
            revocation_frontier,
            observed_unix_ms,
            expires_unix_ms,
            signature,
        };
        value.validate_shape()?;
        Ok(value)
    }

    pub fn validate_shape(&self) -> Result<(), ProviderTerminalAttestationErrorV3> {
        if self.key_epoch == 0
            || self.exact_body_digest.is_zero()
            || self.provider_receipt_digest.is_zero()
            || self.terminal_observation_digest.is_zero()
            || self.observed_unix_ms == 0
            || self.expires_unix_ms <= self.observed_unix_ms
            || self.signature.is_empty()
            || self.signature.len() > MAX_SIGNATURE_BYTES
        {
            return Err(ProviderTerminalAttestationErrorV3::InvalidAttestation);
        }
        Ok(())
    }

    #[must_use]
    pub fn signing_payload(&self) -> Vec<u8> {
        let mut bytes = ATTESTATION_DOMAIN.to_vec();
        for value in [
            &self.key_id,
            &self.issuer,
            &self.audience,
            &self.algorithm,
            &self.attempt_id,
        ] {
            push_id(&mut bytes, value);
        }
        bytes.extend_from_slice(&self.key_epoch.to_be_bytes());
        bytes.extend_from_slice(self.exact_body_digest.as_array());
        bytes.extend_from_slice(self.provider_receipt_digest.as_array());
        bytes.extend_from_slice(self.terminal_observation_digest.as_array());
        bytes.extend_from_slice(&self.revocation_frontier.to_be_bytes());
        bytes.extend_from_slice(&self.observed_unix_ms.to_be_bytes());
        bytes.extend_from_slice(&self.expires_unix_ms.to_be_bytes());
        bytes
    }

    #[must_use]
    pub fn attempt_id(&self) -> &StableId {
        &self.attempt_id
    }

    #[must_use]
    pub const fn exact_body_digest(&self) -> Digest32 {
        self.exact_body_digest
    }

    #[must_use]
    pub const fn provider_receipt_digest(&self) -> Digest32 {
        self.provider_receipt_digest
    }

    #[must_use]
    pub const fn terminal_observation_digest(&self) -> Digest32 {
        self.terminal_observation_digest
    }

    #[must_use]
    pub const fn observed_unix_ms(&self) -> u64 {
        self.observed_unix_ms
    }

    #[must_use]
    pub const fn revocation_frontier(&self) -> u64 {
        self.revocation_frontier
    }
}

impl fmt::Debug for IndependentProviderTerminalAttestationV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("IndependentProviderTerminalAttestationV3")
            .field("key_id", &self.key_id)
            .field("key_epoch", &self.key_epoch)
            .field("issuer", &self.issuer)
            .field("audience", &self.audience)
            .field("algorithm", &self.algorithm)
            .field("attempt_id", &self.attempt_id)
            .field("exact_body_digest", &self.exact_body_digest)
            .field("provider_receipt_digest", &self.provider_receipt_digest)
            .field(
                "terminal_observation_digest",
                &self.terminal_observation_digest,
            )
            .field("revocation_frontier", &self.revocation_frontier)
            .field("observed_unix_ms", &self.observed_unix_ms)
            .field("expires_unix_ms", &self.expires_unix_ms)
            .field("signature_bytes", &self.signature.len())
            .finish()
    }
}

pub trait ProviderTerminalAttestationVerifierV3: Send + Sync {
    fn verifier_digest(&self) -> Digest32;

    fn verify_signature(
        &self,
        key_id: &StableId,
        key_epoch: u64,
        algorithm: &StableId,
        signing_payload: &[u8],
        signature: &[u8],
    ) -> Result<(), String>;
}

#[derive(Clone, Eq, PartialEq)]
pub struct VerifiedProviderTerminalAttestationV3 {
    attestation: IndependentProviderTerminalAttestationV3,
    verifier_digest: Digest32,
    verification_digest: Digest32,
}

impl VerifiedProviderTerminalAttestationV3 {
    #[must_use]
    pub fn attestation(&self) -> &IndependentProviderTerminalAttestationV3 {
        &self.attestation
    }

    #[must_use]
    pub const fn verification_digest(&self) -> Digest32 {
        self.verification_digest
    }
}

impl fmt::Debug for VerifiedProviderTerminalAttestationV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("VerifiedProviderTerminalAttestationV3")
            .field("attestation", &self.attestation)
            .field("verifier_digest", &self.verifier_digest)
            .field("verification_digest", &self.verification_digest)
            .finish()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProviderTerminalAttestationErrorV3 {
    InvalidAttestation,
    AttemptMismatch,
    ExactBodyMismatch,
    ReceiptMismatch,
    ObservationMismatch,
    WrongIssuer,
    WrongAudience,
    KeyEpochRollback,
    RevocationFrontierRollback,
    Expired,
    InvalidVerifier,
    SignatureRejected,
}

impl ProviderTerminalAttestationErrorV3 {
    #[must_use]
    pub const fn code(self) -> &'static str {
        match self {
            Self::InvalidAttestation => "provider_terminal_attestation_invalid",
            Self::AttemptMismatch => "provider_terminal_attestation_attempt_mismatch",
            Self::ExactBodyMismatch => "provider_terminal_attestation_exact_body_mismatch",
            Self::ReceiptMismatch => "provider_terminal_attestation_receipt_mismatch",
            Self::ObservationMismatch => "provider_terminal_attestation_observation_mismatch",
            Self::WrongIssuer => "provider_terminal_attestation_wrong_issuer",
            Self::WrongAudience => "provider_terminal_attestation_wrong_audience",
            Self::KeyEpochRollback => "provider_terminal_attestation_key_epoch_rollback",
            Self::RevocationFrontierRollback => {
                "provider_terminal_attestation_revocation_frontier_rollback"
            }
            Self::Expired => "provider_terminal_attestation_expired",
            Self::InvalidVerifier => "provider_terminal_attestation_invalid_verifier",
            Self::SignatureRejected => "provider_terminal_attestation_signature_rejected",
        }
    }
}

impl fmt::Display for ProviderTerminalAttestationErrorV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.code())
    }
}

impl std::error::Error for ProviderTerminalAttestationErrorV3 {}

#[allow(clippy::too_many_arguments)]
pub fn verify_provider_terminal_attestation_v3(
    attestation: IndependentProviderTerminalAttestationV3,
    expected_attempt_id: &StableId,
    expected_exact_body_digest: Digest32,
    expected_provider_receipt_digest: Digest32,
    expected_terminal_observation_digest: Digest32,
    expected_issuer: &StableId,
    expected_audience: &StableId,
    minimum_key_epoch: u64,
    minimum_revocation_frontier: u64,
    now_unix_ms: u64,
    verifier: &impl ProviderTerminalAttestationVerifierV3,
) -> Result<VerifiedProviderTerminalAttestationV3, ProviderTerminalAttestationErrorV3> {
    attestation.validate_shape()?;
    if attestation.attempt_id != *expected_attempt_id {
        return Err(ProviderTerminalAttestationErrorV3::AttemptMismatch);
    }
    if attestation.exact_body_digest != expected_exact_body_digest
        || expected_exact_body_digest.is_zero()
    {
        return Err(ProviderTerminalAttestationErrorV3::ExactBodyMismatch);
    }
    if attestation.provider_receipt_digest != expected_provider_receipt_digest
        || expected_provider_receipt_digest.is_zero()
    {
        return Err(ProviderTerminalAttestationErrorV3::ReceiptMismatch);
    }
    if attestation.terminal_observation_digest != expected_terminal_observation_digest
        || expected_terminal_observation_digest.is_zero()
    {
        return Err(ProviderTerminalAttestationErrorV3::ObservationMismatch);
    }
    if attestation.issuer != *expected_issuer {
        return Err(ProviderTerminalAttestationErrorV3::WrongIssuer);
    }
    if attestation.audience != *expected_audience {
        return Err(ProviderTerminalAttestationErrorV3::WrongAudience);
    }
    if attestation.key_epoch < minimum_key_epoch {
        return Err(ProviderTerminalAttestationErrorV3::KeyEpochRollback);
    }
    if attestation.revocation_frontier < minimum_revocation_frontier {
        return Err(ProviderTerminalAttestationErrorV3::RevocationFrontierRollback);
    }
    if now_unix_ms < attestation.observed_unix_ms || now_unix_ms >= attestation.expires_unix_ms {
        return Err(ProviderTerminalAttestationErrorV3::Expired);
    }
    let verifier_digest = verifier.verifier_digest();
    if verifier_digest.is_zero() {
        return Err(ProviderTerminalAttestationErrorV3::InvalidVerifier);
    }
    let signing_payload = attestation.signing_payload();
    verifier
        .verify_signature(
            &attestation.key_id,
            attestation.key_epoch,
            &attestation.algorithm,
            &signing_payload,
            &attestation.signature,
        )
        .map_err(|_| ProviderTerminalAttestationErrorV3::SignatureRejected)?;
    let mut bytes = VERIFICATION_DOMAIN.to_vec();
    bytes.extend_from_slice(verifier_digest.as_array());
    bytes.extend_from_slice(Digest32::of_bytes(&signing_payload).as_array());
    bytes.extend_from_slice(Digest32::of_bytes(&attestation.signature).as_array());
    Ok(VerifiedProviderTerminalAttestationV3 {
        attestation,
        verifier_digest,
        verification_digest: Digest32::of_bytes(&bytes),
    })
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Verifier(bool);

    impl ProviderTerminalAttestationVerifierV3 for Verifier {
        fn verifier_digest(&self) -> Digest32 {
            Digest32::of_bytes(b"terminal-verifier")
        }

        fn verify_signature(
            &self,
            _key_id: &StableId,
            _key_epoch: u64,
            _algorithm: &StableId,
            _signing_payload: &[u8],
            _signature: &[u8],
        ) -> Result<(), String> {
            if self.0 {
                Ok(())
            } else {
                Err("rejected".to_owned())
            }
        }
    }

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).unwrap_or_else(|_| panic!("invalid test id"))
    }

    fn attestation() -> IndependentProviderTerminalAttestationV3 {
        IndependentProviderTerminalAttestationV3::from_external_attestor(
            id("provider-key"),
            3,
            id("provider-reconciler"),
            id("context-compiler"),
            id("ed25519"),
            id("attempt-1"),
            Digest32::of_bytes(b"body"),
            Digest32::of_bytes(b"receipt"),
            Digest32::of_bytes(b"terminal"),
            8,
            100,
            200,
            vec![7; 64],
        )
        .unwrap_or_else(|_| panic!("valid fixture"))
    }

    #[test]
    fn binds_attempt_and_exact_body() {
        let value = attestation();
        let verified = verify_provider_terminal_attestation_v3(
            value.clone(),
            &id("attempt-1"),
            value.exact_body_digest(),
            value.provider_receipt_digest(),
            value.terminal_observation_digest(),
            &id("provider-reconciler"),
            &id("context-compiler"),
            3,
            8,
            150,
            &Verifier(true),
        )
        .unwrap_or_else(|_| panic!("attestation should verify"));
        assert!(!verified.verification_digest().is_zero());
    }

    #[test]
    fn rejects_body_drift_and_bad_signature() {
        let value = attestation();
        assert_eq!(
            verify_provider_terminal_attestation_v3(
                value.clone(),
                &id("attempt-1"),
                Digest32::of_bytes(b"different-body"),
                value.provider_receipt_digest(),
                value.terminal_observation_digest(),
                &id("provider-reconciler"),
                &id("context-compiler"),
                3,
                8,
                150,
                &Verifier(true),
            ),
            Err(ProviderTerminalAttestationErrorV3::ExactBodyMismatch)
        );
        assert_eq!(
            verify_provider_terminal_attestation_v3(
                value.clone(),
                &id("attempt-1"),
                value.exact_body_digest(),
                value.provider_receipt_digest(),
                value.terminal_observation_digest(),
                &id("provider-reconciler"),
                &id("context-compiler"),
                3,
                8,
                150,
                &Verifier(false),
            ),
            Err(ProviderTerminalAttestationErrorV3::SignatureRejected)
        );
    }
}
