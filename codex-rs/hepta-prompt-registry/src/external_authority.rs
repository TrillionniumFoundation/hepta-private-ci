//! External prompt-context authority verification.
//!
//! The product process never signs an authority object and never owns a signing
//! key.  It accepts only a bounded externally signed envelope, verifies it via a
//! host-owned verifier capability, and binds that verification to the exact
//! registry-owned authority snapshot digest.  Concrete KMS/HSM custody remains
//! outside this crate and outside the model/provider process.

use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::PromptContextAuthoritySnapshotV3;

const SIGNING_DOMAIN: &[u8] = b"hepta.prompt-context.external-authority.v3";
const VERIFICATION_DOMAIN: &[u8] = b"hepta.prompt-context.external-authority-verification.v3";
const MAX_SIGNATURE_BYTES: usize = 16 * 1024;

#[derive(Clone, Eq, PartialEq)]
pub struct PromptContextAuthoritySignatureV3 {
    key_id: StableId,
    key_epoch: u64,
    issuer: StableId,
    audience: StableId,
    algorithm: StableId,
    issued_unix_ms: u64,
    expires_unix_ms: u64,
    revocation_frontier: u64,
    payload_digest: Digest32,
    signature: Vec<u8>,
}

impl PromptContextAuthoritySignatureV3 {
    #[allow(clippy::too_many_arguments)]
    pub fn from_external_signature(
        key_id: StableId,
        key_epoch: u64,
        issuer: StableId,
        audience: StableId,
        algorithm: StableId,
        issued_unix_ms: u64,
        expires_unix_ms: u64,
        revocation_frontier: u64,
        payload_digest: Digest32,
        signature: Vec<u8>,
    ) -> Result<Self, ExternalPromptContextAuthorityErrorV3> {
        let value = Self {
            key_id,
            key_epoch,
            issuer,
            audience,
            algorithm,
            issued_unix_ms,
            expires_unix_ms,
            revocation_frontier,
            payload_digest,
            signature,
        };
        value.validate_shape()?;
        Ok(value)
    }

    pub fn validate_shape(&self) -> Result<(), ExternalPromptContextAuthorityErrorV3> {
        if self.key_epoch == 0
            || self.issued_unix_ms == 0
            || self.expires_unix_ms <= self.issued_unix_ms
            || self.payload_digest.is_zero()
            || self.signature.is_empty()
            || self.signature.len() > MAX_SIGNATURE_BYTES
        {
            return Err(ExternalPromptContextAuthorityErrorV3::InvalidEnvelope);
        }
        Ok(())
    }

    #[must_use]
    pub fn signing_payload(&self) -> Vec<u8> {
        let mut bytes = SIGNING_DOMAIN.to_vec();
        push_id(&mut bytes, &self.key_id);
        bytes.extend_from_slice(&self.key_epoch.to_be_bytes());
        push_id(&mut bytes, &self.issuer);
        push_id(&mut bytes, &self.audience);
        push_id(&mut bytes, &self.algorithm);
        bytes.extend_from_slice(&self.issued_unix_ms.to_be_bytes());
        bytes.extend_from_slice(&self.expires_unix_ms.to_be_bytes());
        bytes.extend_from_slice(&self.revocation_frontier.to_be_bytes());
        bytes.extend_from_slice(self.payload_digest.as_array());
        bytes
    }

    #[must_use]
    pub fn key_id(&self) -> &StableId {
        &self.key_id
    }

    #[must_use]
    pub const fn key_epoch(&self) -> u64 {
        self.key_epoch
    }

    #[must_use]
    pub fn issuer(&self) -> &StableId {
        &self.issuer
    }

    #[must_use]
    pub fn audience(&self) -> &StableId {
        &self.audience
    }

    #[must_use]
    pub fn algorithm(&self) -> &StableId {
        &self.algorithm
    }

    #[must_use]
    pub const fn issued_unix_ms(&self) -> u64 {
        self.issued_unix_ms
    }

    #[must_use]
    pub const fn expires_unix_ms(&self) -> u64 {
        self.expires_unix_ms
    }

    #[must_use]
    pub const fn revocation_frontier(&self) -> u64 {
        self.revocation_frontier
    }

    #[must_use]
    pub const fn payload_digest(&self) -> Digest32 {
        self.payload_digest
    }

    #[must_use]
    pub fn signature(&self) -> &[u8] {
        &self.signature
    }
}

impl fmt::Debug for PromptContextAuthoritySignatureV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PromptContextAuthoritySignatureV3")
            .field("key_id", &self.key_id)
            .field("key_epoch", &self.key_epoch)
            .field("issuer", &self.issuer)
            .field("audience", &self.audience)
            .field("algorithm", &self.algorithm)
            .field("issued_unix_ms", &self.issued_unix_ms)
            .field("expires_unix_ms", &self.expires_unix_ms)
            .field("revocation_frontier", &self.revocation_frontier)
            .field("payload_digest", &self.payload_digest)
            .field("signature_bytes", &self.signature.len())
            .finish()
    }
}

pub trait PromptContextAuthoritySignatureVerifierV3: Send + Sync {
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
pub struct VerifiedPromptContextAuthoritySignatureV3 {
    signed: PromptContextAuthoritySignatureV3,
    verifier_digest: Digest32,
    verification_digest: Digest32,
}

impl VerifiedPromptContextAuthoritySignatureV3 {
    #[must_use]
    pub fn signed(&self) -> &PromptContextAuthoritySignatureV3 {
        &self.signed
    }

    #[must_use]
    pub const fn verifier_digest(&self) -> Digest32 {
        self.verifier_digest
    }

    #[must_use]
    pub const fn verification_digest(&self) -> Digest32 {
        self.verification_digest
    }
}

impl fmt::Debug for VerifiedPromptContextAuthoritySignatureV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("VerifiedPromptContextAuthoritySignatureV3")
            .field("signed", &self.signed)
            .field("verifier_digest", &self.verifier_digest)
            .field("verification_digest", &self.verification_digest)
            .finish()
    }
}

#[derive(Clone, Eq, PartialEq)]
pub struct ExternallyVerifiedPromptContextAuthoritySnapshotV3 {
    snapshot: PromptContextAuthoritySnapshotV3,
    signature: VerifiedPromptContextAuthoritySignatureV3,
}

impl ExternallyVerifiedPromptContextAuthoritySnapshotV3 {
    #[must_use]
    pub fn snapshot(&self) -> &PromptContextAuthoritySnapshotV3 {
        &self.snapshot
    }

    #[must_use]
    pub fn signature(&self) -> &VerifiedPromptContextAuthoritySignatureV3 {
        &self.signature
    }

    #[must_use]
    pub const fn verification_digest(&self) -> Digest32 {
        self.signature.verification_digest()
    }
}

impl fmt::Debug for ExternallyVerifiedPromptContextAuthoritySnapshotV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ExternallyVerifiedPromptContextAuthoritySnapshotV3")
            .field("snapshot_digest", &self.snapshot.snapshot_digest())
            .field("signature", &self.signature)
            .finish()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ExternalPromptContextAuthorityErrorV3 {
    InvalidEnvelope,
    WrongPayload,
    WrongIssuer,
    WrongAudience,
    KeyEpochRollback,
    RevocationFrontierRollback,
    NotYetValid,
    Expired,
    InvalidVerifier,
    SignatureRejected,
    InvalidSnapshot,
}

impl ExternalPromptContextAuthorityErrorV3 {
    #[must_use]
    pub const fn code(self) -> &'static str {
        match self {
            Self::InvalidEnvelope => "prompt_context_external_authority_invalid_envelope",
            Self::WrongPayload => "prompt_context_external_authority_wrong_payload",
            Self::WrongIssuer => "prompt_context_external_authority_wrong_issuer",
            Self::WrongAudience => "prompt_context_external_authority_wrong_audience",
            Self::KeyEpochRollback => "prompt_context_external_authority_key_epoch_rollback",
            Self::RevocationFrontierRollback => {
                "prompt_context_external_authority_revocation_frontier_rollback"
            }
            Self::NotYetValid => "prompt_context_external_authority_not_yet_valid",
            Self::Expired => "prompt_context_external_authority_expired",
            Self::InvalidVerifier => "prompt_context_external_authority_invalid_verifier",
            Self::SignatureRejected => "prompt_context_external_authority_signature_rejected",
            Self::InvalidSnapshot => "prompt_context_external_authority_invalid_snapshot",
        }
    }
}

impl fmt::Display for ExternalPromptContextAuthorityErrorV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.code())
    }
}

impl std::error::Error for ExternalPromptContextAuthorityErrorV3 {}

#[allow(clippy::too_many_arguments)]
pub fn verify_prompt_context_authority_signature_v3(
    signed: PromptContextAuthoritySignatureV3,
    expected_payload_digest: Digest32,
    expected_issuer: &StableId,
    expected_audience: &StableId,
    minimum_key_epoch: u64,
    minimum_revocation_frontier: u64,
    now_unix_ms: u64,
    verifier: &impl PromptContextAuthoritySignatureVerifierV3,
) -> Result<VerifiedPromptContextAuthoritySignatureV3, ExternalPromptContextAuthorityErrorV3> {
    signed.validate_shape()?;
    if expected_payload_digest.is_zero() || signed.payload_digest != expected_payload_digest {
        return Err(ExternalPromptContextAuthorityErrorV3::WrongPayload);
    }
    if signed.issuer != *expected_issuer {
        return Err(ExternalPromptContextAuthorityErrorV3::WrongIssuer);
    }
    if signed.audience != *expected_audience {
        return Err(ExternalPromptContextAuthorityErrorV3::WrongAudience);
    }
    if signed.key_epoch < minimum_key_epoch {
        return Err(ExternalPromptContextAuthorityErrorV3::KeyEpochRollback);
    }
    if signed.revocation_frontier < minimum_revocation_frontier {
        return Err(ExternalPromptContextAuthorityErrorV3::RevocationFrontierRollback);
    }
    if now_unix_ms < signed.issued_unix_ms {
        return Err(ExternalPromptContextAuthorityErrorV3::NotYetValid);
    }
    if now_unix_ms >= signed.expires_unix_ms {
        return Err(ExternalPromptContextAuthorityErrorV3::Expired);
    }
    let verifier_digest = verifier.verifier_digest();
    if verifier_digest.is_zero() {
        return Err(ExternalPromptContextAuthorityErrorV3::InvalidVerifier);
    }
    let signing_payload = signed.signing_payload();
    verifier
        .verify_signature(
            &signed.key_id,
            signed.key_epoch,
            &signed.algorithm,
            &signing_payload,
            &signed.signature,
        )
        .map_err(|_| ExternalPromptContextAuthorityErrorV3::SignatureRejected)?;

    let mut verification = VERIFICATION_DOMAIN.to_vec();
    verification.extend_from_slice(verifier_digest.as_array());
    verification.extend_from_slice(Digest32::of_bytes(&signing_payload).as_array());
    verification.extend_from_slice(Digest32::of_bytes(&signed.signature).as_array());
    Ok(VerifiedPromptContextAuthoritySignatureV3 {
        signed,
        verifier_digest,
        verification_digest: Digest32::of_bytes(&verification),
    })
}

#[allow(clippy::too_many_arguments)]
pub fn verify_external_prompt_context_authority_snapshot_v3(
    snapshot: PromptContextAuthoritySnapshotV3,
    signed: PromptContextAuthoritySignatureV3,
    expected_issuer: &StableId,
    expected_audience: &StableId,
    minimum_key_epoch: u64,
    minimum_revocation_frontier: u64,
    now_unix_ms: u64,
    verifier: &impl PromptContextAuthoritySignatureVerifierV3,
) -> Result<ExternallyVerifiedPromptContextAuthoritySnapshotV3, ExternalPromptContextAuthorityErrorV3>
{
    snapshot
        .validate()
        .map_err(|_| ExternalPromptContextAuthorityErrorV3::InvalidSnapshot)?;
    if signed.revocation_frontier() < snapshot.revocation_frontier() {
        return Err(ExternalPromptContextAuthorityErrorV3::RevocationFrontierRollback);
    }
    let signature = verify_prompt_context_authority_signature_v3(
        signed,
        snapshot.snapshot_digest(),
        expected_issuer,
        expected_audience,
        minimum_key_epoch,
        minimum_revocation_frontier.max(snapshot.revocation_frontier()),
        now_unix_ms,
        verifier,
    )?;
    Ok(ExternallyVerifiedPromptContextAuthoritySnapshotV3 {
        snapshot,
        signature,
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

    struct TestVerifier {
        digest: Digest32,
        accept: bool,
    }

    impl PromptContextAuthoritySignatureVerifierV3 for TestVerifier {
        fn verifier_digest(&self) -> Digest32 {
            self.digest
        }

        fn verify_signature(
            &self,
            _key_id: &StableId,
            _key_epoch: u64,
            _algorithm: &StableId,
            _signing_payload: &[u8],
            _signature: &[u8],
        ) -> Result<(), String> {
            if self.accept {
                Ok(())
            } else {
                Err("rejected".to_owned())
            }
        }
    }

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).unwrap_or_else(|_| panic!("invalid test id"))
    }

    fn signature() -> PromptContextAuthoritySignatureV3 {
        PromptContextAuthoritySignatureV3::from_external_signature(
            id("kms-key-1"),
            7,
            id("security-authority"),
            id("context-compiler"),
            id("ed25519"),
            100,
            200,
            11,
            Digest32::of_bytes(b"snapshot"),
            vec![9; 64],
        )
        .unwrap_or_else(|_| panic!("valid external signature fixture"))
    }

    #[test]
    fn accepts_bound_external_signature() {
        let signed = signature();
        let verified = verify_prompt_context_authority_signature_v3(
            signed.clone(),
            signed.payload_digest(),
            &id("security-authority"),
            &id("context-compiler"),
            7,
            11,
            150,
            &TestVerifier {
                digest: Digest32::of_bytes(b"verifier"),
                accept: true,
            },
        )
        .unwrap_or_else(|_| panic!("signature should verify"));
        assert!(!verified.verification_digest().is_zero());
    }

    #[test]
    fn rejects_wrong_audience_epoch_frontier_expiry_and_signature() {
        let verifier = TestVerifier {
            digest: Digest32::of_bytes(b"verifier"),
            accept: true,
        };
        let signed = signature();
        assert_eq!(
            verify_prompt_context_authority_signature_v3(
                signed.clone(),
                signed.payload_digest(),
                &id("security-authority"),
                &id("other-product"),
                7,
                11,
                150,
                &verifier,
            ),
            Err(ExternalPromptContextAuthorityErrorV3::WrongAudience)
        );
        assert_eq!(
            verify_prompt_context_authority_signature_v3(
                signed.clone(),
                signed.payload_digest(),
                &id("security-authority"),
                &id("context-compiler"),
                8,
                11,
                150,
                &verifier,
            ),
            Err(ExternalPromptContextAuthorityErrorV3::KeyEpochRollback)
        );
        assert_eq!(
            verify_prompt_context_authority_signature_v3(
                signed.clone(),
                signed.payload_digest(),
                &id("security-authority"),
                &id("context-compiler"),
                7,
                12,
                150,
                &verifier,
            ),
            Err(ExternalPromptContextAuthorityErrorV3::RevocationFrontierRollback)
        );
        assert_eq!(
            verify_prompt_context_authority_signature_v3(
                signed.clone(),
                signed.payload_digest(),
                &id("security-authority"),
                &id("context-compiler"),
                7,
                11,
                200,
                &verifier,
            ),
            Err(ExternalPromptContextAuthorityErrorV3::Expired)
        );
        assert_eq!(
            verify_prompt_context_authority_signature_v3(
                signed.clone(),
                signed.payload_digest(),
                &id("security-authority"),
                &id("context-compiler"),
                7,
                11,
                150,
                &TestVerifier {
                    digest: Digest32::of_bytes(b"verifier"),
                    accept: false,
                },
            ),
            Err(ExternalPromptContextAuthorityErrorV3::SignatureRejected)
        );
    }
}
