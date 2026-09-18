//! Canonical prompt-selection to context-compilation composition.
//!
//! This is a source-level product composition surface. It does not dispatch a
//! model or claim delivery. The optimizer remains read-only and the context
//! compiler remains the owner of compilation receipts.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_context_compiler::{
    CompiledContextV2, ContextCandidateV2, ContextCompilationRequestV2,
    ContextCompilerV2Error, ContextModelProfileV2, ContextRoleV2, MandatoryContextGroupV2,
    TokenizationReceiptV2, compile_v2,
};
use codex_hepta_learning_ledger::{
    LearningEvidenceRoleV1, LearningEvidenceVerifierV1, SignedEvidenceError,
    SignedLearningEvidenceV1,
};
use codex_hepta_prompt_optimizer::canonical::{
    CandidateEvidenceV1, CanonicalError, ExerciseBoundaryV1, ExerciseDispositionV1,
    PortfolioBudgetV1, PortfolioRelationV1, PromptCandidateSetReceiptV1,
    PromptExerciseDecisionV1, PromptPortfolioReceiptV1, PromptPricingReceiptV1,
    candidate_evidence_signing_bytes, enumerate_factors, exercise, price_factors,
    select_portfolio,
};
use codex_hepta_prompt_registry::{
    PromptModelTupleV2, PromptRegistry, PromptRegistrySnapshotV2, PromptRegistryV2Error,
    PromptRoleV2,
};
use codex_hepta_types::{Digest32, FixedQ32, StableId};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedCandidatePricingEvidenceV1 {
    pub pricing: CandidateEvidenceV1,
    pub signed: SignedLearningEvidenceV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalPromptContextReceiptV1 {
    pub candidates: PromptCandidateSetReceiptV1,
    pub pricing: PromptPricingReceiptV1,
    pub portfolio: PromptPortfolioReceiptV1,
    pub exercise: PromptExerciseDecisionV1,
    pub context: CompiledContextV2,
}

pub struct CanonicalPromptContextRequestV1<'a> {
    pub registry: &'a PromptRegistry,
    pub expected_registry_snapshot: &'a PromptRegistrySnapshotV2,
    pub generation_vector_digest: Digest32,
    pub prompt_model: &'a PromptModelTupleV2,
    pub context_model: ContextModelProfileV2,
    pub decision_id: StableId,
    pub compilation_id: StableId,
    pub objective_digest: Digest32,
    pub generator_digest: Digest32,
    pub hard_filter_digest: Digest32,
    pub prompt_truncation_digest: Digest32,
    pub context_truncation_digest: Digest32,
    pub now_unix_ms: u64,
    pub evidence_verifier: &'a LearningEvidenceVerifierV1,
    pub evidence: Vec<SignedCandidatePricingEvidenceV1>,
    pub relations: Vec<PortfolioRelationV1>,
    pub portfolio_budget: PortfolioBudgetV1,
    pub context_token_budget: u64,
    pub additional_context: Vec<ContextCandidateV2>,
    pub mandatory_groups: Vec<MandatoryContextGroupV2>,
}

#[derive(Debug)]
pub enum CanonicalPromptContextErrorV1 {
    Registry(PromptRegistryV2Error),
    Prompt(CanonicalError),
    Context(ContextCompilerV2Error),
    SignedEvidence(SignedEvidenceError),
    ModelProfileMismatch,
    StaleAtExercise,
    SelectedCandidateMissing(String),
}

impl fmt::Display for CanonicalPromptContextErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for CanonicalPromptContextErrorV1 {}

pub fn run_canonical_prompt_context_v1(
    request: CanonicalPromptContextRequestV1<'_>,
) -> Result<CanonicalPromptContextReceiptV1, CanonicalPromptContextErrorV1> {
    validate_model_profiles(request.prompt_model, &request.context_model)?;
    let compatible = request
        .registry
        .read_compatible_v2(
            request.expected_registry_snapshot,
            request.generation_vector_digest,
            request.prompt_model,
            request.now_unix_ms,
            Vec::new(),
            128,
        )
        .map_err(CanonicalPromptContextErrorV1::Registry)?;
    let candidates = enumerate_factors(
        request.decision_id,
        request.objective_digest,
        request.expected_registry_snapshot,
        &compatible,
        request.generator_digest,
        request.hard_filter_digest,
        request.prompt_truncation_digest,
    )
    .map_err(CanonicalPromptContextErrorV1::Prompt)?;
    let mut admitted_evidence = Vec::with_capacity(request.evidence.len());
    for evidence in request.evidence {
        if evidence.signed.objective_digest != request.objective_digest {
            return Err(CanonicalPromptContextErrorV1::SignedEvidence(
                SignedEvidenceError::ContextMismatch,
            ));
        }
        let payload = candidate_evidence_signing_bytes(&evidence.pricing);
        request
            .evidence_verifier
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                &evidence.signed,
                &payload,
                request.now_unix_ms,
            )
            .map_err(CanonicalPromptContextErrorV1::SignedEvidence)?;
        admitted_evidence.push(evidence.pricing);
    }
    let pricing = price_factors(&candidates, admitted_evidence)
        .map_err(CanonicalPromptContextErrorV1::Prompt)?;
    let portfolio = select_portfolio(&pricing, request.relations, request.portfolio_budget)
        .map_err(CanonicalPromptContextErrorV1::Prompt)?;
    let exercise_receipt = exercise(
        &portfolio,
        request.registry,
        request.expected_registry_snapshot,
        request.generation_vector_digest,
        request.prompt_model,
        request.now_unix_ms,
        ExerciseBoundaryV1::BeforeModelOrToolDispatch,
    )
    .map_err(CanonicalPromptContextErrorV1::Prompt)?;
    if exercise_receipt.disposition != ExerciseDispositionV1::Exercise {
        return Err(CanonicalPromptContextErrorV1::StaleAtExercise);
    }

    let mut context_candidates = request.additional_context;
    for selected_id in &portfolio.selected_candidate_ids {
        let Some(price) = pricing
            .prices
            .iter()
            .find(|price| &price.candidate.candidate_id == selected_id)
        else {
            return Err(CanonicalPromptContextErrorV1::SelectedCandidateMissing(
                selected_id.to_string(),
            ));
        };
        let tokenization = TokenizationReceiptV2::new(
            price.candidate.candidate_id.clone(),
            price.candidate.payload_digest,
            request.context_model.tokenizer_digest,
            price.candidate.token_cost,
        )
        .map_err(CanonicalPromptContextErrorV1::Context)?;
        context_candidates.push(ContextCandidateV2 {
            item_id: price.candidate.candidate_id.clone(),
            role: map_prompt_role(price.candidate.role),
            content_digest: price.candidate.payload_digest,
            source_digest: request.expected_registry_snapshot.registry_digest,
            generation_vector_digest: request.generation_vector_digest,
            tokenization,
            expected_value: FixedQ32::ZERO,
            trusted_admission_digest: Some(request.expected_registry_snapshot.snapshot_digest),
            contains_secret: false,
        });
    }

    let context = compile_v2(ContextCompilationRequestV2 {
        compilation_id: request.compilation_id,
        objective_digest: candidates.objective_digest,
        prompt_portfolio_digest: portfolio.receipt_digest,
        generation_vector_digest: request.generation_vector_digest,
        model_profile: request.context_model,
        token_budget: request.context_token_budget,
        truncation_policy_digest: request.context_truncation_digest,
        candidates: context_candidates,
        mandatory_groups: request.mandatory_groups,
    })
    .map_err(CanonicalPromptContextErrorV1::Context)?;

    Ok(CanonicalPromptContextReceiptV1 {
        candidates,
        pricing,
        portfolio,
        exercise: exercise_receipt,
        context,
    })
}

fn validate_model_profiles(
    prompt: &PromptModelTupleV2,
    context: &ContextModelProfileV2,
) -> Result<(), CanonicalPromptContextErrorV1> {
    prompt
        .validate()
        .map_err(CanonicalPromptContextErrorV1::Registry)?;
    context
        .validate()
        .map_err(CanonicalPromptContextErrorV1::Context)?;
    if prompt.model_digest != context.model_digest
        || prompt.tokenizer_digest != context.tokenizer_digest
        || prompt.template_digest != context.template_digest
        || prompt.tool_schema_digest != context.tool_schema_digest
    {
        return Err(CanonicalPromptContextErrorV1::ModelProfileMismatch);
    }
    Ok(())
}

const fn map_prompt_role(role: PromptRoleV2) -> ContextRoleV2 {
    match role {
        PromptRoleV2::SystemInstruction
        | PromptRoleV2::DeveloperInstruction
        | PromptRoleV2::UserTemplate => ContextRoleV2::TrustedInstruction,
        PromptRoleV2::ToolSchemaFragment => ContextRoleV2::Schema,
    }
}

#[cfg(test)]
#[path = "prompt_pipeline_tests.rs"]
mod tests;
