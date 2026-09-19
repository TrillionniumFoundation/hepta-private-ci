//! Verified end-to-end V2 context closure.
//!
//! This module is the normative security path layered over the legacy V2
//! selection engine. It requires injected owner verification for admission and
//! attachment-time freshness, tokenizes the actual serialized payload bytes,
//! proves that every selected content digest is realized in those bytes, and
//! accepts delivery only from an injected provider/transport evidence verifier.
//! The legacy V2 helpers remain compatibility surfaces only.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CompiledContextV2;
use crate::ContextCandidateV2;
use crate::ContextCompilationRequestV2;
use crate::ContextDeliveryDispositionV2;
use crate::ContextModelProfileV2;
use crate::ContextRoleV2;
use crate::MandatoryContextGroupV2;
use crate::compile_v2;

const ADMISSION_MANIFEST_DOMAIN: &[u8] = b"hepta.context-admission-manifest.v2";
const MANDATORY_GROUPS_DOMAIN: &[u8] = b"hepta.context-mandatory-groups.v2";
const VERIFIED_COMPILATION_DOMAIN: &[u8] = b"hepta.context-verified-compilation.v2";
const VERIFIED_SERIALIZATION_DOMAIN: &[u8] = b"hepta.context-verified-serialization.v2";
const ATTACHMENT_REVALIDATION_DOMAIN: &[u8] = b"hepta.context-attachment-revalidation.v2";
const VERIFIED_ATTACHMENT_DOMAIN: &[u8] = b"hepta.context-verified-attachment.v2";
const VERIFIED_DELIVERY_DOMAIN: &[u8] = b"hepta.context-verified-delivery.v2";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedAdmissionEvidenceV2 {
    pub item_id: StableId,
    pub role: ContextRoleV2,
    pub content_digest: Digest32,
    pub source_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub admission_receipt_digest: Digest32,
    pub owner_snapshot_digest: Digest32,
    pub revocation_frontier_digest: Digest32,
    pub expires_unix_ms: u64,
    pub active: bool,
}

pub trait ContextAdmissionVerifierV2 {
    /// Resolve the current authoritative admission state for exactly this item.
    ///
    /// Implementations are trusted owner adapters. A digest supplied by the
    /// compilation caller is not sufficient evidence.
    fn verify_current(
        &self,
        candidate: &ContextCandidateV2,
        now_unix_ms: u64,
    ) -> Result<VerifiedAdmissionEvidenceV2, ContextClosureErrorV2>;
}

pub trait ExactContextTokenizerV2 {
    fn tokenizer_digest(&self) -> Digest32;
    fn count_tokens(&self, payload: &[u8]) -> Result<u64, ContextClosureErrorV2>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SerializedContextSegmentV2 {
    pub item_id: StableId,
    pub start: usize,
    pub end: usize,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedCompiledContextV2 {
    pub compiled: CompiledContextV2,
    pub admission_evidence: Vec<VerifiedAdmissionEvidenceV2>,
    pub admission_manifest_digest: Digest32,
    pub mandatory_groups_digest: Digest32,
    pub verified_compilation_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedContextSerializationV2 {
    pub serialization_id: StableId,
    pub verified_compilation_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub selected_item_ids: Vec<StableId>,
    pub payload_digest: Digest32,
    pub serialized_token_count: u64,
    pub segment_manifest_digest: Digest32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AttachmentRevalidationReceiptV2 {
    pub revalidation_id: StableId,
    pub verified_compilation_digest: Digest32,
    pub current_admission_manifest_digest: Digest32,
    pub revalidated_unix_ms: u64,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedContextAttachmentV2 {
    pub attachment_id: StableId,
    pub verified_compilation_digest: Digest32,
    pub serialization_receipt_digest: Digest32,
    pub revalidation_receipt_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub payload_digest: Digest32,
    pub selected_item_ids: Vec<StableId>,
    pub attachment_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderDeliveryEvidenceV2 {
    pub provider_request_id: StableId,
    pub transport_receipt_digest: Digest32,
    pub payload_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub terminal_observed: bool,
    pub disposition: ContextDeliveryDispositionV2,
    pub observed_unix_ms: u64,
}

pub trait ProviderDeliveryEvidenceVerifierV2 {
    /// Read provider/transport truth for this exact attachment.
    ///
    /// Implementations must resolve a real transport/provider record. The
    /// caller cannot upgrade an arbitrary boolean/digest pair into delivery.
    fn verify_delivery(
        &self,
        attachment: &VerifiedContextAttachmentV2,
    ) -> Result<ProviderDeliveryEvidenceV2, ContextClosureErrorV2>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedContextDeliveryReceiptV2 {
    pub observation_id: StableId,
    pub attachment_digest: Digest32,
    pub provider_request_id: StableId,
    pub transport_receipt_digest: Digest32,
    pub payload_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub terminal_observed: bool,
    pub disposition: ContextDeliveryDispositionV2,
    pub observed_unix_ms: u64,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

pub fn compile_verified_v2(
    request: ContextCompilationRequestV2,
    admission_verifier: &impl ContextAdmissionVerifierV2,
    now_unix_ms: u64,
) -> Result<VerifiedCompiledContextV2, ContextClosureErrorV2> {
    if now_unix_ms == 0 {
        return Err(ContextClosureErrorV2::InvalidTime);
    }
    let mandatory_groups_digest = digest_mandatory_groups(&request.mandatory_groups)?;
    let mut evidence = Vec::with_capacity(request.candidates.len());
    for candidate in &request.candidates {
        let current = admission_verifier.verify_current(candidate, now_unix_ms)?;
        validate_admission(candidate, &current, now_unix_ms)?;
        evidence.push(current);
    }
    evidence.sort_by(|left, right| left.item_id.cmp(&right.item_id));
    let admission_manifest_digest = digest_admission_manifest(&evidence);
    let compiled = compile_v2(request).map_err(ContextClosureErrorV2::Compilation)?;
    let selected = compiled
        .receipt
        .selected_item_ids
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>();
    let selected_evidence = evidence
        .iter()
        .filter(|entry| selected.contains(&entry.item_id))
        .cloned()
        .collect::<Vec<_>>();
    let selected_admission_digest = digest_admission_manifest(&selected_evidence);

    let verified_compilation_digest = digest_verified_compilation(
        compiled.receipt.receipt_digest,
        selected_admission_digest,
        mandatory_groups_digest,
    );
    Ok(VerifiedCompiledContextV2 {
        compiled,
        admission_evidence: selected_evidence,
        admission_manifest_digest: selected_admission_digest,
        mandatory_groups_digest,
        verified_compilation_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn record_verified_serialization_v2(
    compiled: &VerifiedCompiledContextV2,
    model_profile: &ContextModelProfileV2,
    serialization_id: StableId,
    payload: &[u8],
    segments: &[SerializedContextSegmentV2],
    tokenizer: &impl ExactContextTokenizerV2,
) -> Result<VerifiedContextSerializationV2, ContextClosureErrorV2> {
    compiled
        .compiled
        .validate()
        .map_err(ContextClosureErrorV2::Compilation)?;
    model_profile
        .validate()
        .map_err(ContextClosureErrorV2::Compilation)?;
    if model_profile.digest() != compiled.compiled.receipt.model_profile_digest {
        return Err(ContextClosureErrorV2::ModelProfileMismatch);
    }
    if tokenizer.tokenizer_digest() != model_profile.tokenizer_digest {
        return Err(ContextClosureErrorV2::TokenizerMismatch);
    }
    if payload.is_empty() {
        return Err(ContextClosureErrorV2::EmptyPayload);
    }

    let mut seen = BTreeSet::new();
    let mut previous_end = 0usize;
    for segment in segments {
        if segment.start >= segment.end || segment.end > payload.len() || segment.start < previous_end {
            return Err(ContextClosureErrorV2::InvalidSegmentRange(segment.item_id.to_string()));
        }
        if !seen.insert(segment.item_id.clone()) {
            return Err(ContextClosureErrorV2::DuplicateSerializedItem(segment.item_id.to_string()));
        }
        let Some(candidate) = compiled
            .compiled
            .selected_candidates
            .iter()
            .find(|candidate| candidate.item_id == segment.item_id)
        else {
            return Err(ContextClosureErrorV2::UnknownSerializedItem(segment.item_id.to_string()));
        };
        if Digest32::of_bytes(&payload[segment.start..segment.end]) != candidate.content_digest {
            return Err(ContextClosureErrorV2::SerializedContentMismatch(segment.item_id.to_string()));
        }
        previous_end = segment.end;
    }
    let expected_ids = compiled
        .compiled
        .receipt
        .selected_item_ids
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>();
    if seen != expected_ids {
        return Err(ContextClosureErrorV2::SerializedSelectionMismatch);
    }

    let serialized_token_count = tokenizer.count_tokens(payload)?;
    if serialized_token_count == 0
        || serialized_token_count > compiled.compiled.receipt.token_upper_bound
        || serialized_token_count > model_profile.maximum_context_tokens
    {
        return Err(ContextClosureErrorV2::FinalPayloadTokenBudgetExceeded {
            actual_tokens: serialized_token_count,
            token_budget: compiled.compiled.receipt.token_upper_bound,
        });
    }
    let payload_digest = Digest32::of_bytes(payload);
    let segment_manifest_digest = digest_segments(segments);
    let receipt_digest = digest_verified_serialization(
        &serialization_id,
        compiled.verified_compilation_digest,
        model_profile.digest(),
        tokenizer.tokenizer_digest(),
        &compiled.compiled.receipt.selected_item_ids,
        payload_digest,
        serialized_token_count,
        segment_manifest_digest,
    );
    Ok(VerifiedContextSerializationV2 {
        serialization_id,
        verified_compilation_digest: compiled.verified_compilation_digest,
        model_profile_digest: model_profile.digest(),
        tokenizer_digest: tokenizer.tokenizer_digest(),
        selected_item_ids: compiled.compiled.receipt.selected_item_ids.clone(),
        payload_digest,
        serialized_token_count,
        segment_manifest_digest,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn build_revalidated_attachment_v2(
    compiled: &VerifiedCompiledContextV2,
    serialization: &VerifiedContextSerializationV2,
    attachment_id: StableId,
    revalidation_id: StableId,
    admission_verifier: &impl ContextAdmissionVerifierV2,
    now_unix_ms: u64,
) -> Result<(VerifiedContextAttachmentV2, AttachmentRevalidationReceiptV2), ContextClosureErrorV2> {
    if now_unix_ms == 0 {
        return Err(ContextClosureErrorV2::InvalidTime);
    }
    if serialization.verified_compilation_digest != compiled.verified_compilation_digest
        || serialization.selected_item_ids != compiled.compiled.receipt.selected_item_ids
    {
        return Err(ContextClosureErrorV2::SerializationBindingMismatch);
    }

    let mut current = Vec::with_capacity(compiled.compiled.selected_candidates.len());
    for candidate in &compiled.compiled.selected_candidates {
        let evidence = admission_verifier.verify_current(candidate, now_unix_ms)?;
        validate_admission(candidate, &evidence, now_unix_ms)?;
        current.push(evidence);
    }
    current.sort_by(|left, right| left.item_id.cmp(&right.item_id));
    let current_admission_manifest_digest = digest_admission_manifest(&current);
    let revalidation_receipt_digest = digest_attachment_revalidation(
        &revalidation_id,
        compiled.verified_compilation_digest,
        current_admission_manifest_digest,
        now_unix_ms,
    );
    let revalidation = AttachmentRevalidationReceiptV2 {
        revalidation_id,
        verified_compilation_digest: compiled.verified_compilation_digest,
        current_admission_manifest_digest,
        revalidated_unix_ms: now_unix_ms,
        receipt_digest: revalidation_receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    };
    let attachment_digest = digest_verified_attachment(
        &attachment_id,
        compiled.verified_compilation_digest,
        serialization.receipt_digest,
        revalidation.receipt_digest,
        serialization.model_profile_digest,
        serialization.payload_digest,
        &serialization.selected_item_ids,
    );
    let attachment = VerifiedContextAttachmentV2 {
        attachment_id,
        verified_compilation_digest: compiled.verified_compilation_digest,
        serialization_receipt_digest: serialization.receipt_digest,
        revalidation_receipt_digest: revalidation.receipt_digest,
        model_profile_digest: serialization.model_profile_digest,
        payload_digest: serialization.payload_digest,
        selected_item_ids: serialization.selected_item_ids.clone(),
        attachment_digest,
        authority: AuthorityPosture::DENY_ALL,
    };
    Ok((attachment, revalidation))
}

pub fn observe_verified_delivery_v2(
    attachment: &VerifiedContextAttachmentV2,
    observation_id: StableId,
    verifier: &impl ProviderDeliveryEvidenceVerifierV2,
) -> Result<VerifiedContextDeliveryReceiptV2, ContextClosureErrorV2> {
    let evidence = verifier.verify_delivery(attachment)?;
    ensure_digest(evidence.transport_receipt_digest, "transport_receipt")?;
    if evidence.payload_digest != attachment.payload_digest
        || evidence.model_profile_digest != attachment.model_profile_digest
    {
        return Err(ContextClosureErrorV2::ProviderEvidenceMismatch);
    }
    match evidence.disposition {
        ContextDeliveryDispositionV2::Delivered => {
            if !evidence.terminal_observed {
                return Err(ContextClosureErrorV2::ProviderEvidenceNotTerminal);
            }
        }
        ContextDeliveryDispositionV2::Rejected => {
            if !evidence.terminal_observed {
                return Err(ContextClosureErrorV2::ProviderEvidenceNotTerminal);
            }
        }
        ContextDeliveryDispositionV2::Indeterminate => {
            if evidence.terminal_observed {
                return Err(ContextClosureErrorV2::InvalidProviderDisposition);
            }
        }
    }
    if evidence.observed_unix_ms == 0 {
        return Err(ContextClosureErrorV2::InvalidTime);
    }
    let receipt_digest = digest_verified_delivery(
        &observation_id,
        attachment.attachment_digest,
        &evidence.provider_request_id,
        evidence.transport_receipt_digest,
        evidence.payload_digest,
        evidence.model_profile_digest,
        evidence.terminal_observed,
        evidence.disposition,
        evidence.observed_unix_ms,
    );
    Ok(VerifiedContextDeliveryReceiptV2 {
        observation_id,
        attachment_digest: attachment.attachment_digest,
        provider_request_id: evidence.provider_request_id,
        transport_receipt_digest: evidence.transport_receipt_digest,
        payload_digest: evidence.payload_digest,
        model_profile_digest: evidence.model_profile_digest,
        terminal_observed: evidence.terminal_observed,
        disposition: evidence.disposition,
        observed_unix_ms: evidence.observed_unix_ms,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn validate_admission(
    candidate: &ContextCandidateV2,
    evidence: &VerifiedAdmissionEvidenceV2,
    now_unix_ms: u64,
) -> Result<(), ContextClosureErrorV2> {
    for (digest, name) in [
        (evidence.content_digest, "admission_content"),
        (evidence.source_digest, "admission_source"),
        (evidence.generation_vector_digest, "admission_generation"),
        (evidence.admission_receipt_digest, "admission_receipt"),
        (evidence.owner_snapshot_digest, "admission_owner_snapshot"),
        (evidence.revocation_frontier_digest, "admission_revocation_frontier"),
    ] {
        ensure_digest(digest, name)?;
    }
    if evidence.item_id != candidate.item_id
        || evidence.role != candidate.role
        || evidence.content_digest != candidate.content_digest
        || evidence.source_digest != candidate.source_digest
        || evidence.generation_vector_digest != candidate.generation_vector_digest
    {
        return Err(ContextClosureErrorV2::AdmissionSubjectMismatch(candidate.item_id.to_string()));
    }
    if !evidence.active || evidence.expires_unix_ms < now_unix_ms {
        return Err(ContextClosureErrorV2::AdmissionStaleOrRevoked(candidate.item_id.to_string()));
    }
    match candidate.role {
        ContextRoleV2::TrustedInstruction | ContextRoleV2::Schema => {
            if candidate.trusted_admission_digest != Some(evidence.admission_receipt_digest) {
                return Err(ContextClosureErrorV2::AdmissionReceiptMismatch(candidate.item_id.to_string()));
            }
        }
        ContextRoleV2::UntrustedEvidence => {
            if candidate.trusted_admission_digest.is_some() {
                return Err(ContextClosureErrorV2::AdmissionRoleConfusion(candidate.item_id.to_string()));
            }
        }
    }
    Ok(())
}

fn digest_mandatory_groups(groups: &[MandatoryContextGroupV2]) -> Result<Digest32, ContextClosureErrorV2> {
    let mut normalized = groups.to_vec();
    normalized.sort_by(|left, right| left.group_id.cmp(&right.group_id));
    let mut bytes = MANDATORY_GROUPS_DOMAIN.to_vec();
    push_len(&mut bytes, normalized.len());
    for group in normalized {
        ensure_digest(group.reason_digest, "mandatory_group_reason")?;
        push_id(&mut bytes, &group.group_id);
        let mut ids = group.item_ids;
        ids.sort();
        push_ids(&mut bytes, &ids);
        push_digest(&mut bytes, group.reason_digest);
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_admission_manifest(evidence: &[VerifiedAdmissionEvidenceV2]) -> Digest32 {
    let mut bytes = ADMISSION_MANIFEST_DOMAIN.to_vec();
    push_len(&mut bytes, evidence.len());
    for entry in evidence {
        push_id(&mut bytes, &entry.item_id);
        bytes.push(role_code(entry.role));
        for digest in [
            entry.content_digest,
            entry.source_digest,
            entry.generation_vector_digest,
            entry.admission_receipt_digest,
            entry.owner_snapshot_digest,
            entry.revocation_frontier_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_u64(&mut bytes, entry.expires_unix_ms);
        bytes.push(u8::from(entry.active));
    }
    Digest32::of_bytes(&bytes)
}

fn digest_segments(segments: &[SerializedContextSegmentV2]) -> Digest32 {
    let mut bytes = b"hepta.context-serialized-segments.v2".to_vec();
    push_len(&mut bytes, segments.len());
    for segment in segments {
        push_id(&mut bytes, &segment.item_id);
        push_u64(&mut bytes, u64::try_from(segment.start).unwrap_or(u64::MAX));
        push_u64(&mut bytes, u64::try_from(segment.end).unwrap_or(u64::MAX));
    }
    Digest32::of_bytes(&bytes)
}

fn digest_verified_compilation(base: Digest32, admissions: Digest32, groups: Digest32) -> Digest32 {
    let mut bytes = VERIFIED_COMPILATION_DOMAIN.to_vec();
    push_digest(&mut bytes, base);
    push_digest(&mut bytes, admissions);
    push_digest(&mut bytes, groups);
    Digest32::of_bytes(&bytes)
}

#[allow(clippy::too_many_arguments)]
fn digest_verified_serialization(
    serialization_id: &StableId,
    verified_compilation: Digest32,
    model_profile: Digest32,
    tokenizer: Digest32,
    selected_ids: &[StableId],
    payload: Digest32,
    token_count: u64,
    segments: Digest32,
) -> Digest32 {
    let mut bytes = VERIFIED_SERIALIZATION_DOMAIN.to_vec();
    push_id(&mut bytes, serialization_id);
    push_digest(&mut bytes, verified_compilation);
    push_digest(&mut bytes, model_profile);
    push_digest(&mut bytes, tokenizer);
    push_ids(&mut bytes, selected_ids);
    push_digest(&mut bytes, payload);
    push_u64(&mut bytes, token_count);
    push_digest(&mut bytes, segments);
    Digest32::of_bytes(&bytes)
}

fn digest_attachment_revalidation(
    revalidation_id: &StableId,
    verified_compilation: Digest32,
    admissions: Digest32,
    now: u64,
) -> Digest32 {
    let mut bytes = ATTACHMENT_REVALIDATION_DOMAIN.to_vec();
    push_id(&mut bytes, revalidation_id);
    push_digest(&mut bytes, verified_compilation);
    push_digest(&mut bytes, admissions);
    push_u64(&mut bytes, now);
    Digest32::of_bytes(&bytes)
}

#[allow(clippy::too_many_arguments)]
fn digest_verified_attachment(
    attachment_id: &StableId,
    verified_compilation: Digest32,
    serialization: Digest32,
    revalidation: Digest32,
    model_profile: Digest32,
    payload: Digest32,
    selected_ids: &[StableId],
) -> Digest32 {
    let mut bytes = VERIFIED_ATTACHMENT_DOMAIN.to_vec();
    push_id(&mut bytes, attachment_id);
    push_digest(&mut bytes, verified_compilation);
    push_digest(&mut bytes, serialization);
    push_digest(&mut bytes, revalidation);
    push_digest(&mut bytes, model_profile);
    push_digest(&mut bytes, payload);
    push_ids(&mut bytes, selected_ids);
    Digest32::of_bytes(&bytes)
}

#[allow(clippy::too_many_arguments)]
fn digest_verified_delivery(
    observation_id: &StableId,
    attachment: Digest32,
    provider_request_id: &StableId,
    transport_receipt: Digest32,
    payload: Digest32,
    model_profile: Digest32,
    terminal: bool,
    disposition: ContextDeliveryDispositionV2,
    observed_unix_ms: u64,
) -> Digest32 {
    let mut bytes = VERIFIED_DELIVERY_DOMAIN.to_vec();
    push_id(&mut bytes, observation_id);
    push_digest(&mut bytes, attachment);
    push_id(&mut bytes, provider_request_id);
    push_digest(&mut bytes, transport_receipt);
    push_digest(&mut bytes, payload);
    push_digest(&mut bytes, model_profile);
    bytes.push(u8::from(terminal));
    bytes.push(match disposition {
        ContextDeliveryDispositionV2::Delivered => 0,
        ContextDeliveryDispositionV2::Rejected => 1,
        ContextDeliveryDispositionV2::Indeterminate => 2,
    });
    push_u64(&mut bytes, observed_unix_ms);
    Digest32::of_bytes(&bytes)
}

fn ensure_digest(digest: Digest32, name: &'static str) -> Result<(), ContextClosureErrorV2> {
    if digest.is_zero() {
        return Err(ContextClosureErrorV2::EmptyDigest(name));
    }
    Ok(())
}

fn push_ids(bytes: &mut Vec<u8>, values: &[StableId]) {
    push_len(bytes, values.len());
    for value in values {
        push_id(bytes, value);
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len());
    bytes.extend_from_slice(raw);
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    push_u64(bytes, u64::try_from(value).unwrap_or(u64::MAX));
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

const fn role_code(role: ContextRoleV2) -> u8 {
    match role {
        ContextRoleV2::TrustedInstruction => 0,
        ContextRoleV2::Schema => 1,
        ContextRoleV2::UntrustedEvidence => 2,
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ContextClosureErrorV2 {
    Compilation(crate::ContextCompilerV2Error),
    EmptyDigest(&'static str),
    InvalidTime,
    AdmissionSubjectMismatch(String),
    AdmissionStaleOrRevoked(String),
    AdmissionReceiptMismatch(String),
    AdmissionRoleConfusion(String),
    ModelProfileMismatch,
    TokenizerMismatch,
    EmptyPayload,
    InvalidSegmentRange(String),
    DuplicateSerializedItem(String),
    UnknownSerializedItem(String),
    SerializedContentMismatch(String),
    SerializedSelectionMismatch,
    FinalPayloadTokenBudgetExceeded { actual_tokens: u64, token_budget: u64 },
    SerializationBindingMismatch,
    ProviderEvidenceMismatch,
    ProviderEvidenceNotTerminal,
    InvalidProviderDisposition,
    TokenizerFailure(String),
    AdmissionUnavailable(String),
    ProviderEvidenceUnavailable(String),
}

impl fmt::Display for ContextClosureErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ContextClosureErrorV2 {}

#[cfg(test)]
#[path = "verified_tests.rs"]
mod tests;
