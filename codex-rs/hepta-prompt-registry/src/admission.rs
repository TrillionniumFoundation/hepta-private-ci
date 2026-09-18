//! Authenticated prompt-factor admission.
//!
//! A caller cannot construct [VerifiedAdmission]. It is produced only after an
//! independently configured reviewer key verifies an exact factor, scope and
//! evidence binding.

use std::fmt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::SignedFinalUseGrant;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;

use crate::FactorSource;
use crate::PromptFactor;
use crate::PromptRealizationBindingV2;

const ADMISSION_DOMAIN: &[u8] = b"hepta.prompt-registry.admission.v1\0";
const FINAL_USE_REQUEST_DOMAIN: &[u8] = b"hepta.prompt-registry.final-use-admission.v1\0";
const FINAL_USE_DESTINATION: &str = "prompt.registry:admission";
const FINAL_USE_RETIRE_DESTINATION: &str = "prompt.registry:retire";
const FINAL_USE_REVOKE_DESTINATION: &str = "prompt.registry:revoke";
const FINAL_USE_REALIZATION_DESTINATION: &str = "prompt.registry:realization";
const FINAL_USE_REALIZATION_REQUEST_DOMAIN: &[u8] =
    b"hepta.prompt-registry.final-use-realization.v1\0";
const FINAL_USE_RETIRE_REQUEST_DOMAIN: &[u8] = b"hepta.prompt-registry.final-use-retire.v1\0";
const FINAL_USE_REVOKE_REQUEST_DOMAIN: &[u8] = b"hepta.prompt-registry.final-use-revoke.v1\0";
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
    not_before_unix_ms: u64,
    verified_at_unix_ms: u64,
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

    pub const fn verified_at_unix_ms(&self) -> u64 {
        self.verified_at_unix_ms
    }

    pub(crate) const fn is_live_at(&self, now_unix_ms: u64) -> bool {
        now_unix_ms >= self.not_before_unix_ms
            && now_unix_ms >= self.verified_at_unix_ms
            && now_unix_ms < self.expires_at_unix_ms
    }
}

impl AdmissionAuthority {
    pub fn new(signer_id: StableId, verifying_key: [u8; 32]) -> Result<Self, AdmissionError> {
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
        expected_reviewed_scope_digest: Digest32,
        now_unix_ms: u64,
    ) -> Result<VerifiedAdmission, AdmissionError> {
        if expected_reviewed_scope_digest.is_zero() {
            return Err(AdmissionError::ScopeMismatch);
        }
        let signing_bytes = signed.grant.signing_bytes()?;
        if signed.grant.signer_id != self.signer_id.as_str() {
            return Err(AdmissionError::SignerMismatch);
        }
        let signature = Signature::from_slice(&signed.signature)
            .map_err(|_| AdmissionError::InvalidSignature)?;
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
        if reviewed_scope_digest != expected_reviewed_scope_digest {
            return Err(AdmissionError::ScopeMismatch);
        }
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
            not_before_unix_ms: signed.grant.not_before_unix_ms,
            verified_at_unix_ms: now_unix_ms,
            expires_at_unix_ms: signed.grant.expires_at_unix_ms,
        })
    }
}

#[derive(Clone, Copy, Debug)]
pub struct FinalUseAdmissionAuthority<'a> {
    authority: &'a FinalUseAuthority,
}

impl<'a> FinalUseAdmissionAuthority<'a> {
    #[must_use]
    pub const fn new(authority: &'a FinalUseAuthority) -> Self {
        Self { authority }
    }

    pub fn verify(
        &self,
        signed: &SignedFinalUseGrant,
        factor: &PromptFactor,
        expected_reviewed_scope_digest: Digest32,
        expected_evidence_digest: Digest32,
    ) -> Result<VerifiedAdmission, AdmissionError> {
        self.with_verified_admission(
            signed,
            factor,
            expected_reviewed_scope_digest,
            expected_evidence_digest,
            |admission| admission,
        )
    }

    pub fn with_verified_admission<T>(
        &self,
        signed: &SignedFinalUseGrant,
        factor: &PromptFactor,
        expected_reviewed_scope_digest: Digest32,
        expected_evidence_digest: Digest32,
        consumer: impl FnOnce(VerifiedAdmission) -> T,
    ) -> Result<T, AdmissionError> {
        let reviewer_id = StableId::new(signed.grant.binding.subject_id.clone())
            .map_err(|_| AdmissionError::InvalidGrant)?;
        let expected = final_use_admission_binding(
            factor,
            &reviewer_id,
            expected_reviewed_scope_digest,
            expected_evidence_digest,
        )?;
        let token = self
            .authority
            .claim(signed, &expected)
            .map_err(map_final_use_error)?;
        let verified_at_unix_ms = current_unix_ms()?;
        let grant_id = StableId::new(signed.grant.grant_id.clone())
            .map_err(|_| AdmissionError::InvalidGrant)?;
        self.authority
            .with_verified_use(token, &expected, || {
                consumer(VerifiedAdmission {
                    grant_id,
                    factor_id: factor.factor_id.clone(),
                    factor_content_digest: factor.content_digest,
                    reviewer_id,
                    reviewed_scope_digest: expected_reviewed_scope_digest,
                    evidence_digest: expected_evidence_digest,
                    not_before_unix_ms: signed.grant.not_before_unix_ms,
                    verified_at_unix_ms,
                    expires_at_unix_ms: signed.grant.expires_at_unix_ms,
                })
            })
            .map_err(map_final_use_error)
    }
}

pub fn final_use_admission_binding(
    factor: &PromptFactor,
    reviewer_id: &StableId,
    reviewed_scope_digest: Digest32,
    evidence_digest: Digest32,
) -> Result<FinalUseBinding, AdmissionError> {
    if factor.source != FactorSource::GovernedInternal {
        return Err(AdmissionError::UntrustedFactor);
    }
    if reviewer_id == &factor.proposer_id {
        return Err(AdmissionError::SelfReview);
    }
    if reviewed_scope_digest.is_zero() || evidence_digest.is_zero() {
        return Err(AdmissionError::ScopeMismatch);
    }
    let mut request = FINAL_USE_REQUEST_DOMAIN.to_vec();
    push_id(&mut request, &factor.factor_id);
    push_id(&mut request, &factor.proposer_id);
    push_id(&mut request, &factor.semantic_version);
    push_text(&mut request, &factor.semantic_purpose);
    push_text(&mut request, &factor.authority_class);
    request.extend_from_slice(
        &u32::try_from(factor.eligible_objective_dimensions.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    for dimension in &factor.eligible_objective_dimensions {
        push_id(&mut request, dimension);
    }
    request.extend_from_slice(factor.content_digest.as_array());
    Ok(FinalUseBinding {
        subject_id: reviewer_id.to_string(),
        destination_id: FINAL_USE_DESTINATION.to_owned(),
        request_sha256: Digest32::of_bytes(&request).into_array(),
        scope_sha256: reviewed_scope_digest.into_array(),
        payload_sha256: evidence_digest.into_array(),
    })
}


pub fn final_use_realization_binding(
    factor: &PromptFactor,
    actor_id: &StableId,
    scope_digest: Digest32,
    binding: &PromptRealizationBindingV2,
    supersedes_realization_id: Option<&StableId>,
) -> Result<FinalUseBinding, AdmissionError> {
    if scope_digest.is_zero()
        || factor.lifecycle != crate::Lifecycle::Admitted
        || factor.factor_id != binding.factor_id
    {
        return Err(AdmissionError::ScopeMismatch);
    }
    binding.validate().map_err(|_| AdmissionError::InvalidGrant)?;
    let mut request = FINAL_USE_REALIZATION_REQUEST_DOMAIN.to_vec();
    push_id(&mut request, &factor.factor_id);
    push_id(&mut request, &factor.proposer_id);
    push_id(&mut request, &factor.semantic_version);
    push_text(&mut request, &factor.semantic_purpose);
    push_text(&mut request, &factor.authority_class);
    request.extend_from_slice(
        &u32::try_from(factor.eligible_objective_dimensions.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    for dimension in &factor.eligible_objective_dimensions {
        push_id(&mut request, dimension);
    }
    request.extend_from_slice(factor.content_digest.as_array());
    request.extend_from_slice(binding.digest().as_array());
    match supersedes_realization_id {
        Some(predecessor) => {
            request.push(1);
            push_id(&mut request, predecessor);
        }
        None => request.push(0),
    }
    Ok(FinalUseBinding {
        subject_id: actor_id.to_string(),
        destination_id: FINAL_USE_REALIZATION_DESTINATION.to_owned(),
        request_sha256: Digest32::of_bytes(&request).into_array(),
        scope_sha256: scope_digest.into_array(),
        payload_sha256: binding.payload_digest.into_array(),
    })
}

pub fn final_use_retire_binding(
    factor: &PromptFactor,
    actor_id: &StableId,
    scope_digest: Digest32,
    reason_digest: Digest32,
) -> Result<FinalUseBinding, AdmissionError> {
    final_use_lifecycle_binding(
        FINAL_USE_RETIRE_REQUEST_DOMAIN,
        FINAL_USE_RETIRE_DESTINATION,
        factor,
        actor_id,
        scope_digest,
        reason_digest,
        None,
    )
}

pub fn final_use_revoke_binding(
    factor: &PromptFactor,
    actor_id: &StableId,
    scope_digest: Digest32,
    reason_digest: Digest32,
    cutoff_unix_ms: u64,
) -> Result<FinalUseBinding, AdmissionError> {
    if cutoff_unix_ms == 0 {
        return Err(AdmissionError::InvalidGrant);
    }
    final_use_lifecycle_binding(
        FINAL_USE_REVOKE_REQUEST_DOMAIN,
        FINAL_USE_REVOKE_DESTINATION,
        factor,
        actor_id,
        scope_digest,
        reason_digest,
        Some(cutoff_unix_ms),
    )
}

fn final_use_lifecycle_binding(
    domain: &[u8],
    destination: &str,
    factor: &PromptFactor,
    actor_id: &StableId,
    scope_digest: Digest32,
    reason_digest: Digest32,
    cutoff_unix_ms: Option<u64>,
) -> Result<FinalUseBinding, AdmissionError> {
    if scope_digest.is_zero() || reason_digest.is_zero() {
        return Err(AdmissionError::ScopeMismatch);
    }
    let mut request = domain.to_vec();
    push_id(&mut request, &factor.factor_id);
    push_id(&mut request, &factor.proposer_id);
    push_id(&mut request, &factor.semantic_version);
    push_text(&mut request, &factor.semantic_purpose);
    push_text(&mut request, &factor.authority_class);
    request.extend_from_slice(
        &u32::try_from(factor.eligible_objective_dimensions.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    for dimension in &factor.eligible_objective_dimensions {
        push_id(&mut request, dimension);
    }
    request.extend_from_slice(factor.content_digest.as_array());
    request.push(match factor.lifecycle {
        crate::Lifecycle::Draft => 0,
        crate::Lifecycle::Admitted => 1,
        crate::Lifecycle::Retired => 2,
        crate::Lifecycle::Revoked => 3,
    });
    let mut payload = domain.to_vec();
    payload.extend_from_slice(reason_digest.as_array());
    match cutoff_unix_ms {
        Some(value) => {
            payload.push(1);
            payload.extend_from_slice(&value.to_be_bytes());
        }
        None => payload.push(0),
    }
    Ok(FinalUseBinding {
        subject_id: actor_id.to_string(),
        destination_id: destination.to_owned(),
        request_sha256: Digest32::of_bytes(&request).into_array(),
        scope_sha256: scope_digest.into_array(),
        payload_sha256: Digest32::of_bytes(&payload).into_array(),
    })
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    push_text(bytes, value.as_str());
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    let raw = value.as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

fn current_unix_ms() -> Result<u64, AdmissionError> {
    let value = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| AdmissionError::AuthorityUnavailable)?
        .as_millis();
    u64::try_from(value).map_err(|_| AdmissionError::AuthorityUnavailable)
}

pub(crate) const fn map_final_use_error(error: FinalUseError) -> AdmissionError {
    match error {
        FinalUseError::Unavailable | FinalUseError::StateLocked => {
            AdmissionError::AuthorityUnavailable
        }
        FinalUseError::Revoked => AdmissionError::Revoked,
        FinalUseError::AlreadyClaimed => AdmissionError::AlreadyUsed,
        FinalUseError::NotYetValid => AdmissionError::NotYetValid,
        FinalUseError::Expired => AdmissionError::Expired,
        FinalUseError::BindingMismatch => AdmissionError::FactorBindingMismatch,
        FinalUseError::InvalidGrant
        | FinalUseError::InvalidTrust
        | FinalUseError::InvalidSignature
        | FinalUseError::EpochMismatch
        | FinalUseError::StaleRevocationHead
        | FinalUseError::CapacityExceeded
        | FinalUseError::UnsafeStateDirectory => AdmissionError::InvalidGrant,
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
    ScopeMismatch,
    UntrustedFactor,
    SelfReview,
    NotYetValid,
    Expired,
    Revoked,
    AlreadyUsed,
    AuthorityUnavailable,
}

impl fmt::Display for AdmissionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for AdmissionError {}
