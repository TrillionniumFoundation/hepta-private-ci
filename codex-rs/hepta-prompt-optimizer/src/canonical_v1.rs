//! Canonical, authority-free prompt candidate enumeration.
//!
//! Authentication remains a host/owner concern supplied through a narrow trait.
//! The optimizer validates the exact authenticated source it consumes and emits
//! deterministic receipts; an opaque digest alone is never treated as evidence.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

pub const MAX_CANONICAL_PROMPT_CANDIDATES_V1: usize = 128;
pub const CANONICAL_NO_INTERVENTION_ID_V1: &str = "prompt:no-intervention";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptAuthenticationErrorV1 {
    Rejected,
}

/// Authenticates an exact prompt-registry owner view before enumeration.
///
/// Implementations are expected to verify producer identity, scope, freshness,
/// revocation state and host-owned signature or transport evidence. Returning
/// `Ok(())` admits the exact `source_digest`, not an arbitrary caller claim.
pub trait PromptCandidateSourceAuthenticatorV1 {
    fn authenticate_candidate_source(
        &self,
        source: &PromptCandidateSourceV1,
        objective_digest: Digest32,
        now_unix_ms: u64,
    ) -> Result<(), PromptAuthenticationErrorV1>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptModelProfileV1 {
    pub model_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub template_digest: Digest32,
    pub tool_schema_digest: Digest32,
    pub locale_id: StableId,
}

impl PromptModelProfileV1 {
    pub fn validate(&self) -> Result<(), CanonicalPromptErrorV1> {
        for (label, digest) in [
            ("model", self.model_digest),
            ("tokenizer", self.tokenizer_digest),
            ("template", self.template_digest),
            ("tool schema", self.tool_schema_digest),
        ] {
            require_digest(digest, label)?;
        }
        Ok(())
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.prompt-optimizer.model-profile.v1".to_vec();
        for digest in [
            self.model_digest,
            self.tokenizer_digest,
            self.template_digest,
            self.tool_schema_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        push_id(&mut bytes, &self.locale_id);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateBindingV1 {
    pub candidate_id: StableId,
    pub factor_id: StableId,
    pub realization_id: StableId,
    pub payload_digest: Digest32,
    pub admission_digest: Digest32,
    pub support_digest: Digest32,
    pub token_cost: u64,
    pub expires_unix_ms: Option<u64>,
    pub binding_digest: Digest32,
}

impl PromptCandidateBindingV1 {
    #[must_use]
    pub fn compute_binding_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.prompt-optimizer.candidate-binding.v1".to_vec();
        push_id(&mut bytes, &self.candidate_id);
        push_id(&mut bytes, &self.factor_id);
        push_id(&mut bytes, &self.realization_id);
        for digest in [
            self.payload_digest,
            self.admission_digest,
            self.support_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.token_cost.to_be_bytes());
        push_optional_u64(&mut bytes, self.expires_unix_ms);
        Digest32::of_bytes(&bytes)
    }

    pub(super) fn validate(&self, now_unix_ms: u64) -> Result<(), CanonicalPromptErrorV1> {
        for (label, digest) in [
            ("candidate payload", self.payload_digest),
            ("candidate admission", self.admission_digest),
            ("candidate support", self.support_digest),
            ("candidate binding", self.binding_digest),
        ] {
            require_digest(digest, label)?;
        }
        if self.token_cost == 0 {
            return Err(CanonicalPromptErrorV1::InvalidTokenCost(
                self.candidate_id.to_string(),
            ));
        }
        if self.expires_unix_ms.is_some_and(|expires| now_unix_ms >= expires) {
            return Err(CanonicalPromptErrorV1::ExpiredCandidate(
                self.candidate_id.to_string(),
            ));
        }
        if self.binding_digest != self.compute_binding_digest() {
            return Err(CanonicalPromptErrorV1::DigestMismatch("candidate binding"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateSourceV1 {
    pub owner_id: StableId,
    pub registry_snapshot_digest: Digest32,
    pub registry_revision: u64,
    pub revocation_frontier: u64,
    pub generation_vector_digest: Digest32,
    pub model_profile: PromptModelProfileV1,
    pub bindings: Vec<PromptCandidateBindingV1>,
    pub omitted_count: u32,
    pub source_digest: Digest32,
}

impl PromptCandidateSourceV1 {
    #[must_use]
    pub fn compute_source_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.prompt-optimizer.candidate-source.v1".to_vec();
        push_id(&mut bytes, &self.owner_id);
        bytes.extend_from_slice(self.registry_snapshot_digest.as_array());
        bytes.extend_from_slice(&self.registry_revision.to_be_bytes());
        bytes.extend_from_slice(&self.revocation_frontier.to_be_bytes());
        bytes.extend_from_slice(self.generation_vector_digest.as_array());
        bytes.extend_from_slice(self.model_profile.digest().as_array());
        push_len(&mut bytes, self.bindings.len());
        for binding in &self.bindings {
            bytes.extend_from_slice(binding.binding_digest.as_array());
        }
        bytes.extend_from_slice(&self.omitted_count.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }

    pub fn validate_at(&self, now_unix_ms: u64) -> Result<(), CanonicalPromptErrorV1> {
        if self.owner_id.as_str() != "prompt.registry" {
            return Err(CanonicalPromptErrorV1::InvalidSourceOwner);
        }
        if self.registry_revision == 0 || self.revocation_frontier > self.registry_revision {
            return Err(CanonicalPromptErrorV1::InvalidRegistryFrontier);
        }
        if self.bindings.len() > MAX_CANONICAL_PROMPT_CANDIDATES_V1 {
            return Err(CanonicalPromptErrorV1::CandidateLimitExceeded);
        }
        for (label, digest) in [
            ("registry snapshot", self.registry_snapshot_digest),
            ("generation vector", self.generation_vector_digest),
            ("candidate source", self.source_digest),
        ] {
            require_digest(digest, label)?;
        }
        self.model_profile.validate()?;
        let mut candidate_ids = BTreeSet::new();
        let mut realization_ids = BTreeSet::new();
        for binding in &self.bindings {
            binding.validate(now_unix_ms)?;
            if !candidate_ids.insert(binding.candidate_id.clone()) {
                return Err(CanonicalPromptErrorV1::DuplicateCandidate(
                    binding.candidate_id.to_string(),
                ));
            }
            if !realization_ids.insert(binding.realization_id.clone()) {
                return Err(CanonicalPromptErrorV1::DuplicateRealization(
                    binding.realization_id.to_string(),
                ));
            }
        }
        if self
            .bindings
            .windows(2)
            .any(|pair| pair[0].candidate_id >= pair[1].candidate_id)
        {
            return Err(CanonicalPromptErrorV1::NonCanonicalCandidateOrder);
        }
        if self.source_digest != self.compute_source_digest() {
            return Err(CanonicalPromptErrorV1::DigestMismatch("candidate source"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateEnumerationRequestV1 {
    pub enumeration_id: StableId,
    pub objective_digest: Digest32,
    pub state_digest: Digest32,
    pub maximum_candidates: usize,
    pub now_unix_ms: u64,
    pub source: PromptCandidateSourceV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateSetReceiptV1 {
    pub enumeration_id: StableId,
    pub objective_digest: Digest32,
    pub state_digest: Digest32,
    pub registry_snapshot_digest: Digest32,
    pub registry_revision: u64,
    pub revocation_frontier: u64,
    pub generation_vector_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub source_digest: Digest32,
    pub no_intervention_arm_id: StableId,
    pub candidates: Vec<PromptCandidateBindingV1>,
    pub omitted_count_bound: u32,
    pub candidate_set_digest: Digest32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl PromptCandidateSetReceiptV1 {
    pub fn validate(&self, now_unix_ms: u64) -> Result<(), CanonicalPromptErrorV1> {
        if now_unix_ms == 0 || self.authority.grants_any() {
            return Err(CanonicalPromptErrorV1::InvalidReceipt);
        }
        if self.registry_revision == 0
            || self.revocation_frontier > self.registry_revision
            || self.candidates.len() > MAX_CANONICAL_PROMPT_CANDIDATES_V1
            || self.no_intervention_arm_id.as_str() != CANONICAL_NO_INTERVENTION_ID_V1
        {
            return Err(CanonicalPromptErrorV1::InvalidReceipt);
        }
        for (label, digest) in [
            ("objective", self.objective_digest),
            ("state", self.state_digest),
            ("registry snapshot", self.registry_snapshot_digest),
            ("generation vector", self.generation_vector_digest),
            ("model profile", self.model_profile_digest),
            ("candidate source", self.source_digest),
            ("candidate set", self.candidate_set_digest),
            ("candidate receipt", self.receipt_digest),
        ] {
            require_digest(digest, label)?;
        }
        let mut ids = BTreeSet::new();
        for candidate in &self.candidates {
            candidate.validate(now_unix_ms)?;
            if !ids.insert(candidate.candidate_id.clone()) {
                return Err(CanonicalPromptErrorV1::DuplicateCandidate(
                    candidate.candidate_id.to_string(),
                ));
            }
        }
        if self
            .candidates
            .windows(2)
            .any(|pair| pair[0].candidate_id >= pair[1].candidate_id)
        {
            return Err(CanonicalPromptErrorV1::NonCanonicalCandidateOrder);
        }
        if self.candidate_set_digest != compute_candidate_set_digest(self) {
            return Err(CanonicalPromptErrorV1::DigestMismatch("candidate set"));
        }
        if self.receipt_digest != compute_candidate_receipt_digest(self) {
            return Err(CanonicalPromptErrorV1::DigestMismatch("candidate receipt"));
        }
        Ok(())
    }
}

pub fn enumerate_factors_v1<A: PromptCandidateSourceAuthenticatorV1>(
    request: PromptCandidateEnumerationRequestV1,
    authenticator: &A,
) -> Result<PromptCandidateSetReceiptV1, CanonicalPromptErrorV1> {
    require_digest(request.objective_digest, "objective")?;
    require_digest(request.state_digest, "state")?;
    if request.now_unix_ms == 0
        || request.maximum_candidates == 0
        || request.maximum_candidates > MAX_CANONICAL_PROMPT_CANDIDATES_V1
    {
        return Err(CanonicalPromptErrorV1::InvalidEnumerationBound);
    }
    request.source.validate_at(request.now_unix_ms)?;
    authenticator
        .authenticate_candidate_source(
            &request.source,
            request.objective_digest,
            request.now_unix_ms,
        )
        .map_err(|_| CanonicalPromptErrorV1::SourceAuthenticationRejected)?;

    let retained = request.source.bindings.len().min(request.maximum_candidates);
    let local_omitted = request.source.bindings.len().saturating_sub(retained);
    let omitted_count_bound = request
        .source
        .omitted_count
        .checked_add(u32::try_from(local_omitted).map_err(|_| CanonicalPromptErrorV1::Arithmetic)?)
        .ok_or(CanonicalPromptErrorV1::Arithmetic)?;
    let no_intervention_arm_id = StableId::new(CANONICAL_NO_INTERVENTION_ID_V1)
        .map_err(|_| CanonicalPromptErrorV1::InternalInvariant)?;
    let mut receipt = PromptCandidateSetReceiptV1 {
        enumeration_id: request.enumeration_id,
        objective_digest: request.objective_digest,
        state_digest: request.state_digest,
        registry_snapshot_digest: request.source.registry_snapshot_digest,
        registry_revision: request.source.registry_revision,
        revocation_frontier: request.source.revocation_frontier,
        generation_vector_digest: request.source.generation_vector_digest,
        model_profile_digest: request.source.model_profile.digest(),
        source_digest: request.source.source_digest,
        no_intervention_arm_id,
        candidates: request.source.bindings[..retained].to_vec(),
        omitted_count_bound,
        candidate_set_digest: Digest32::ZERO,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.candidate_set_digest = compute_candidate_set_digest(&receipt);
    receipt.receipt_digest = compute_candidate_receipt_digest(&receipt);
    receipt.validate(request.now_unix_ms)?;
    Ok(receipt)
}

pub(super) fn compute_candidate_set_digest(receipt: &PromptCandidateSetReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.candidate-set.v1".to_vec();
    push_id(&mut bytes, &receipt.no_intervention_arm_id);
    push_len(&mut bytes, receipt.candidates.len());
    for candidate in &receipt.candidates {
        bytes.extend_from_slice(candidate.binding_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn compute_candidate_receipt_digest(receipt: &PromptCandidateSetReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.candidate-receipt.v1".to_vec();
    push_id(&mut bytes, &receipt.enumeration_id);
    for digest in [
        receipt.objective_digest,
        receipt.state_digest,
        receipt.registry_snapshot_digest,
        receipt.generation_vector_digest,
        receipt.model_profile_digest,
        receipt.source_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&receipt.registry_revision.to_be_bytes());
    bytes.extend_from_slice(&receipt.revocation_frontier.to_be_bytes());
    push_id(&mut bytes, &receipt.no_intervention_arm_id);
    bytes.extend_from_slice(&receipt.omitted_count_bound.to_be_bytes());
    bytes.extend_from_slice(receipt.candidate_set_digest.as_array());
    Digest32::of_bytes(&bytes)
}

pub(super) fn require_digest(
    digest: Digest32,
    label: &'static str,
) -> Result<(), CanonicalPromptErrorV1> {
    if digest.is_zero() {
        return Err(CanonicalPromptErrorV1::EmptyDigest(label));
    }
    Ok(())
}

pub(super) fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

pub(super) fn push_len(bytes: &mut Vec<u8>, value: usize) {
    bytes.extend_from_slice(&u64::try_from(value).unwrap_or(u64::MAX).to_be_bytes());
}

fn push_optional_u64(bytes: &mut Vec<u8>, value: Option<u64>) {
    match value {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        None => bytes.push(0),
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CanonicalPromptErrorV1 {
    EmptyDigest(&'static str),
    InvalidSourceOwner,
    InvalidRegistryFrontier,
    CandidateLimitExceeded,
    InvalidEnumerationBound,
    DuplicateCandidate(String),
    DuplicateRealization(String),
    NonCanonicalCandidateOrder,
    InvalidTokenCost(String),
    ExpiredCandidate(String),
    SourceAuthenticationRejected,
    PricingAuthenticationRejected,
    UnknownCandidate(String),
    DuplicateEvidence(String),
    EvidenceContextMismatch(String),
    InvalidConfidence(String),
    InvalidEvidenceWindow(String),
    NegativeCost,
    DigestMismatch(&'static str),
    InvalidReceipt,
    Arithmetic,
    InternalInvariant,
}

impl fmt::Display for CanonicalPromptErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CanonicalPromptErrorV1 {}

#[cfg(test)]
#[path = "canonical_v1_tests.rs"]
mod tests;
