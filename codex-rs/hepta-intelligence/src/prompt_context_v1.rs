//! Product-facing composition from an exercised prompt portfolio into the
//! existing context-compiler delivery chain.
//!
//! This module stops before provider delivery. It may compile, bind a serializer
//! witness and build an attachment, but it never manufactures a delivery
//! observation or writes learning outcomes.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_context_compiler::CompiledContextV2;
use codex_hepta_context_compiler::ContextAttachmentV2;
use codex_hepta_context_compiler::ContextCandidateV2;
use codex_hepta_context_compiler::ContextCompilationRequestV2;
use codex_hepta_context_compiler::ContextCompilerV2Error;
use codex_hepta_context_compiler::ContextModelProfileV2;
use codex_hepta_context_compiler::ContextRoleV2;
use codex_hepta_context_compiler::ContextSerializationReceiptV2;
use codex_hepta_context_compiler::MandatoryContextGroupV2;
use codex_hepta_context_compiler::TokenizationReceiptV2;
use codex_hepta_context_compiler::build_attachment;
use codex_hepta_context_compiler::compile_v2;
use codex_hepta_context_compiler::record_serialization;
use codex_hepta_prompt_optimizer::PromptCandidateSetReceiptV1;
use codex_hepta_prompt_optimizer::PromptCandidateSourceAuthenticatorV1;
use codex_hepta_prompt_optimizer::PromptExerciseDecisionV1;
use codex_hepta_prompt_optimizer::PromptExerciseDispositionV1;
use codex_hepta_prompt_optimizer::PromptExerciseRequestV1;
use codex_hepta_prompt_optimizer::PromptPortfolioReceiptV1;
use codex_hepta_prompt_optimizer::PromptPricingReceiptV1;
use codex_hepta_prompt_optimizer::PromptRelationSourceV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const SELECTED_PROMPT_GROUP_ID: &str = "prompt:selected-portfolio";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptContextPreparationRequestV1 {
    pub compilation_id: StableId,
    pub serialization_id: StableId,
    pub attachment_id: StableId,
    pub maximum_context_tokens: u64,
    pub token_budget: u64,
    pub truncation_policy_digest: Digest32,
    /// Exact tokenizer receipts produced for the selected prompt payloads.
    pub tokenizations: Vec<TokenizationReceiptV2>,
    /// Digest of bytes produced by the actual serializer. This is not delivery evidence.
    pub serialized_payload_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptContextPreparationV1 {
    pub exercise_receipt_digest: Digest32,
    pub portfolio_receipt_digest: Digest32,
    pub compiled: CompiledContextV2,
    pub serialization: ContextSerializationReceiptV2,
    pub attachment: ContextAttachmentV2,
    pub preparation_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl PromptContextPreparationV1 {
    pub fn validate(
        &self,
        exercise: &PromptExerciseDecisionV1,
        portfolio: &PromptPortfolioReceiptV1,
    ) -> Result<(), PromptContextCompositionErrorV1> {
        if self.exercise_receipt_digest != exercise.receipt_digest
            || self.portfolio_receipt_digest != portfolio.receipt_digest
            || self.compiled.receipt.prompt_portfolio_digest != portfolio.receipt_digest
            || self.compiled.receipt.selected_item_ids != portfolio.selected_candidate_ids
            || self.authority.grants_any()
        {
            return Err(PromptContextCompositionErrorV1::InvalidPreparation);
        }
        self.compiled
            .validate()
            .map_err(PromptContextCompositionErrorV1::Context)?;
        self.serialization
            .validate_for(&self.compiled)
            .map_err(PromptContextCompositionErrorV1::Context)?;
        self.attachment
            .validate(&self.compiled, &self.serialization)
            .map_err(PromptContextCompositionErrorV1::Context)?;
        if self.preparation_digest != compute_preparation_digest(self) {
            return Err(PromptContextCompositionErrorV1::DigestMismatch);
        }
        Ok(())
    }
}

pub fn prepare_prompt_context_v1<A>(
    candidate_set: &PromptCandidateSetReceiptV1,
    pricing: &PromptPricingReceiptV1,
    relations: &PromptRelationSourceV1,
    portfolio: &PromptPortfolioReceiptV1,
    exercise: &PromptExerciseDecisionV1,
    exercise_request: &PromptExerciseRequestV1,
    source_authenticator: &A,
    request: PromptContextPreparationRequestV1,
) -> Result<PromptContextPreparationV1, PromptContextCompositionErrorV1>
where
    A: PromptCandidateSourceAuthenticatorV1,
{
    exercise
        .validate_for(
            candidate_set,
            pricing,
            relations,
            portfolio,
            exercise_request,
        )
        .map_err(PromptContextCompositionErrorV1::Exercise)?;
    source_authenticator
        .authenticate_candidate_source(
            &exercise_request.current_source,
            portfolio.objective_digest,
            exercise_request.now_unix_ms,
        )
        .map_err(|_| PromptContextCompositionErrorV1::SourceAuthenticationRejected)?;
    match exercise.disposition {
        PromptExerciseDispositionV1::ExercisePortfolio => {}
        PromptExerciseDispositionV1::NoIntervention => {
            return Err(PromptContextCompositionErrorV1::NoIntervention);
        }
        PromptExerciseDispositionV1::Invalidated(reason) => {
            return Err(PromptContextCompositionErrorV1::Invalidated(reason));
        }
    }
    if request.truncation_policy_digest.is_zero() || request.serialized_payload_digest.is_zero() {
        return Err(PromptContextCompositionErrorV1::EmptyDigest);
    }

    let current_bindings = exercise_request
        .current_source
        .bindings
        .iter()
        .map(|binding| (binding.candidate_id.clone(), binding))
        .collect::<BTreeMap<_, _>>();
    let prices = pricing
        .prices
        .iter()
        .map(|price| (price.candidate_id.clone(), price))
        .collect::<BTreeMap<_, _>>();
    let mut tokenizations = BTreeMap::new();
    for tokenization in &request.tokenizations {
        tokenization
            .validate()
            .map_err(PromptContextCompositionErrorV1::Context)?;
        if tokenizations
            .insert(tokenization.item_id.clone(), tokenization.clone())
            .is_some()
        {
            return Err(PromptContextCompositionErrorV1::DuplicateTokenization(
                tokenization.item_id.to_string(),
            ));
        }
    }
    if tokenizations.len() != portfolio.selected_candidate_ids.len() {
        return Err(PromptContextCompositionErrorV1::InvalidTokenizationSet);
    }
    let mut candidates = Vec::with_capacity(portfolio.selected_candidate_ids.len());
    for candidate_id in &portfolio.selected_candidate_ids {
        let binding = current_bindings
            .get(candidate_id)
            .ok_or_else(|| PromptContextCompositionErrorV1::MissingSelectedBinding(
                candidate_id.to_string(),
            ))?;
        let price = prices
            .get(candidate_id)
            .ok_or(PromptContextCompositionErrorV1::InvalidPreparation)?;
        let tokenization = tokenizations
            .remove(candidate_id)
            .ok_or_else(|| PromptContextCompositionErrorV1::MissingTokenization(
                candidate_id.to_string(),
            ))?;
        if tokenization.token_count > binding.token_cost {
            return Err(PromptContextCompositionErrorV1::TokenizationExceedsRegisteredBound(
                candidate_id.to_string(),
            ));
        }
        candidates.push(ContextCandidateV2 {
            item_id: candidate_id.clone(),
            role: match binding.role {
                codex_hepta_prompt_optimizer::PromptCandidateRoleV1::ToolSchemaFragment => {
                    ContextRoleV2::Schema
                }
                codex_hepta_prompt_optimizer::PromptCandidateRoleV1::SystemInstruction
                | codex_hepta_prompt_optimizer::PromptCandidateRoleV1::DeveloperInstruction
                | codex_hepta_prompt_optimizer::PromptCandidateRoleV1::UserTemplate => {
                    ContextRoleV2::TrustedInstruction
                }
            },
            content_digest: binding.payload_digest,
            source_digest: binding.binding_digest,
            generation_vector_digest: exercise.current_generation_vector_digest,
            tokenization,
            expected_value: price.confidence,
            trusted_admission_digest: Some(binding.admission_digest),
            contains_secret: false,
        });
    }

    let model = &exercise_request.current_source.model_profile;
    let compiled = compile_v2(ContextCompilationRequestV2 {
        compilation_id: request.compilation_id,
        objective_digest: portfolio.objective_digest,
        prompt_portfolio_digest: portfolio.receipt_digest,
        generation_vector_digest: exercise.current_generation_vector_digest,
        model_profile: ContextModelProfileV2 {
            model_digest: model.model_digest,
            tokenizer_digest: model.tokenizer_digest,
            template_digest: model.template_digest,
            tool_schema_digest: model.tool_schema_digest,
            maximum_context_tokens: request.maximum_context_tokens,
        },
        token_budget: request.token_budget,
        truncation_policy_digest: request.truncation_policy_digest,
        candidates,
        mandatory_groups: vec![MandatoryContextGroupV2 {
            group_id: StableId::new(SELECTED_PROMPT_GROUP_ID)
                .map_err(|_| PromptContextCompositionErrorV1::InternalInvariant)?,
            item_ids: portfolio.selected_candidate_ids.clone(),
            reason_digest: exercise.receipt_digest,
        }],
    })
    .map_err(PromptContextCompositionErrorV1::Context)?;
    if compiled.receipt.selected_item_ids != portfolio.selected_candidate_ids {
        return Err(PromptContextCompositionErrorV1::InvalidPreparation);
    }
    let serialization = record_serialization(
        &compiled,
        request.serialization_id,
        request.serialized_payload_digest,
    )
    .map_err(PromptContextCompositionErrorV1::Context)?;
    let attachment = build_attachment(&compiled, &serialization, request.attachment_id)
        .map_err(PromptContextCompositionErrorV1::Context)?;
    let mut preparation = PromptContextPreparationV1 {
        exercise_receipt_digest: exercise.receipt_digest,
        portfolio_receipt_digest: portfolio.receipt_digest,
        compiled,
        serialization,
        attachment,
        preparation_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    preparation.preparation_digest = compute_preparation_digest(&preparation);
    preparation.validate(exercise, portfolio)?;
    Ok(preparation)
}

fn compute_preparation_digest(value: &PromptContextPreparationV1) -> Digest32 {
    let mut bytes = b"hepta.intelligence.prompt-context-preparation.v1".to_vec();
    for digest in [
        value.exercise_receipt_digest,
        value.portfolio_receipt_digest,
        value.compiled.receipt.receipt_digest,
        value.serialization.receipt_digest,
        value.attachment.attachment_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

#[derive(Debug)]
pub enum PromptContextCompositionErrorV1 {
    Exercise(codex_hepta_prompt_optimizer::PromptExerciseErrorV1),
    Context(ContextCompilerV2Error),
    NoIntervention,
    Invalidated(codex_hepta_prompt_optimizer::PromptExerciseInvalidationV1),
    MissingSelectedBinding(String),
    EmptyDigest,
    SourceAuthenticationRejected,
    InvalidPreparation,
    DigestMismatch,
    InternalInvariant,
}

impl fmt::Display for PromptContextCompositionErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PromptContextCompositionErrorV1 {}
