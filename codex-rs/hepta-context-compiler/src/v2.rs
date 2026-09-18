//! Exact-profile, admission-verified context compilation and delivery receipts.
//!
//! V2 is the normative context compiler path. Candidates are created only by
//! an admission-snapshot verifier and an exact tokenizer adapter; compilation
//! binds one coherent admission/revocation snapshot and mandatory-group policy;
//! serialization materializes the exact selected bytes, runs the registered
//! serializer and tokenizes the final payload; attachment revalidates current
//! admission; delivery consumes a validated provider receipt plus an
//! independent provider-evidence verifier. This crate never sends to a provider
//! and grants no runtime, writer or model authority.

use std::cmp::Ordering;
use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_contracts::ProviderInvocationReceipt;
use codex_hepta_contracts::ProviderTerminal;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

pub const MAX_CONTEXT_CANDIDATES_V2: usize = 4_096;
pub const MAX_CONTEXT_GROUPS_V2: usize = 256;
pub const MAX_CONTEXT_TOKENS_V2: u64 = 1_000_000;
pub const MAX_CONTEXT_ITEM_BYTES_V2: usize = 4 * 1024 * 1024;
pub const MAX_CONTEXT_SERIALIZED_BYTES_V2: usize = 16 * 1024 * 1024;
const TOKENIZATION_DOMAIN: &[u8] = b"hepta.context-tokenization.v2";
const ADMISSION_DOMAIN: &[u8] = b"hepta.context-admission.v2";
const MODEL_PROFILE_DOMAIN: &[u8] = b"hepta.context-model-profile.v2";
const CANDIDATE_SET_DOMAIN: &[u8] = b"hepta.context-candidate-set.v2";
const MANDATORY_GROUPS_DOMAIN: &[u8] = b"hepta.context-mandatory-groups.v2";
const CONTEXT_DOMAIN: &[u8] = b"hepta.context-compilation.v2";
const COMPILATION_RECEIPT_DOMAIN: &[u8] = b"hepta.context-compilation-receipt.v2";
const MATERIALIZATION_DOMAIN: &[u8] = b"hepta.context-materialization.v2";
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
pub struct ContextAdmissionClaimV2 {
    pub item_id: StableId,
    pub role: ContextRoleV2,
    pub content_digest: Digest32,
    pub source_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub contains_secret: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextAdmissionDecisionV2 {
    pub source_admission_digest: Digest32,
    pub expires_at_unix_ms: u64,
}

pub trait ContextAdmissionSnapshotVerifierV2 {
    fn verifier_digest(&self) -> Digest32;
    fn snapshot_digest(&self) -> Digest32;
    fn revocation_frontier_digest(&self) -> Digest32;
    fn verify_admitted(
        &self,
        claim: &ContextAdmissionClaimV2,
        at_unix_ms: u64,
    ) -> Result<ContextAdmissionDecisionV2, String>;
}

pub trait ExactContextTokenizerV2 {
    fn tokenizer_digest(&self) -> Digest32;
    fn count_tokens(&self, bytes: &[u8]) -> Result<u64, String>;
}

pub trait ContextSerializerV2 {
    fn serializer_digest(&self) -> Digest32;
    fn template_digest(&self) -> Digest32;
    fn tool_schema_digest(&self) -> Digest32;
    fn serialize(
        &self,
        compiled: &CompiledContextV2,
        items: &[ContextMaterializedItemV2],
    ) -> Result<Vec<u8>, String>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextProviderDeliveryDecisionV2 {
    pub evidence_digest: Digest32,
    pub recorded_at_unix_ms: u64,
}

pub trait ContextProviderDeliveryVerifierV2 {
    fn verifier_digest(&self) -> Digest32;
    fn verify_delivery(
        &self,
        receipt: &ProviderInvocationReceipt,
    ) -> Result<ContextProviderDeliveryDecisionV2, String>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextAdmissionReceiptV2 {
    item_id: StableId,
    role: ContextRoleV2,
    content_digest: Digest32,
    source_digest: Digest32,
    generation_vector_digest: Digest32,
    verifier_digest: Digest32,
    snapshot_digest: Digest32,
    revocation_frontier_digest: Digest32,
    source_admission_digest: Digest32,
    verified_at_unix_ms: u64,
    expires_at_unix_ms: u64,
    receipt_digest: Digest32,
    authority: AuthorityPosture,
}

impl ContextAdmissionReceiptV2 {
    #[must_use]
    pub fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    #[must_use]
    pub fn snapshot_digest(&self) -> Digest32 {
        self.snapshot_digest
    }

    #[must_use]
    pub fn revocation_frontier_digest(&self) -> Digest32 {
        self.revocation_frontier_digest
    }

    #[must_use]
    pub fn source_admission_digest(&self) -> Digest32 {
        self.source_admission_digest
    }

    fn new(
        claim: &ContextAdmissionClaimV2,
        verifier: &impl ContextAdmissionSnapshotVerifierV2,
        decision: ContextAdmissionDecisionV2,
        verified_at_unix_ms: u64,
    ) -> Result<Self, ContextCompilerV2Error> {
        let verifier_digest = verifier.verifier_digest();
        let snapshot_digest = verifier.snapshot_digest();
        let revocation_frontier_digest = verifier.revocation_frontier_digest();
        for (name, digest) in [
            ("admission_verifier", verifier_digest),
            ("admission_snapshot", snapshot_digest),
            ("revocation_frontier", revocation_frontier_digest),
            ("source_admission", decision.source_admission_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if verified_at_unix_ms == 0 || decision.expires_at_unix_ms <= verified_at_unix_ms {
            return Err(ContextCompilerV2Error::InvalidAdmissionWindow(
                claim.item_id.to_string(),
            ));
        }
        let mut receipt = Self {
            item_id: claim.item_id.clone(),
            role: claim.role,
            content_digest: claim.content_digest,
            source_digest: claim.source_digest,
            generation_vector_digest: claim.generation_vector_digest,
            verifier_digest,
            snapshot_digest,
            revocation_frontier_digest,
            source_admission_digest: decision.source_admission_digest,
            verified_at_unix_ms,
            expires_at_unix_ms: decision.expires_at_unix_ms,
            receipt_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        receipt.receipt_digest = receipt.compute_digest();
        receipt.validate_for_claim(claim, verified_at_unix_ms)?;
        Ok(receipt)
    }

    fn validate_for_claim(
        &self,
        claim: &ContextAdmissionClaimV2,
        at_unix_ms: u64,
    ) -> Result<(), ContextCompilerV2Error> {
        if self.item_id != claim.item_id
            || self.role != claim.role
            || self.content_digest != claim.content_digest
            || self.source_digest != claim.source_digest
            || self.generation_vector_digest != claim.generation_vector_digest
        {
            return Err(ContextCompilerV2Error::AdmissionBindingMismatch(
                claim.item_id.to_string(),
            ));
        }
        for (name, digest) in [
            ("admission_content", self.content_digest),
            ("admission_source", self.source_digest),
            ("admission_generation", self.generation_vector_digest),
            ("admission_verifier", self.verifier_digest),
            ("admission_snapshot", self.snapshot_digest),
            ("revocation_frontier", self.revocation_frontier_digest),
            ("source_admission", self.source_admission_digest),
            ("admission_receipt", self.receipt_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.verified_at_unix_ms == 0
            || self.expires_at_unix_ms <= self.verified_at_unix_ms
            || at_unix_ms < self.verified_at_unix_ms
            || at_unix_ms >= self.expires_at_unix_ms
        {
            return Err(ContextCompilerV2Error::AdmissionExpired(
                claim.item_id.to_string(),
            ));
        }
        if self.authority.grants_any() {
            return Err(ContextCompilerV2Error::AuthorityGranted);
        }
        if self.receipt_digest != self.compute_digest() {
            return Err(ContextCompilerV2Error::DigestMismatch("admission_receipt"));
        }
        Ok(())
    }

    fn compute_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(ADMISSION_DOMAIN);
        push_id(&mut bytes, &self.item_id);
        bytes.push(role_code(self.role));
        for digest in [
            self.content_digest,
            self.source_digest,
            self.generation_vector_digest,
            self.verifier_digest,
            self.snapshot_digest,
            self.revocation_frontier_digest,
            self.source_admission_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_u64(&mut bytes, self.verified_at_unix_ms);
        push_u64(&mut bytes, self.expires_at_unix_ms);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TokenizationReceiptV2 {
    item_id: StableId,
    content_digest: Digest32,
    tokenizer_digest: Digest32,
    token_count: u64,
    receipt_digest: Digest32,
}

impl TokenizationReceiptV2 {
    #[must_use]
    pub fn token_count(&self) -> u64 {
        self.token_count
    }

    #[must_use]
    pub fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    fn from_exact_tokenizer(
        item_id: StableId,
        content_digest: Digest32,
        tokenizer: &impl ExactContextTokenizerV2,
        content: &[u8],
    ) -> Result<Self, ContextCompilerV2Error> {
        let tokenizer_digest = tokenizer.tokenizer_digest();
        ensure_digest("tokenizer", tokenizer_digest)?;
        let token_count = tokenizer
            .count_tokens(content)
            .map_err(ContextCompilerV2Error::TokenizerFailure)?;
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

    fn validate(&self) -> Result<(), ContextCompilerV2Error> {
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

    fn compute_digest(&self) -> Digest32 {
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
    pub provider_id_digest: Digest32,
    pub provider_model_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub serializer_digest: Digest32,
    pub template_digest: Digest32,
    pub tool_schema_digest: Digest32,
    pub maximum_context_tokens: u64,
}

impl ContextModelProfileV2 {
    pub fn validate(&self) -> Result<(), ContextCompilerV2Error> {
        for (name, digest) in [
            ("model", self.model_digest),
            ("provider_id", self.provider_id_digest),
            ("provider_model", self.provider_model_digest),
            ("tokenizer", self.tokenizer_digest),
            ("serializer", self.serializer_digest),
            ("template", self.template_digest),
            ("tool_schema", self.tool_schema_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.maximum_context_tokens == 0 || self.maximum_context_tokens > MAX_CONTEXT_TOKENS_V2 {
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
            self.provider_id_digest,
            self.provider_model_digest,
            self.tokenizer_digest,
            self.serializer_digest,
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
pub struct ContextCandidateDraftV2 {
    pub item_id: StableId,
    pub role: ContextRoleV2,
    pub source_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub expected_value: FixedQ32,
    pub contains_secret: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextCandidateV2 {
    item_id: StableId,
    role: ContextRoleV2,
    content_digest: Digest32,
    source_digest: Digest32,
    generation_vector_digest: Digest32,
    tokenization: TokenizationReceiptV2,
    admission: ContextAdmissionReceiptV2,
    expected_value: FixedQ32,
    contains_secret: bool,
}

impl ContextCandidateV2 {
    #[must_use]
    pub fn item_id(&self) -> &StableId {
        &self.item_id
    }

    #[must_use]
    pub fn role(&self) -> ContextRoleV2 {
        self.role
    }

    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        self.content_digest
    }

    #[must_use]
    pub fn source_digest(&self) -> Digest32 {
        self.source_digest
    }

    #[must_use]
    pub fn token_count(&self) -> u64 {
        self.tokenization.token_count
    }

    #[must_use]
    pub fn admission_receipt(&self) -> &ContextAdmissionReceiptV2 {
        &self.admission
    }

    fn admission_claim(&self) -> ContextAdmissionClaimV2 {
        ContextAdmissionClaimV2 {
            item_id: self.item_id.clone(),
            role: self.role,
            content_digest: self.content_digest,
            source_digest: self.source_digest,
            generation_vector_digest: self.generation_vector_digest,
            contains_secret: self.contains_secret,
        }
    }

    fn validate(
        &self,
        expected_generation_vector_digest: Digest32,
        profile: &ContextModelProfileV2,
        admission_verifier_digest: Digest32,
        admission_snapshot_digest: Digest32,
        revocation_frontier_digest: Digest32,
        compiled_at_unix_ms: u64,
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
        let claim = self.admission_claim();
        self.admission
            .validate_for_claim(&claim, compiled_at_unix_ms)?;
        if self.admission.verifier_digest != admission_verifier_digest
            || self.admission.snapshot_digest != admission_snapshot_digest
            || self.admission.revocation_frontier_digest != revocation_frontier_digest
        {
            return Err(ContextCompilerV2Error::AdmissionSnapshotMismatch(
                self.item_id.to_string(),
            ));
        }
        Ok(())
    }
}

pub fn verify_context_candidate_v2(
    draft: ContextCandidateDraftV2,
    content: &[u8],
    admission_snapshot: &impl ContextAdmissionSnapshotVerifierV2,
    tokenizer: &impl ExactContextTokenizerV2,
    verified_at_unix_ms: u64,
) -> Result<ContextCandidateV2, ContextCompilerV2Error> {
    if content.is_empty() || content.len() > MAX_CONTEXT_ITEM_BYTES_V2 {
        return Err(ContextCompilerV2Error::InvalidMaterializedItemBytes(
            draft.item_id.to_string(),
        ));
    }
    ensure_digest("candidate_source", draft.source_digest)?;
    ensure_digest("candidate_generation_vector", draft.generation_vector_digest)?;
    if draft.expected_value < FixedQ32::ZERO || draft.expected_value > FixedQ32::ONE {
        return Err(ContextCompilerV2Error::ValueOutOfRange(
            draft.item_id.to_string(),
        ));
    }
    if draft.contains_secret {
        return Err(ContextCompilerV2Error::SecretRejected(
            draft.item_id.to_string(),
        ));
    }
    let content_digest = Digest32::of_bytes(content);
    let claim = ContextAdmissionClaimV2 {
        item_id: draft.item_id.clone(),
        role: draft.role,
        content_digest,
        source_digest: draft.source_digest,
        generation_vector_digest: draft.generation_vector_digest,
        contains_secret: draft.contains_secret,
    };
    let decision = admission_snapshot
        .verify_admitted(&claim, verified_at_unix_ms)
        .map_err(|reason| ContextCompilerV2Error::AdmissionVerifierFailed {
            item_id: draft.item_id.to_string(),
            reason,
        })?;
    let admission = ContextAdmissionReceiptV2::new(
        &claim,
        admission_snapshot,
        decision,
        verified_at_unix_ms,
    )?;
    let tokenization = TokenizationReceiptV2::from_exact_tokenizer(
        draft.item_id.clone(),
        content_digest,
        tokenizer,
        content,
    )?;
    Ok(ContextCandidateV2 {
        item_id: draft.item_id,
        role: draft.role,
        content_digest,
        source_digest: draft.source_digest,
        generation_vector_digest: draft.generation_vector_digest,
        tokenization,
        admission,
        expected_value: draft.expected_value,
        contains_secret: draft.contains_secret,
    })
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
    pub admission_verifier_digest: Digest32,
    pub admission_snapshot_digest: Digest32,
    pub revocation_frontier_digest: Digest32,
    pub model_profile: ContextModelProfileV2,
    pub token_budget: u64,
    pub truncation_policy_digest: Digest32,
    pub compiled_at_unix_ms: u64,
    pub candidates: Vec<ContextCandidateV2>,
    pub mandatory_groups: Vec<MandatoryContextGroupV2>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextCompilationReceiptV2 {
    pub compilation_id: StableId,
    pub objective_digest: Digest32,
    pub prompt_portfolio_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub admission_verifier_digest: Digest32,
    pub admission_snapshot_digest: Digest32,
    pub revocation_frontier_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub mandatory_groups_digest: Digest32,
    pub selected_item_ids: Vec<StableId>,
    pub omitted_item_ids: Vec<StableId>,
    pub used_tokens: u64,
    pub token_upper_bound: u64,
    pub truncation_policy_digest: Digest32,
    pub compiled_at_unix_ms: u64,
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
            ("admission_verifier", self.admission_verifier_digest),
            ("admission_snapshot", self.admission_snapshot_digest),
            ("revocation_frontier", self.revocation_frontier_digest),
            ("model_profile", self.model_profile_digest),
            ("candidate_set", self.candidate_set_digest),
            ("mandatory_groups", self.mandatory_groups_digest),
            ("truncation_policy", self.truncation_policy_digest),
            ("context", self.context_digest),
            ("compilation_receipt", self.receipt_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.compiled_at_unix_ms == 0 {
            return Err(ContextCompilerV2Error::InvalidCompilationTime);
        }
        if self.used_tokens > self.token_upper_bound
            || self.token_upper_bound > MAX_CONTEXT_TOKENS_V2
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
            self.admission_verifier_digest,
            self.admission_snapshot_digest,
            self.revocation_frontier_digest,
            self.model_profile_digest,
            self.candidate_set_digest,
            self.mandatory_groups_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_ids(&mut bytes, &self.selected_item_ids);
        push_ids(&mut bytes, &self.omitted_item_ids);
        push_u64(&mut bytes, self.used_tokens);
        push_u64(&mut bytes, self.token_upper_bound);
        push_digest(&mut bytes, self.truncation_policy_digest);
        push_u64(&mut bytes, self.compiled_at_unix_ms);
        push_digest(&mut bytes, self.context_digest);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompiledContextV2 {
    receipt: ContextCompilationReceiptV2,
    model_profile: ContextModelProfileV2,
    selected_candidates: Vec<ContextCandidateV2>,
}

impl CompiledContextV2 {
    #[must_use]
    pub fn receipt(&self) -> &ContextCompilationReceiptV2 {
        &self.receipt
    }

    #[must_use]
    pub fn model_profile(&self) -> &ContextModelProfileV2 {
        &self.model_profile
    }

    #[must_use]
    pub fn selected_candidates(&self) -> &[ContextCandidateV2] {
        &self.selected_candidates
    }

    pub fn validate(&self) -> Result<(), ContextCompilerV2Error> {
        self.receipt.validate()?;
        self.model_profile.validate()?;
        if self.model_profile.digest() != self.receipt.model_profile_digest {
            return Err(ContextCompilerV2Error::DigestMismatch("model_profile"));
        }
        let selected_ids = self
            .selected_candidates
            .iter()
            .map(|candidate| candidate.item_id.clone())
            .collect::<Vec<_>>();
        if selected_ids != self.receipt.selected_item_ids {
            return Err(ContextCompilerV2Error::SelectedSetMismatch);
        }
        for candidate in &self.selected_candidates {
            candidate.validate(
                self.receipt.generation_vector_digest,
                &self.model_profile,
                self.receipt.admission_verifier_digest,
                self.receipt.admission_snapshot_digest,
                self.receipt.revocation_frontier_digest,
                self.receipt.compiled_at_unix_ms,
            )?;
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
        ("admission_verifier", request.admission_verifier_digest),
        ("admission_snapshot", request.admission_snapshot_digest),
        ("revocation_frontier", request.revocation_frontier_digest),
        ("truncation_policy", request.truncation_policy_digest),
    ] {
        ensure_digest(name, digest)?;
    }
    if request.compiled_at_unix_ms == 0 {
        return Err(ContextCompilerV2Error::InvalidCompilationTime);
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
        candidate.validate(
            request.generation_vector_digest,
            &request.model_profile,
            request.admission_verifier_digest,
            request.admission_snapshot_digest,
            request.revocation_frontier_digest,
            request.compiled_at_unix_ms,
        )?;
        let item_id = candidate.item_id.clone();
        if by_id.insert(item_id.clone(), candidate).is_some() {
            return Err(ContextCompilerV2Error::DuplicateCandidate(
                item_id.to_string(),
            ));
        }
    }

    let candidate_set_digest = compute_candidate_set_digest(by_id.values());
    let mandatory_groups = normalize_mandatory_groups(request.mandatory_groups, &by_id)?;
    let mandatory_groups_digest = compute_mandatory_groups_digest(&mandatory_groups);
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
    for group in &mandatory_groups {
        mandatory_ids.extend(group.item_ids.iter().cloned());
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
        admission_verifier_digest: request.admission_verifier_digest,
        admission_snapshot_digest: request.admission_snapshot_digest,
        revocation_frontier_digest: request.revocation_frontier_digest,
        model_profile_digest,
        candidate_set_digest,
        mandatory_groups_digest,
        selected_item_ids: selected_ids,
        omitted_item_ids: omitted,
        used_tokens,
        token_upper_bound: request.token_budget,
        truncation_policy_digest: request.truncation_policy_digest,
        compiled_at_unix_ms: request.compiled_at_unix_ms,
        context_digest,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = receipt.compute_receipt_digest();
    let compiled = CompiledContextV2 {
        receipt,
        model_profile: request.model_profile,
        selected_candidates: selected,
    };
    compiled.validate()?;
    Ok(compiled)
}

#[derive(Clone, Eq, PartialEq)]
pub struct ContextMaterializedItemV2 {
    pub item_id: StableId,
    pub content: Vec<u8>,
}

impl fmt::Debug for ContextMaterializedItemV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ContextMaterializedItemV2")
            .field("item_id", &self.item_id)
            .field("content_digest", &Digest32::of_bytes(&self.content))
            .field("content_bytes", &self.content.len())
            .finish()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextSerializationReceiptV2 {
    pub serialization_id: StableId,
    pub compilation_receipt_digest: Digest32,
    pub context_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub serializer_digest: Digest32,
    pub template_digest: Digest32,
    pub tool_schema_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub selected_item_ids: Vec<StableId>,
    pub materialization_digest: Digest32,
    pub payload_digest: Digest32,
    pub serialized_token_count: u64,
    pub serialized_at_unix_ms: u64,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl ContextSerializationReceiptV2 {
    pub fn validate_for(&self, compiled: &CompiledContextV2) -> Result<(), ContextCompilerV2Error> {
        compiled.validate()?;
        for (name, digest) in [
            ("compilation_receipt", self.compilation_receipt_digest),
            ("context", self.context_digest),
            ("model_profile", self.model_profile_digest),
            ("serializer", self.serializer_digest),
            ("template", self.template_digest),
            ("tool_schema", self.tool_schema_digest),
            ("tokenizer", self.tokenizer_digest),
            ("materialization", self.materialization_digest),
            ("payload", self.payload_digest),
            ("serialization_receipt", self.receipt_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.compilation_receipt_digest != compiled.receipt.receipt_digest
            || self.context_digest != compiled.receipt.context_digest
            || self.model_profile_digest != compiled.receipt.model_profile_digest
            || self.serializer_digest != compiled.model_profile.serializer_digest
            || self.template_digest != compiled.model_profile.template_digest
            || self.tool_schema_digest != compiled.model_profile.tool_schema_digest
            || self.tokenizer_digest != compiled.model_profile.tokenizer_digest
            || self.selected_item_ids != compiled.receipt.selected_item_ids
        {
            return Err(ContextCompilerV2Error::SerializationMismatch);
        }
        if self.serialized_token_count == 0
            || self.serialized_token_count > compiled.receipt.token_upper_bound
        {
            return Err(ContextCompilerV2Error::SerializedTokenBudgetExceeded {
                serialized_tokens: self.serialized_token_count,
                token_budget: compiled.receipt.token_upper_bound,
            });
        }
        if self.serialized_at_unix_ms < compiled.receipt.compiled_at_unix_ms {
            return Err(ContextCompilerV2Error::InvalidSerializationTime);
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
        for digest in [
            self.compilation_receipt_digest,
            self.context_digest,
            self.model_profile_digest,
            self.serializer_digest,
            self.template_digest,
            self.tool_schema_digest,
            self.tokenizer_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_ids(&mut bytes, &self.selected_item_ids);
        push_digest(&mut bytes, self.materialization_digest);
        push_digest(&mut bytes, self.payload_digest);
        push_u64(&mut bytes, self.serialized_token_count);
        push_u64(&mut bytes, self.serialized_at_unix_ms);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Eq, PartialEq)]
pub struct SerializedContextV2 {
    receipt: ContextSerializationReceiptV2,
    payload: Vec<u8>,
}

impl fmt::Debug for SerializedContextV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("SerializedContextV2")
            .field("receipt", &self.receipt)
            .field("payload_digest", &Digest32::of_bytes(&self.payload))
            .field("payload_bytes", &self.payload.len())
            .finish()
    }
}

impl SerializedContextV2 {
    #[must_use]
    pub fn receipt(&self) -> &ContextSerializationReceiptV2 {
        &self.receipt
    }

    #[must_use]
    pub fn payload(&self) -> &[u8] {
        &self.payload
    }

    pub fn validate_with(
        &self,
        compiled: &CompiledContextV2,
        tokenizer: &impl ExactContextTokenizerV2,
    ) -> Result<(), ContextCompilerV2Error> {
        self.receipt.validate_for(compiled)?;
        if self.payload.is_empty() || self.payload.len() > MAX_CONTEXT_SERIALIZED_BYTES_V2 {
            return Err(ContextCompilerV2Error::InvalidSerializedPayloadBytes);
        }
        if Digest32::of_bytes(&self.payload) != self.receipt.payload_digest {
            return Err(ContextCompilerV2Error::DigestMismatch("serialized_payload"));
        }
        if tokenizer.tokenizer_digest() != compiled.model_profile.tokenizer_digest {
            return Err(ContextCompilerV2Error::SerializationTokenizerMismatch);
        }
        let token_count = tokenizer
            .count_tokens(&self.payload)
            .map_err(ContextCompilerV2Error::TokenizerFailure)?;
        if token_count != self.receipt.serialized_token_count {
            return Err(ContextCompilerV2Error::SerializationTokenCountMismatch);
        }
        Ok(())
    }
}

pub fn serialize_context_exact(
    compiled: &CompiledContextV2,
    serialization_id: StableId,
    items: Vec<ContextMaterializedItemV2>,
    serializer: &impl ContextSerializerV2,
    tokenizer: &impl ExactContextTokenizerV2,
    serialized_at_unix_ms: u64,
) -> Result<SerializedContextV2, ContextCompilerV2Error> {
    compiled.validate()?;
    if serializer.serializer_digest() != compiled.model_profile.serializer_digest
        || serializer.template_digest() != compiled.model_profile.template_digest
        || serializer.tool_schema_digest() != compiled.model_profile.tool_schema_digest
    {
        return Err(ContextCompilerV2Error::SerializerProfileMismatch);
    }
    if tokenizer.tokenizer_digest() != compiled.model_profile.tokenizer_digest {
        return Err(ContextCompilerV2Error::SerializationTokenizerMismatch);
    }
    if serialized_at_unix_ms < compiled.receipt.compiled_at_unix_ms {
        return Err(ContextCompilerV2Error::InvalidSerializationTime);
    }
    let materialization_digest = validate_materialization(compiled, &items)?;
    let payload = serializer
        .serialize(compiled, &items)
        .map_err(ContextCompilerV2Error::SerializerFailure)?;
    if payload.is_empty() || payload.len() > MAX_CONTEXT_SERIALIZED_BYTES_V2 {
        return Err(ContextCompilerV2Error::InvalidSerializedPayloadBytes);
    }
    let serialized_token_count = tokenizer
        .count_tokens(&payload)
        .map_err(ContextCompilerV2Error::TokenizerFailure)?;
    if serialized_token_count == 0 || serialized_token_count > compiled.receipt.token_upper_bound {
        return Err(ContextCompilerV2Error::SerializedTokenBudgetExceeded {
            serialized_tokens: serialized_token_count,
            token_budget: compiled.receipt.token_upper_bound,
        });
    }
    let payload_digest = Digest32::of_bytes(&payload);
    let mut receipt = ContextSerializationReceiptV2 {
        serialization_id,
        compilation_receipt_digest: compiled.receipt.receipt_digest,
        context_digest: compiled.receipt.context_digest,
        model_profile_digest: compiled.receipt.model_profile_digest,
        serializer_digest: serializer.serializer_digest(),
        template_digest: serializer.template_digest(),
        tool_schema_digest: serializer.tool_schema_digest(),
        tokenizer_digest: tokenizer.tokenizer_digest(),
        selected_item_ids: compiled.receipt.selected_item_ids.clone(),
        materialization_digest,
        payload_digest,
        serialized_token_count,
        serialized_at_unix_ms,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = receipt.compute_receipt_digest();
    let serialized = SerializedContextV2 { receipt, payload };
    serialized.validate_with(compiled, tokenizer)?;
    Ok(serialized)
}

#[derive(Clone, Eq, PartialEq)]
pub struct ContextAttachmentV2 {
    attachment_id: StableId,
    compilation_receipt_digest: Digest32,
    serialization_receipt_digest: Digest32,
    generation_vector_digest: Digest32,
    model_profile_digest: Digest32,
    provider_id_digest: Digest32,
    provider_model_digest: Digest32,
    admission_verifier_digest: Digest32,
    admission_snapshot_digest: Digest32,
    revocation_frontier_digest: Digest32,
    payload_digest: Digest32,
    serialized_token_count: u64,
    selected_item_ids: Vec<StableId>,
    attached_at_unix_ms: u64,
    attachment_digest: Digest32,
    authority: AuthorityPosture,
    payload: Vec<u8>,
}

impl fmt::Debug for ContextAttachmentV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ContextAttachmentV2")
            .field("attachment_id", &self.attachment_id)
            .field("payload_digest", &self.payload_digest)
            .field("payload_bytes", &self.payload.len())
            .field("serialized_token_count", &self.serialized_token_count)
            .field("attachment_digest", &self.attachment_digest)
            .finish()
    }
}

impl ContextAttachmentV2 {
    #[must_use]
    pub fn attachment_digest(&self) -> Digest32 {
        self.attachment_digest
    }

    #[must_use]
    pub fn payload_digest(&self) -> Digest32 {
        self.payload_digest
    }

    #[must_use]
    pub fn payload(&self) -> &[u8] {
        &self.payload
    }

    #[must_use]
    pub fn model_profile_digest(&self) -> Digest32 {
        self.model_profile_digest
    }

    #[must_use]
    pub fn admission_snapshot_digest(&self) -> Digest32 {
        self.admission_snapshot_digest
    }

    #[must_use]
    pub fn revocation_frontier_digest(&self) -> Digest32 {
        self.revocation_frontier_digest
    }

    #[must_use]
    pub fn attached_at_unix_ms(&self) -> u64 {
        self.attached_at_unix_ms
    }

    pub fn validate(
        &self,
        compiled: &CompiledContextV2,
        serialized: &SerializedContextV2,
    ) -> Result<(), ContextCompilerV2Error> {
        compiled.validate()?;
        serialized.receipt.validate_for(compiled)?;
        for (name, digest) in [
            ("attachment_compilation", self.compilation_receipt_digest),
            ("attachment_serialization", self.serialization_receipt_digest),
            ("attachment_generation", self.generation_vector_digest),
            ("attachment_model_profile", self.model_profile_digest),
            ("attachment_provider_id", self.provider_id_digest),
            ("attachment_provider_model", self.provider_model_digest),
            ("attachment_admission_verifier", self.admission_verifier_digest),
            ("attachment_admission_snapshot", self.admission_snapshot_digest),
            ("attachment_revocation_frontier", self.revocation_frontier_digest),
            ("attachment_payload", self.payload_digest),
            ("attachment", self.attachment_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.compilation_receipt_digest != compiled.receipt.receipt_digest
            || self.serialization_receipt_digest != serialized.receipt.receipt_digest
            || self.generation_vector_digest != compiled.receipt.generation_vector_digest
            || self.model_profile_digest != compiled.receipt.model_profile_digest
            || self.provider_id_digest != compiled.model_profile.provider_id_digest
            || self.provider_model_digest != compiled.model_profile.provider_model_digest
            || self.payload_digest != serialized.receipt.payload_digest
            || self.serialized_token_count != serialized.receipt.serialized_token_count
            || self.selected_item_ids != compiled.receipt.selected_item_ids
            || self.payload != serialized.payload
            || Digest32::of_bytes(&self.payload) != self.payload_digest
        {
            return Err(ContextCompilerV2Error::AttachmentMismatch);
        }
        if self.attached_at_unix_ms < serialized.receipt.serialized_at_unix_ms {
            return Err(ContextCompilerV2Error::InvalidAttachmentTime);
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
        for digest in [
            self.compilation_receipt_digest,
            self.serialization_receipt_digest,
            self.generation_vector_digest,
            self.model_profile_digest,
            self.provider_id_digest,
            self.provider_model_digest,
            self.admission_verifier_digest,
            self.admission_snapshot_digest,
            self.revocation_frontier_digest,
            self.payload_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_u64(&mut bytes, self.serialized_token_count);
        push_ids(&mut bytes, &self.selected_item_ids);
        push_u64(&mut bytes, self.attached_at_unix_ms);
        Digest32::of_bytes(&bytes)
    }
}

pub fn build_attachment(
    compiled: &CompiledContextV2,
    serialized: &SerializedContextV2,
    attachment_id: StableId,
    current_admission_snapshot: &impl ContextAdmissionSnapshotVerifierV2,
    tokenizer: &impl ExactContextTokenizerV2,
    attached_at_unix_ms: u64,
) -> Result<ContextAttachmentV2, ContextCompilerV2Error> {
    serialized.validate_with(compiled, tokenizer)?;
    if attached_at_unix_ms < serialized.receipt.serialized_at_unix_ms {
        return Err(ContextCompilerV2Error::InvalidAttachmentTime);
    }
    let current_verifier_digest = current_admission_snapshot.verifier_digest();
    let current_snapshot_digest = current_admission_snapshot.snapshot_digest();
    let current_revocation_frontier_digest =
        current_admission_snapshot.revocation_frontier_digest();
    for (name, digest) in [
        ("current_admission_verifier", current_verifier_digest),
        ("current_admission_snapshot", current_snapshot_digest),
        ("current_revocation_frontier", current_revocation_frontier_digest),
    ] {
        ensure_digest(name, digest)?;
    }
    if current_verifier_digest != compiled.receipt.admission_verifier_digest {
        return Err(ContextCompilerV2Error::AdmissionVerifierChanged);
    }
    for candidate in &compiled.selected_candidates {
        revalidate_candidate_admission(
            candidate,
            current_admission_snapshot,
            attached_at_unix_ms,
        )?;
    }
    let mut attachment = ContextAttachmentV2 {
        attachment_id,
        compilation_receipt_digest: compiled.receipt.receipt_digest,
        serialization_receipt_digest: serialized.receipt.receipt_digest,
        generation_vector_digest: compiled.receipt.generation_vector_digest,
        model_profile_digest: compiled.receipt.model_profile_digest,
        provider_id_digest: compiled.model_profile.provider_id_digest,
        provider_model_digest: compiled.model_profile.provider_model_digest,
        admission_verifier_digest: current_verifier_digest,
        admission_snapshot_digest: current_snapshot_digest,
        revocation_frontier_digest: current_revocation_frontier_digest,
        payload_digest: serialized.receipt.payload_digest,
        serialized_token_count: serialized.receipt.serialized_token_count,
        selected_item_ids: compiled.receipt.selected_item_ids.clone(),
        attached_at_unix_ms,
        attachment_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
        payload: serialized.payload.clone(),
    };
    attachment.attachment_digest = attachment.compute_attachment_digest();
    attachment.validate(compiled, serialized)?;
    Ok(attachment)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ContextDeliveryDispositionV2 {
    Delivered,
    Rejected,
    NotDispatched,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextDeliveryObservationV2 {
    observation_id: StableId,
    attachment_digest: Digest32,
    expected_payload_digest: Digest32,
    provider_input_witness_digest: Digest32,
    provider_id_digest: Digest32,
    provider_model_digest: Digest32,
    provider_request_binding_digest: Digest32,
    provider_attempt_digest: Digest32,
    provider_receipt_digest: Digest32,
    provider_terminal_digest: Digest32,
    provider_evidence_verifier_digest: Digest32,
    provider_evidence_digest: Digest32,
    provider_recorded_at_unix_ms: u64,
    model_profile_digest: Digest32,
    terminal_observed: bool,
    disposition: ContextDeliveryDispositionV2,
    observed_unix_ms: u64,
    observation_digest: Digest32,
    authority: AuthorityPosture,
}

pub type ContextDeliveryReceiptV2 = ContextDeliveryObservationV2;

impl ContextDeliveryObservationV2 {
    #[must_use]
    pub fn disposition(&self) -> ContextDeliveryDispositionV2 {
        self.disposition
    }

    #[must_use]
    pub fn observation_digest(&self) -> Digest32 {
        self.observation_digest
    }

    #[must_use]
    pub fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    pub fn validate_for(
        &self,
        attachment: &ContextAttachmentV2,
    ) -> Result<(), ContextCompilerV2Error> {
        for (name, digest) in [
            ("attachment", self.attachment_digest),
            ("expected_payload", self.expected_payload_digest),
            ("provider_input_witness", self.provider_input_witness_digest),
            ("provider_id", self.provider_id_digest),
            ("provider_model", self.provider_model_digest),
            ("provider_request_binding", self.provider_request_binding_digest),
            ("provider_attempt", self.provider_attempt_digest),
            ("provider_receipt", self.provider_receipt_digest),
            ("provider_terminal", self.provider_terminal_digest),
            (
                "provider_evidence_verifier",
                self.provider_evidence_verifier_digest,
            ),
            ("provider_evidence", self.provider_evidence_digest),
            ("model_profile", self.model_profile_digest),
            ("delivery_observation", self.observation_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.attachment_digest != attachment.attachment_digest
            || self.expected_payload_digest != attachment.payload_digest
            || self.provider_id_digest != attachment.provider_id_digest
            || self.provider_model_digest != attachment.provider_model_digest
            || self.model_profile_digest != attachment.model_profile_digest
        {
            return Err(ContextCompilerV2Error::DeliveryMismatch);
        }
        match self.disposition {
            ContextDeliveryDispositionV2::Delivered
            | ContextDeliveryDispositionV2::Rejected
            | ContextDeliveryDispositionV2::NotDispatched => {
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
        if self.provider_recorded_at_unix_ms < attachment.attached_at_unix_ms
            || self.observed_unix_ms < self.provider_recorded_at_unix_ms
        {
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
        for digest in [
            self.attachment_digest,
            self.expected_payload_digest,
            self.provider_input_witness_digest,
            self.provider_id_digest,
            self.provider_model_digest,
            self.provider_request_binding_digest,
            self.provider_attempt_digest,
            self.provider_receipt_digest,
            self.provider_terminal_digest,
            self.provider_evidence_verifier_digest,
            self.provider_evidence_digest,
            self.model_profile_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_u64(&mut bytes, self.provider_recorded_at_unix_ms);
        bytes.push(u8::from(self.terminal_observed));
        bytes.push(delivery_disposition_code(self.disposition));
        push_u64(&mut bytes, self.observed_unix_ms);
        Digest32::of_bytes(&bytes)
    }
}

pub fn observe_delivery(
    attachment: &ContextAttachmentV2,
    observation_id: StableId,
    provider_receipt: &ProviderInvocationReceipt,
    delivery_verifier: &impl ContextProviderDeliveryVerifierV2,
    observed_unix_ms: u64,
) -> Result<ContextDeliveryObservationV2, ContextCompilerV2Error> {
    provider_receipt
        .validate()
        .map_err(ContextCompilerV2Error::ProviderReceiptInvalid)?;

    let provider_evidence_verifier_digest = delivery_verifier.verifier_digest();
    ensure_digest(
        "provider_evidence_verifier",
        provider_evidence_verifier_digest,
    )?;
    let delivery_evidence = delivery_verifier
        .verify_delivery(provider_receipt)
        .map_err(ContextCompilerV2Error::ProviderEvidenceInvalid)?;
    ensure_digest("provider_evidence", delivery_evidence.evidence_digest)?;
    if delivery_evidence.recorded_at_unix_ms < attachment.attached_at_unix_ms
        || observed_unix_ms < delivery_evidence.recorded_at_unix_ms
    {
        return Err(ContextCompilerV2Error::InvalidObservationTime);
    }

    let Some(provider_input) = provider_receipt.intent.binding.ephemeral_input_sha256.as_ref()
    else {
        return Err(ContextCompilerV2Error::MissingProviderInputBinding);
    };
    let Some(provider_input_witness) = provider_receipt
        .intent
        .binding
        .ephemeral_input_witness_sha256
        .as_ref()
    else {
        return Err(ContextCompilerV2Error::MissingProviderInputWitness);
    };
    let expected_payload_digest = attachment.payload_digest.to_string();
    if provider_input.as_str() != expected_payload_digest {
        return Err(ContextCompilerV2Error::DeliveryMismatch);
    }

    let provider_id_digest =
        Digest32::of_bytes(provider_receipt.intent.binding.provider_id.as_bytes());
    let provider_model_digest =
        Digest32::of_bytes(provider_receipt.intent.binding.model.as_bytes());
    if provider_id_digest != attachment.provider_id_digest
        || provider_model_digest != attachment.provider_model_digest
    {
        return Err(ContextCompilerV2Error::ProviderModelProfileMismatch);
    }

    let provider_input_witness_digest = provider_input_witness
        .as_str()
        .parse::<Digest32>()
        .map_err(|_| {
            ContextCompilerV2Error::ProviderReceiptInvalid(
                "provider input witness is not canonical sha256".to_string(),
            )
        })?;
    let provider_request_binding_digest =
        Digest32::of_bytes(provider_receipt.request_binding_id.as_str().as_bytes());
    let provider_attempt_digest =
        Digest32::of_bytes(provider_receipt.attempt_id.as_str().as_bytes());
    let provider_receipt_digest = Digest32::of_bytes(
        &provider_receipt
            .canonical_wire_bytes()
            .map_err(ContextCompilerV2Error::ProviderReceiptInvalid)?,
    );
    let provider_terminal_digest = Digest32::of_bytes(
        &provider_receipt
            .terminal
            .canonical_wire_bytes()
            .map_err(ContextCompilerV2Error::ProviderReceiptInvalid)?,
    );
    let (terminal_observed, disposition) = match &provider_receipt.terminal {
        ProviderTerminal::Completed { .. } | ProviderTerminal::CompletedUnary { .. } => {
            (true, ContextDeliveryDispositionV2::Delivered)
        }
        ProviderTerminal::Rejected { .. } => (true, ContextDeliveryDispositionV2::Rejected),
        ProviderTerminal::NotDispatched { .. } => {
            (true, ContextDeliveryDispositionV2::NotDispatched)
        }
        ProviderTerminal::Indeterminate { .. } => {
            (false, ContextDeliveryDispositionV2::Indeterminate)
        }
    };
    let mut observation = ContextDeliveryObservationV2 {
        observation_id,
        attachment_digest: attachment.attachment_digest,
        expected_payload_digest: attachment.payload_digest,
        provider_input_witness_digest,
        provider_id_digest,
        provider_model_digest,
        provider_request_binding_digest,
        provider_attempt_digest,
        provider_receipt_digest,
        provider_terminal_digest,
        provider_evidence_verifier_digest,
        provider_evidence_digest: delivery_evidence.evidence_digest,
        provider_recorded_at_unix_ms: delivery_evidence.recorded_at_unix_ms,
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

fn revalidate_candidate_admission(
    candidate: &ContextCandidateV2,
    current_admission_snapshot: &impl ContextAdmissionSnapshotVerifierV2,
    at_unix_ms: u64,
) -> Result<(), ContextCompilerV2Error> {
    let claim = candidate.admission_claim();
    let decision = current_admission_snapshot
        .verify_admitted(&claim, at_unix_ms)
        .map_err(|reason| ContextCompilerV2Error::AdmissionRevalidationFailed {
            item_id: candidate.item_id.to_string(),
            reason,
        })?;
    ensure_digest("current_source_admission", decision.source_admission_digest)?;
    if decision.source_admission_digest != candidate.admission.source_admission_digest {
        return Err(ContextCompilerV2Error::AdmissionRevalidationMismatch(
            candidate.item_id.to_string(),
        ));
    }
    if decision.expires_at_unix_ms <= at_unix_ms {
        return Err(ContextCompilerV2Error::AdmissionExpired(
            candidate.item_id.to_string(),
        ));
    }
    Ok(())
}

fn validate_materialization(
    compiled: &CompiledContextV2,
    items: &[ContextMaterializedItemV2],
) -> Result<Digest32, ContextCompilerV2Error> {
    if items.len() != compiled.selected_candidates.len() {
        return Err(ContextCompilerV2Error::MaterializationMismatch);
    }
    let mut bytes = Vec::new();
    bytes.extend_from_slice(MATERIALIZATION_DOMAIN);
    push_len(&mut bytes, items.len());
    for (item, candidate) in items.iter().zip(&compiled.selected_candidates) {
        if item.item_id != candidate.item_id
            || item.content.is_empty()
            || item.content.len() > MAX_CONTEXT_ITEM_BYTES_V2
        {
            return Err(ContextCompilerV2Error::MaterializationMismatch);
        }
        let content_digest = Digest32::of_bytes(&item.content);
        if content_digest != candidate.content_digest {
            return Err(ContextCompilerV2Error::MaterializedContentMismatch(
                item.item_id.to_string(),
            ));
        }
        push_id(&mut bytes, &item.item_id);
        bytes.push(role_code(candidate.role));
        push_digest(&mut bytes, content_digest);
        push_len(&mut bytes, item.content.len());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn normalize_mandatory_groups(
    mut groups: Vec<MandatoryContextGroupV2>,
    candidates: &BTreeMap<StableId, ContextCandidateV2>,
) -> Result<Vec<MandatoryContextGroupV2>, ContextCompilerV2Error> {
    groups.sort_by(|left, right| left.group_id.cmp(&right.group_id));
    let mut previous_group: Option<StableId> = None;
    for group in &mut groups {
        if previous_group.as_ref() == Some(&group.group_id) {
            return Err(ContextCompilerV2Error::DuplicateMandatoryGroup(
                group.group_id.to_string(),
            ));
        }
        previous_group = Some(group.group_id.clone());
        ensure_digest("mandatory_group_reason", group.reason_digest)?;
        if group.item_ids.is_empty() {
            return Err(ContextCompilerV2Error::EmptyMandatoryGroup(
                group.group_id.to_string(),
            ));
        }
        group.item_ids.sort();
        let mut previous_item: Option<StableId> = None;
        for item_id in &group.item_ids {
            if previous_item.as_ref() == Some(item_id) {
                return Err(ContextCompilerV2Error::DuplicateMandatoryItem(
                    item_id.to_string(),
                ));
            }
            previous_item = Some(item_id.clone());
            if !candidates.contains_key(item_id) {
                return Err(ContextCompilerV2Error::UnknownMandatoryItem(
                    item_id.to_string(),
                ));
            }
        }
    }
    Ok(groups)
}

fn compute_mandatory_groups_digest(groups: &[MandatoryContextGroupV2]) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(MANDATORY_GROUPS_DOMAIN);
    push_len(&mut bytes, groups.len());
    for group in groups {
        push_id(&mut bytes, &group.group_id);
        push_ids(&mut bytes, &group.item_ids);
        push_digest(&mut bytes, group.reason_digest);
    }
    Digest32::of_bytes(&bytes)
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
        push_digest(&mut bytes, candidate.admission.receipt_digest);
        push_i64(&mut bytes, candidate.expected_value.raw());
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
        push_digest(&mut bytes, candidate.admission.receipt_digest);
    }
    Digest32::of_bytes(&bytes)
}

fn context_placement_order(left: &ContextCandidateV2, right: &ContextCandidateV2) -> Ordering {
    left.role
        .cmp(&right.role)
        .then_with(|| left.item_id.cmp(&right.item_id))
}

fn value_per_token_order(left: &ContextCandidateV2, right: &ContextCandidateV2) -> Ordering {
    let left_cross =
        i128::from(left.expected_value.raw()) * i128::from(right.tokenization.token_count);
    let right_cross =
        i128::from(right.expected_value.raw()) * i128::from(left.tokenization.token_count);
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
    InvalidCompilationTime,
    InvalidSerializationTime,
    InvalidAttachmentTime,
    InvalidObservationTime,
    InvalidMaterializedItemBytes(String),
    InvalidSerializedPayloadBytes,
    DuplicateCandidate(String),
    DuplicateMandatoryGroup(String),
    EmptyMandatoryGroup(String),
    DuplicateMandatoryItem(String),
    UnknownMandatoryItem(String),
    GenerationVectorMismatch(String),
    TokenizationItemMismatch(String),
    TokenizerMismatch(String),
    TokenizerFailure(String),
    ValueOutOfRange(String),
    SecretRejected(String),
    AdmissionVerifierFailed {
        item_id: String,
        reason: String,
    },
    AdmissionBindingMismatch(String),
    AdmissionSnapshotMismatch(String),
    AdmissionVerifierChanged,
    InvalidAdmissionWindow(String),
    AdmissionExpired(String),
    AdmissionRevalidationFailed {
        item_id: String,
        reason: String,
    },
    AdmissionRevalidationMismatch(String),
    InsufficientMandatoryBudget {
        required_tokens: u64,
        token_budget: u64,
    },
    TokenBudgetExceeded,
    SelectedSetMismatch,
    MaterializationMismatch,
    MaterializedContentMismatch(String),
    SerializerProfileMismatch,
    SerializerFailure(String),
    SerializationTokenizerMismatch,
    SerializationTokenCountMismatch,
    SerializedTokenBudgetExceeded {
        serialized_tokens: u64,
        token_budget: u64,
    },
    SerializationMismatch,
    AttachmentMismatch,
    ProviderReceiptInvalid(String),
    ProviderEvidenceInvalid(String),
    MissingProviderInputBinding,
    MissingProviderInputWitness,
    ProviderModelProfileMismatch,
    DeliveryMismatch,
    MissingTerminalObservation,
    InvalidDeliveryDisposition,
    AuthorityGranted,
    Arithmetic,
}

impl fmt::Display for ContextCompilerV2Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ContextCompilerV2Error {}

fn ensure_digest(name: &'static str, digest: Digest32) -> Result<(), ContextCompilerV2Error> {
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
        ContextDeliveryDispositionV2::NotDispatched => 2,
        ContextDeliveryDispositionV2::Indeterminate => 3,
    }
}

#[cfg(test)]
#[path = "v2_tests.rs"]
mod tests;
