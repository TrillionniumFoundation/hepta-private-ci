//! Exact-profile, generation-bound context compilation and delivery receipts.
//!
//! This module keeps trusted instructions, schemas and untrusted evidence in
//! distinct roles; binds every candidate to one Lane C generation vector; binds
//! token counts to the exact tokenizer; preserves mandatory groups atomically;
//! selects optional evidence by deterministic value-per-token; and emits a
//! compilation -> serialization -> attachment -> terminal-delivery digest chain.
//! It has no model client or provider authority.

use std::cmp::Ordering;
use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

pub const MAX_CONTEXT_CANDIDATES_V2: usize = 4_096;
pub const MAX_CONTEXT_GROUPS_V2: usize = 256;
pub const MAX_CONTEXT_TOKENS_V2: u64 = 1_000_000;
const TOKENIZATION_DOMAIN: &[u8] = b"hepta.context-tokenization.v2";
const MODEL_PROFILE_DOMAIN: &[u8] = b"hepta.context-model-profile.v2";
const CANDIDATE_SET_DOMAIN: &[u8] = b"hepta.context-candidate-set.v2";
const CONTEXT_DOMAIN: &[u8] = b"hepta.context-compilation.v2";
const COMPILATION_RECEIPT_DOMAIN: &[u8] = b"hepta.context-compilation-receipt.v2";
const SERIALIZATION_DOMAIN: &[u8] = b"hepta.context-serialization.v2";
const ATTACHMENT_DOMAIN: &[u8] = b"hepta.context-attachment.v2";
const DELIVERY_DOMAIN: &[u8] = b"hepta.context-delivery-observation.v2";

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum ContextRoleV2 {
    TrustedInstruction,
    Schema,
    UntrustedEvidence,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TokenizationReceiptV2 {
    pub item_id: StableId,
    pub content_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub token_count: u64,
    pub receipt_digest: Digest32,
}

impl TokenizationReceiptV2 {
    pub fn new(
        item_id: StableId,
        content_digest: Digest32,
        tokenizer_digest: Digest32,
        token_count: u64,
    ) -> Result<Self, ContextCompilerV2Error> {
        let mut receipt = Self {
            item_id,
            content_digest,
            tokenizer_digest,
            token_count,
            receipt_digest: Digest32::ZERO,
        };
        receipt.receipt_digest = receipt.compute_digest();
        receipt.validate()?;
        Ok(receipt)
    }

    pub fn validate(&self) -> Result<(), ContextCompilerV2Error> {
        ensure_digest("tokenized_content", self.content_digest)?;
        ensure_digest("tokenizer", self.tokenizer_digest)?;
        if self.token_count == 0 || self.token_count > MAX_CONTEXT_TOKENS_V2 {
            return Err(ContextCompilerV2Error::InvalidTokenCount(
                self.item_id.to_string(),
            ));
        }
        if self.receipt_digest != self.compute_digest() {
            return Err(ContextCompilerV2Error::DigestMismatch(
                "tokenization_receipt",
            ));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(TOKENIZATION_DOMAIN);
        push_id(&mut bytes, &self.item_id);
        push_digest(&mut bytes, self.content_digest);
        push_digest(&mut bytes, self.tokenizer_digest);
        push_u64(&mut bytes, self.token_count);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextModelProfileV2 {
    pub model_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub template_digest: Digest32,
    pub tool_schema_digest: Digest32,
    pub maximum_context_tokens: u64,
}

impl ContextModelProfileV2 {
    pub fn validate(&self) -> Result<(), ContextCompilerV2Error> {
        for (name, digest) in [
            ("model", self.model_digest),
            ("tokenizer", self.tokenizer_digest),
            ("template", self.template_digest),
            ("tool_schema", self.tool_schema_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.maximum_context_tokens == 0
            || self.maximum_context_tokens > MAX_CONTEXT_TOKENS_V2
        {
            return Err(ContextCompilerV2Error::InvalidModelContextLimit);
        }
        Ok(())
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(MODEL_PROFILE_DOMAIN);
        for digest in [
            self.model_digest,
            self.tokenizer_digest,
            self.template_digest,
            self.tool_schema_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_u64(&mut bytes, self.maximum_context_tokens);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextCandidateV2 {
    pub item_id: StableId,
    pub role: ContextRoleV2,
    pub content_digest: Digest32,
    pub source_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub tokenization: TokenizationReceiptV2,
    pub expected_value: FixedQ32,
    pub trusted_admission_digest: Option<Digest32>,
    pub contains_secret: bool,
}

impl ContextCandidateV2 {
    fn validate(
        &self,
        expected_generation_vector_digest: Digest32,
        profile: &ContextModelProfileV2,
    ) -> Result<(), ContextCompilerV2Error> {
        ensure_digest("candidate_content", self.content_digest)?;
        ensure_digest("candidate_source", self.source_digest)?;
        ensure_digest("candidate_generation_vector", self.generation_vector_digest)?;
        if self.generation_vector_digest != expected_generation_vector_digest {
            return Err(ContextCompilerV2Error::GenerationVectorMismatch(
                self.item_id.to_string(),
            ));
        }
        self.tokenization.validate()?;
        if self.tokenization.item_id != self.item_id
            || self.tokenization.content_digest != self.content_digest
        {
            return Err(ContextCompilerV2Error::TokenizationItemMismatch(
                self.item_id.to_string(),
            ));
        }
        if self.tokenization.tokenizer_digest != profile.tokenizer_digest {
            return Err(ContextCompilerV2Error::TokenizerMismatch(
                self.item_id.to_string(),
            ));
        }
        if self.expected_value < FixedQ32::ZERO || self.expected_value > FixedQ32::ONE {
            return Err(ContextCompilerV2Error::ValueOutOfRange(
                self.item_id.to_string(),
            ));
        }
        if self.contains_secret {
            return Err(ContextCompilerV2Error::SecretRejected(
                self.item_id.to_string(),
            ));
        }
        match self.role {
            ContextRoleV2::TrustedInstruction | ContextRoleV2::Schema => {
                let Some(admission) = self.trusted_admission_digest else {
                    return Err(ContextCompilerV2Error::MissingTrustedAdmission(
                        self.item_id.to_string(),
                    ));
                };
                ensure_digest("trusted_admission", admission)?;
            }
            ContextRoleV2::UntrustedEvidence => {
                if self.trusted_admission_digest.is_some() {
                    return Err(ContextCompilerV2Error::EvidenceRoleConfusion(
                        self.item_id.to_string(),
                    ));
                }
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MandatoryContextGroupV2 {
    pub group_id: StableId,
    pub item_ids: Vec<StableId>,
    pub reason_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextCompilationRequestV2 {
    pub compilation_id: StableId,
    pub objective_digest: Digest32,
    pub prompt_portfolio_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub model_profile: ContextModelProfileV2,
    pub token_budget: u64,
    pub truncation_policy_digest: Digest32,
    pub candidates: Vec<ContextCandidateV2>,
    pub mandatory_groups: Vec<MandatoryContextGroupV2>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextCompilationReceiptV2 {
    pub compilation_id: StableId,
    pub objective_digest: Digest32,
    pub prompt_portfolio_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub selected_item_ids: Vec<StableId>,
    pub omitted_item_ids: Vec<StableId>,
    pub used_tokens: u64,
    pub token_upper_bound: u64,
    pub truncation_policy_digest: Digest32,
    pub context_digest: Digest32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl ContextCompilationReceiptV2 {
    pub fn validate(&self) -> Result<(), ContextCompilerV2Error> {
        for (name, digest) in [
            ("objective", self.objective_digest),
            ("prompt_portfolio", self.prompt_portfolio_digest),
            ("generation_vector", self.generation_vector_digest),
            ("model_profile", self.model_profile_digest),
            ("candidate_set", self.candidate_set_digest),
            ("truncation_policy", self.truncation_policy_digest),
            ("context", self.context_digest),
            ("compilation_receipt", self.receipt_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.used_tokens > self.token_upper_bound || self.token_upper_bound > MAX_CONTEXT_TOKENS_V2
        {
            return Err(ContextCompilerV2Error::TokenBudgetExceeded);
        }
        if self.authority.grants_any() {
            return Err(ContextCompilerV2Error::AuthorityGranted);
        }
        if self.receipt_digest != self.compute_receipt_digest() {
            return Err(ContextCompilerV2Error::DigestMismatch(
                "compilation_receipt",
            ));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_receipt_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(COMPILATION_RECEIPT_DOMAIN);
        push_id(&mut bytes, &self.compilation_id);
        for digest in [
            self.objective_digest,
            self.prompt_portfolio_digest,
            self.generation_vector_digest,
            self.model_profile_digest,
            self.candidate_set_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_ids(&mut bytes, &self.selected_item_ids);
        push_ids(&mut bytes, &self.omitted_item_ids);
        push_u64(&mut bytes, self.used_tokens);
        push_u64(&mut bytes, self.token_upper_bound);
        push_digest(&mut bytes, self.truncation_policy_digest);
        push_digest(&mut bytes, self.context_digest);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompiledContextV2 {
    pub receipt: ContextCompilationReceiptV2,
    pub selected_candidates: Vec<ContextCandidateV2>,
}

impl CompiledContextV2 {
    pub fn validate(&self) -> Result<(), ContextCompilerV2Error> {
        self.receipt.validate()?;
        let selected_ids = self
            .selected_candidates
            .iter()
            .map(|candidate| candidate.item_id.clone())
            .collect::<Vec<_>>();
        if selected_ids != self.receipt.selected_item_ids {
            return Err(ContextCompilerV2Error::SelectedSetMismatch);
        }
        if self.receipt.context_digest != compute_context_digest(&self.selected_candidates) {
            return Err(ContextCompilerV2Error::DigestMismatch("context"));
        }
        Ok(())
    }
}

pub fn compile_v2(
    mut request: ContextCompilationRequestV2,
) -> Result<CompiledContextV2, ContextCompilerV2Error> {
    request.model_profile.validate()?;
    for (name, digest) in [
        ("objective", request.objective_digest),
        ("prompt_portfolio", request.prompt_portfolio_digest),
        ("generation_vector", request.generation_vector_digest),
        ("truncation_policy", request.truncation_policy_digest),
    ] {
        ensure_digest(name, digest)?;
    }
    if request.candidates.len() > MAX_CONTEXT_CANDIDATES_V2 {
        return Err(ContextCompilerV2Error::CandidateLimitExceeded);
    }
    if request.mandatory_groups.len() > MAX_CONTEXT_GROUPS_V2 {
        return Err(ContextCompilerV2Error::GroupLimitExceeded);
    }
    if request.token_budget == 0
        || request.token_budget > request.model_profile.maximum_context_tokens
    {
        return Err(ContextCompilerV2Error::InvalidTokenBudget);
    }

    request
        .candidates
        .sort_by(|left, right| left.item_id.cmp(&right.item_id));
    let mut by_id = BTreeMap::<StableId, ContextCandidateV2>::new();
    for candidate in request.candidates {
        candidate.validate(request.generation_vector_digest, &request.model_profile)?;
        let item_id = candidate.item_id.clone();
        if by_id.insert(item_id.clone(), candidate).is_some() {
            return Err(ContextCompilerV2Error::DuplicateCandidate(
                item_id.to_string(),
            ));
        }
    }

    let candidate_set_digest = compute_candidate_set_digest(by_id.values());
    let mut mandatory_ids = by_id
        .values()
        .filter(|candidate| {
            matches!(
                candidate.role,
                ContextRoleV2::TrustedInstruction | ContextRoleV2::Schema
            )
        })
        .map(|candidate| candidate.item_id.clone())
        .collect::<BTreeSet<_>>();
    let mut group_ids = BTreeSet::new();
    for group in request.mandatory_groups {
        if !group_ids.insert(group.group_id.clone()) {
            return Err(ContextCompilerV2Error::DuplicateMandatoryGroup(
                group.group_id.to_string(),
            ));
        }
        ensure_digest("mandatory_group_reason", group.reason_digest)?;
        if group.item_ids.is_empty() {
            return Err(ContextCompilerV2Error::EmptyMandatoryGroup(
                group.group_id.to_string(),
            ));
        }
        let mut local_ids = BTreeSet::new();
        for item_id in group.item_ids {
            if !local_ids.insert(item_id.clone()) {
                return Err(ContextCompilerV2Error::DuplicateMandatoryItem(
                    item_id.to_string(),
                ));
            }
            if !by_id.contains_key(&item_id) {
                return Err(ContextCompilerV2Error::UnknownMandatoryItem(
                    item_id.to_string(),
                ));
            }
            mandatory_ids.insert(item_id);
        }
    }

    let mandatory_tokens = mandatory_ids.iter().try_fold(0_u64, |total, item_id| {
        let Some(candidate) = by_id.get(item_id) else {
            return Err(ContextCompilerV2Error::UnknownMandatoryItem(
                item_id.to_string(),
            ));
        };
        total
            .checked_add(candidate.tokenization.token_count)
            .ok_or(ContextCompilerV2Error::Arithmetic)
    })?;
    if mandatory_tokens > request.token_budget {
        return Err(ContextCompilerV2Error::InsufficientMandatoryBudget {
            required_tokens: mandatory_tokens,
            token_budget: request.token_budget,
        });
    }

    let mut selected = by_id
        .values()
        .filter(|candidate| mandatory_ids.contains(&candidate.item_id))
        .cloned()
        .collect::<Vec<_>>();
    selected.sort_by(context_placement_order);
    let mut optional = by_id
        .values()
        .filter(|candidate| !mandatory_ids.contains(&candidate.item_id))
        .cloned()
        .collect::<Vec<_>>();
    optional.sort_by(value_per_token_order);

    let mut used_tokens = mandatory_tokens;
    let mut omitted = Vec::new();
    for candidate in optional {
        let next = used_tokens
            .checked_add(candidate.tokenization.token_count)
            .ok_or(ContextCompilerV2Error::Arithmetic)?;
        if next > request.token_budget {
            omitted.push(candidate.item_id);
        } else {
            used_tokens = next;
            selected.push(candidate);
        }
    }
    selected.sort_by(context_placement_order);
    omitted.sort();
    let selected_ids = selected
        .iter()
        .map(|candidate| candidate.item_id.clone())
        .collect::<Vec<_>>();
    let model_profile_digest = request.model_profile.digest();
    let context_digest = compute_context_digest(&selected);
    let mut receipt = ContextCompilationReceiptV2 {
        compilation_id: request.compilation_id,
        objective_digest: request.objective_digest,
        prompt_portfolio_digest: request.prompt_portfolio_digest,
        generation_vector_digest: request.generation_vector_digest,
        model_profile_digest,
        candidate_set_digest,
        selected_item_ids: selected_ids,
        omitted_item_ids: omitted,
        used_tokens,
        token_upper_bound: request.token_budget,
        truncation_policy_digest: request.truncation_policy_digest,
        context_digest,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = receipt.compute_receipt_digest();
    let compiled = CompiledContextV2 {
        receipt,
        selected_candidates: selected,
    };
    compiled.validate()?;
    Ok(compiled)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextSerializationReceiptV2 {
    pub serialization_id: StableId,
    pub compilation_receipt_digest: Digest32,
    pub context_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub selected_item_ids: Vec<StableId>,
    pub payload_digest: Digest32,
    pub serialized_token_count: u64,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl ContextSerializationReceiptV2 {
    pub fn validate_for(
        &self,
        compiled: &CompiledContextV2,
    ) -> Result<(), ContextCompilerV2Error> {
        compiled.validate()?;
        for (name, digest) in [
            ("compilation_receipt", self.compilation_receipt_digest),
            ("context", self.context_digest),
            ("model_profile", self.model_profile_digest),
            ("payload", self.payload_digest),
            ("serialization_receipt", self.receipt_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.compilation_receipt_digest != compiled.receipt.receipt_digest
            || self.context_digest != compiled.receipt.context_digest
            || self.model_profile_digest != compiled.receipt.model_profile_digest
            || self.selected_item_ids != compiled.receipt.selected_item_ids
            || self.serialized_token_count != compiled.receipt.used_tokens
        {
            return Err(ContextCompilerV2Error::SerializationMismatch);
        }
        if self.authority.grants_any() {
            return Err(ContextCompilerV2Error::AuthorityGranted);
        }
        if self.receipt_digest != self.compute_receipt_digest() {
            return Err(ContextCompilerV2Error::DigestMismatch(
                "serialization_receipt",
            ));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_receipt_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(SERIALIZATION_DOMAIN);
        push_id(&mut bytes, &self.serialization_id);
        push_digest(&mut bytes, self.compilation_receipt_digest);
        push_digest(&mut bytes, self.context_digest);
        push_digest(&mut bytes, self.model_profile_digest);
        push_ids(&mut bytes, &self.selected_item_ids);
        push_digest(&mut bytes, self.payload_digest);
        push_u64(&mut bytes, self.serialized_token_count);
        Digest32::of_bytes(&bytes)
    }
}

pub fn record_serialization(
    compiled: &CompiledContextV2,
    serialization_id: StableId,
    payload_digest: Digest32,
) -> Result<ContextSerializationReceiptV2, ContextCompilerV2Error> {
    compiled.validate()?;
    ensure_digest("payload", payload_digest)?;
    let mut receipt = ContextSerializationReceiptV2 {
        serialization_id,
        compilation_receipt_digest: compiled.receipt.receipt_digest,
        context_digest: compiled.receipt.context_digest,
        model_profile_digest: compiled.receipt.model_profile_digest,
        selected_item_ids: compiled.receipt.selected_item_ids.clone(),
        payload_digest,
        serialized_token_count: compiled.receipt.used_tokens,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = receipt.compute_receipt_digest();
    receipt.validate_for(compiled)?;
    Ok(receipt)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextAttachmentV2 {
    pub attachment_id: StableId,
    pub compilation_receipt_digest: Digest32,
    pub serialization_receipt_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub payload_digest: Digest32,
    pub selected_item_ids: Vec<StableId>,
    pub attachment_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl ContextAttachmentV2 {
    pub fn validate(
        &self,
        compiled: &CompiledContextV2,
        serialization: &ContextSerializationReceiptV2,
    ) -> Result<(), ContextCompilerV2Error> {
        compiled.validate()?;
        serialization.validate_for(compiled)?;
        if self.compilation_receipt_digest != compiled.receipt.receipt_digest
            || self.serialization_receipt_digest != serialization.receipt_digest
            || self.generation_vector_digest != compiled.receipt.generation_vector_digest
            || self.model_profile_digest != compiled.receipt.model_profile_digest
            || self.payload_digest != serialization.payload_digest
            || self.selected_item_ids != compiled.receipt.selected_item_ids
        {
            return Err(ContextCompilerV2Error::AttachmentMismatch);
        }
        if self.authority.grants_any() {
            return Err(ContextCompilerV2Error::AuthorityGranted);
        }
        if self.attachment_digest != self.compute_attachment_digest() {
            return Err(ContextCompilerV2Error::DigestMismatch("attachment"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_attachment_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(ATTACHMENT_DOMAIN);
        push_id(&mut bytes, &self.attachment_id);
        push_digest(&mut bytes, self.compilation_receipt_digest);
        push_digest(&mut bytes, self.serialization_receipt_digest);
        push_digest(&mut bytes, self.generation_vector_digest);
        push_digest(&mut bytes, self.model_profile_digest);
        push_digest(&mut bytes, self.payload_digest);
        push_ids(&mut bytes, &self.selected_item_ids);
        Digest32::of_bytes(&bytes)
    }
}

pub fn build_attachment(
    compiled: &CompiledContextV2,
    serialization: &ContextSerializationReceiptV2,
    attachment_id: StableId,
) -> Result<ContextAttachmentV2, ContextCompilerV2Error> {
    serialization.validate_for(compiled)?;
    let mut attachment = ContextAttachmentV2 {
        attachment_id,
        compilation_receipt_digest: compiled.receipt.receipt_digest,
        serialization_receipt_digest: serialization.receipt_digest,
        generation_vector_digest: compiled.receipt.generation_vector_digest,
        model_profile_digest: compiled.receipt.model_profile_digest,
        payload_digest: serialization.payload_digest,
        selected_item_ids: compiled.receipt.selected_item_ids.clone(),
        attachment_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    attachment.attachment_digest = attachment.compute_attachment_digest();
    attachment.validate(compiled, serialization)?;
    Ok(attachment)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ContextDeliveryDispositionV2 {
    Delivered,
    Rejected,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextDeliveryObservationV2 {
    pub observation_id: StableId,
    pub attachment_digest: Digest32,
    pub expected_payload_digest: Digest32,
    pub observed_payload_digest: Option<Digest32>,
    pub model_profile_digest: Digest32,
    pub terminal_observed: bool,
    pub disposition: ContextDeliveryDispositionV2,
    pub observed_unix_ms: u64,
    pub observation_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl ContextDeliveryObservationV2 {
    pub fn validate_for(
        &self,
        attachment: &ContextAttachmentV2,
    ) -> Result<(), ContextCompilerV2Error> {
        for (name, digest) in [
            ("attachment", self.attachment_digest),
            ("expected_payload", self.expected_payload_digest),
            ("model_profile", self.model_profile_digest),
            ("delivery_observation", self.observation_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.attachment_digest != attachment.attachment_digest
            || self.expected_payload_digest != attachment.payload_digest
            || self.model_profile_digest != attachment.model_profile_digest
        {
            return Err(ContextCompilerV2Error::DeliveryMismatch);
        }
        match self.disposition {
            ContextDeliveryDispositionV2::Delivered => {
                if !self.terminal_observed
                    || self.observed_payload_digest != Some(self.expected_payload_digest)
                {
                    return Err(ContextCompilerV2Error::DeliveryMismatch);
                }
            }
            ContextDeliveryDispositionV2::Rejected => {
                if !self.terminal_observed {
                    return Err(ContextCompilerV2Error::MissingTerminalObservation);
                }
            }
            ContextDeliveryDispositionV2::Indeterminate => {
                if self.terminal_observed {
                    return Err(ContextCompilerV2Error::InvalidDeliveryDisposition);
                }
            }
        }
        if self.observed_unix_ms == 0 {
            return Err(ContextCompilerV2Error::InvalidObservationTime);
        }
        if self.authority.grants_any() {
            return Err(ContextCompilerV2Error::AuthorityGranted);
        }
        if self.observation_digest != self.compute_observation_digest() {
            return Err(ContextCompilerV2Error::DigestMismatch(
                "delivery_observation",
            ));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_observation_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(DELIVERY_DOMAIN);
        push_id(&mut bytes, &self.observation_id);
        push_digest(&mut bytes, self.attachment_digest);
        push_digest(&mut bytes, self.expected_payload_digest);
        match self.observed_payload_digest {
            Some(digest) => {
                bytes.push(1);
                push_digest(&mut bytes, digest);
            }
            None => bytes.push(0),
        }
        push_digest(&mut bytes, self.model_profile_digest);
        bytes.push(u8::from(self.terminal_observed));
        bytes.push(delivery_disposition_code(self.disposition));
        push_u64(&mut bytes, self.observed_unix_ms);
        Digest32::of_bytes(&bytes)
    }
}

pub fn observe_delivery(
    attachment: &ContextAttachmentV2,
    observation_id: StableId,
    observed_payload_digest: Option<Digest32>,
    terminal_observed: bool,
    disposition: ContextDeliveryDispositionV2,
    observed_unix_ms: u64,
) -> Result<ContextDeliveryObservationV2, ContextCompilerV2Error> {
    if let Some(digest) = observed_payload_digest {
        ensure_digest("observed_payload", digest)?;
    }
    let mut observation = ContextDeliveryObservationV2 {
        observation_id,
        attachment_digest: attachment.attachment_digest,
        expected_payload_digest: attachment.payload_digest,
        observed_payload_digest,
        model_profile_digest: attachment.model_profile_digest,
        terminal_observed,
        disposition,
        observed_unix_ms,
        observation_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    observation.observation_digest = observation.compute_observation_digest();
    observation.validate_for(attachment)?;
    Ok(observation)
}

fn compute_candidate_set_digest<'a>(
    candidates: impl IntoIterator<Item = &'a ContextCandidateV2>,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(CANDIDATE_SET_DOMAIN);
    for candidate in candidates {
        push_id(&mut bytes, &candidate.item_id);
        bytes.push(role_code(candidate.role));
        push_digest(&mut bytes, candidate.content_digest);
        push_digest(&mut bytes, candidate.source_digest);
        push_digest(&mut bytes, candidate.generation_vector_digest);
        push_digest(&mut bytes, candidate.tokenization.receipt_digest);
        push_i64(&mut bytes, candidate.expected_value.raw());
        match candidate.trusted_admission_digest {
            Some(digest) => {
                bytes.push(1);
                push_digest(&mut bytes, digest);
            }
            None => bytes.push(0),
        }
    }
    Digest32::of_bytes(&bytes)
}

fn compute_context_digest(candidates: &[ContextCandidateV2]) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(CONTEXT_DOMAIN);
    push_len(&mut bytes, candidates.len());
    for candidate in candidates {
        bytes.push(role_code(candidate.role));
        push_id(&mut bytes, &candidate.item_id);
        push_digest(&mut bytes, candidate.content_digest);
        push_digest(&mut bytes, candidate.source_digest);
        push_digest(&mut bytes, candidate.tokenization.receipt_digest);
    }
    Digest32::of_bytes(&bytes)
}

fn context_placement_order(left: &ContextCandidateV2, right: &ContextCandidateV2) -> Ordering {
    left.role
        .cmp(&right.role)
        .then_with(|| left.item_id.cmp(&right.item_id))
}

fn value_per_token_order(left: &ContextCandidateV2, right: &ContextCandidateV2) -> Ordering {
    let left_cross = i128::from(left.expected_value.raw())
        * i128::from(right.tokenization.token_count);
    let right_cross = i128::from(right.expected_value.raw())
        * i128::from(left.tokenization.token_count);
    right_cross
        .cmp(&left_cross)
        .then_with(|| right.expected_value.cmp(&left.expected_value))
        .then_with(|| left.item_id.cmp(&right.item_id))
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ContextCompilerV2Error {
    EmptyDigest(&'static str),
    DigestMismatch(&'static str),
    CandidateLimitExceeded,
    GroupLimitExceeded,
    InvalidModelContextLimit,
    InvalidTokenBudget,
    InvalidTokenCount(String),
    DuplicateCandidate(String),
    DuplicateMandatoryGroup(String),
    EmptyMandatoryGroup(String),
    DuplicateMandatoryItem(String),
    UnknownMandatoryItem(String),
    GenerationVectorMismatch(String),
    TokenizationItemMismatch(String),
    TokenizerMismatch(String),
    ValueOutOfRange(String),
    SecretRejected(String),
    MissingTrustedAdmission(String),
    EvidenceRoleConfusion(String),
    InsufficientMandatoryBudget {
        required_tokens: u64,
        token_budget: u64,
    },
    TokenBudgetExceeded,
    SelectedSetMismatch,
    SerializationMismatch,
    AttachmentMismatch,
    DeliveryMismatch,
    MissingTerminalObservation,
    InvalidDeliveryDisposition,
    InvalidObservationTime,
    AuthorityGranted,
    Arithmetic,
}

impl fmt::Display for ContextCompilerV2Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ContextCompilerV2Error {}

fn ensure_digest(
    name: &'static str,
    digest: Digest32,
) -> Result<(), ContextCompilerV2Error> {
    if digest.is_zero() {
        return Err(ContextCompilerV2Error::EmptyDigest(name));
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

fn push_i64(bytes: &mut Vec<u8>, value: i64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

const fn role_code(role: ContextRoleV2) -> u8 {
    match role {
        ContextRoleV2::TrustedInstruction => 0,
        ContextRoleV2::Schema => 1,
        ContextRoleV2::UntrustedEvidence => 2,
    }
}

const fn delivery_disposition_code(disposition: ContextDeliveryDispositionV2) -> u8 {
    match disposition {
        ContextDeliveryDispositionV2::Delivered => 0,
        ContextDeliveryDispositionV2::Rejected => 1,
        ContextDeliveryDispositionV2::Indeterminate => 2,
    }
}

#[cfg(test)]
#[path = "v2_tests.rs"]
mod tests;
