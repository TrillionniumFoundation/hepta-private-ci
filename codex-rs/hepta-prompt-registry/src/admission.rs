//! Authenticated prompt-factor admission.
//!
//! A caller cannot construct [VerifiedAdmission]. It is produced only after an
//! independently configured reviewer key verifies an exact factor, scope and
//! evidence binding.

use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;

use crate::FactorSource;
use crate::PromptFactor;

const ADMISSION_DOMAIN: &[u8] = b"hepta.prompt-registry.admission.v1\0";
const MAX_ADMISSION_LIFETIME_MS: u64 = 300_000;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AdmissionBindingV1 {
    pub factor_id: String,
    pub factor_content_sha256: [u8; 32],
    pub reviewer_id: String,
    pub reviewed_scope_sha256: [u8; 32],
    pub evidence_sha256: [u8; 32],
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AdmissionGrantV1 {
    pub schema_version: u32,
    pub signer_id: String,
    pub grant_id: String,
    pub binding: AdmissionBindingV1,
    pub not_before_unix_ms: u64,
    pub expires_at_unix_ms: u64,
}

impl AdmissionGrantV1 {
    pub fn signing_bytes(&self) -> Result<Vec<u8>, AdmissionError> {
        validate_grant_shape(self)?;
        let mut bytes = ADMISSION_DOMAIN.to_vec();
        bytes.extend(serde_json::to_vec(self).map_err(|_| AdmissionError::InvalidGrant)?);
        Ok(bytes)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SignedAdmissionGrantV1 {
    pub grant: AdmissionGrantV1,
    pub signature: Vec<u8>,
}

#[derive(Clone)]
pub struct AdmissionAuthority {
    signer_id: StableId,
    key: VerifyingKey,
}

impl fmt::Debug for AdmissionAuthority {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("AdmissionAuthority([PINNED REVIEW TRUST])")
    }
}

#[derive(Debug)]
pub struct VerifiedAdmission {
    grant_id: StableId,
    factor_id: StableId,
    factor_content_digest: Digest32,
    reviewer_id: StableId,
    reviewed_scope_digest: Digest32,
    evidence_digest: Digest32,
    expires_at_unix_ms: u64,
}

impl VerifiedAdmission {
    pub fn grant_id(&self) -> &StableId {
        &self.grant_id
    }

    pub fn factor_id(&self) -> &StableId {
        &self.factor_id
    }

    pub const fn factor_content_digest(&self) -> Digest32 {
        self.factor_content_digest
    }

    pub fn reviewer_id(&self) -> &StableId {
        &self.reviewer_id
    }

    pub const fn reviewed_scope_digest(&self) -> Digest32 {
        self.reviewed_scope_digest
    }

    pub const fn evidence_digest(&self) -> Digest32 {
        self.evidence_digest
    }

    pub const fn expires_at_unix_ms(&self) -> u64 {
        self.expires_at_unix_ms
    }

    pub(crate) const fn is_live_at(&self, now_unix_ms: u64) -> bool {
        now_unix_ms < self.expires_at_unix_ms
    }
}

impl AdmissionAuthority {
    pub fn new(
        signer_id: StableId,
        verifying_key: [u8; 32],
    ) -> Result<Self, AdmissionError> {
        let key =
            VerifyingKey::from_bytes(&verifying_key).map_err(|_| AdmissionError::InvalidTrust)?;
        if key.is_weak() {
            return Err(AdmissionError::InvalidTrust);
        }
        Ok(Self { signer_id, key })
    }

    pub fn verify(
        &self,
        signed: &SignedAdmissionGrantV1,
        factor: &PromptFactor,
        now_unix_ms: u64,
    ) -> Result<VerifiedAdmission, AdmissionError> {
        let signing_bytes = signed.grant.signing_bytes()?;
        if signed.grant.signer_id != self.signer_id.as_str() {
            return Err(AdmissionError::SignerMismatch);
        }
        let signature =
            Signature::from_slice(&signed.signature).map_err(|_| AdmissionError::InvalidSignature)?;
        self.key
            .verify_strict(&signing_bytes, &signature)
            .map_err(|_| AdmissionError::InvalidSignature)?;

        if now_unix_ms < signed.grant.not_before_unix_ms {
            return Err(AdmissionError::NotYetValid);
        }
        if now_unix_ms >= signed.grant.expires_at_unix_ms {
            return Err(AdmissionError::Expired);
        }

        let factor_id = StableId::new(signed.grant.binding.factor_id.clone())
            .map_err(|_| AdmissionError::InvalidGrant)?;
        let reviewer_id = StableId::new(signed.grant.binding.reviewer_id.clone())
            .map_err(|_| AdmissionError::InvalidGrant)?;
        let grant_id = StableId::new(signed.grant.grant_id.clone())
            .map_err(|_| AdmissionError::InvalidGrant)?;
        let factor_content_digest =
            Digest32::from_array(signed.grant.binding.factor_content_sha256);
        let reviewed_scope_digest =
            Digest32::from_array(signed.grant.binding.reviewed_scope_sha256);
        let evidence_digest = Digest32::from_array(signed.grant.binding.evidence_sha256);

        if factor.source != FactorSource::GovernedInternal {
            return Err(AdmissionError::UntrustedFactor);
        }
        if factor.factor_id != factor_id || factor.content_digest != factor_content_digest {
            return Err(AdmissionError::FactorBindingMismatch);
        }
        if factor.proposer_id == reviewer_id {
            return Err(AdmissionError::SelfReview);
        }

        Ok(VerifiedAdmission {
            grant_id,
            factor_id,
            factor_content_digest,
            reviewer_id,
            reviewed_scope_digest,
            evidence_digest,
            expires_at_unix_ms: signed.grant.expires_at_unix_ms,
        })
    }
}

fn validate_grant_shape(grant: &AdmissionGrantV1) -> Result<(), AdmissionError> {
    if grant.schema_version != 1
        || StableId::new(grant.signer_id.clone()).is_err()
        || StableId::new(grant.grant_id.clone()).is_err()
        || StableId::new(grant.binding.factor_id.clone()).is_err()
        || StableId::new(grant.binding.reviewer_id.clone()).is_err()
        || grant.binding.factor_content_sha256 == [0; 32]
        || grant.binding.reviewed_scope_sha256 == [0; 32]
        || grant.binding.evidence_sha256 == [0; 32]
        || grant.expires_at_unix_ms <= grant.not_before_unix_ms
        || grant.expires_at_unix_ms - grant.not_before_unix_ms > MAX_ADMISSION_LIFETIME_MS
    {
        return Err(AdmissionError::InvalidGrant);
    }
    Ok(())
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AdmissionError {
    InvalidGrant,
    InvalidTrust,
    InvalidSignature,
    SignerMismatch,
    FactorBindingMismatch,
    UntrustedFactor,
    SelfReview,
    NotYetValid,
    Expired,
}

impl fmt::Display for AdmissionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for AdmissionError {}
