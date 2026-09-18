//! Product-facing composition for the canonical prompt optimizer.
//!
//! This layer does not invoke a provider. It converts an exercised, revalidated
//! prompt portfolio into the existing context compiler's trusted candidates,
//! preserves the serialization/attachment digest chain, and requires a second
//! optimizer revalidation immediately before a delivery attachment is prepared.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_context_compiler::{
    build_attachment, compile_v2, observe_delivery, record_serialization, CompiledContextV2,
    ContextAttachmentV2, ContextCandidateV2, ContextCompilationRequestV2, ContextDeliveryDispositionV2,
    ContextDeliveryObservationV2, ContextModelProfileV2, ContextRoleV2,
    ContextSerializationReceiptV2, MandatoryContextGroupV2, TokenizationReceiptV2,
};
use codex_hepta_prompt_optimizer::canonical::{
    exercise_v1, PromptExerciseActionV1, PromptExerciseDecisionV1, PromptExerciseRequestV1,
    SelectedPromptPortfolioV1,
};
use codex_hepta_prompt_registry::{PromptRegistry, PromptRoleV2};
use codex_hepta_types::{Digest32, FixedQ32, StableId};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptContextCompileRequestV1 {
    pub exercise: PromptExerciseRequestV1,
    pub compilation_id: StableId,
    pub model_profile: ContextModelProfileV2,
    pub token_budget: u64,
    pub truncation_policy_digest: Digest32,
    pub base_candidates: Vec<ContextCandidateV2>,
    pub mandatory_groups: Vec<MandatoryContextGroupV2>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedPromptContextV1 {
    pub exercise: PromptExerciseDecisionV1,
    pub compiled: CompiledContextV2,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptDeliveryPrepareRequestV1 {
    pub exercise: PromptExerciseRequestV1,
    pub serialization_id: StableId,
    pub payload_digest: Digest32,
    pub attachment_id: StableId,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedPromptDeliveryV1 {
    pub exercise: PromptExerciseDecisionV1,
    pub serialization: ContextSerializationReceiptV2,
    pub attachment: ContextAttachmentV2,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptPipelineErrorV1 {
    ModelTupleMismatch,
    ExerciseRejected(PromptExerciseActionV1),
    Optimizer(String),
    ContextCompiler(String),
    DuplicateContextItem(String),
    PortfolioContextBindingMismatch,
    SelectedRealizationMissing(String),
}

impl fmt::Display for PromptPipelineErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PromptPipelineErrorV1 {}

pub fn compile_exercised_prompt_context_v1(
    registry: &PromptRegistry,
    portfolio: &SelectedPromptPortfolioV1,
    request: PromptContextCompileRequestV1,
) -> Result<PreparedPromptContextV1, PromptPipelineErrorV1> {
    ensure_model_tuple_matches(portfolio, &request.model_profile)?;
    let exercise = exercise_v1(registry, portfolio, request.exercise)
        .map_err(|error| PromptPipelineErrorV1::Optimizer(format!("{error:?}")))?;
    ensure_exercisable(exercise.decision)?;

    let mut candidates = request.base_candidates;
    let mut seen = candidates
        .iter()
        .map(|candidate| candidate.item_id.clone())
        .collect::<BTreeSet<_>>();
    if seen.len() != candidates.len() {
        return Err(PromptPipelineErrorV1::DuplicateContextItem(
            "base candidate".to_owned(),
        ));
    }

    for selected in &portfolio.selected {
        let realization = &selected.realization;
        if !seen.insert(realization.realization_id.clone()) {
            return Err(PromptPipelineErrorV1::DuplicateContextItem(
                realization.realization_id.to_string(),
            ));
        }
        let role = match realization.role {
            PromptRoleV2::ToolSchemaFragment => ContextRoleV2::Schema,
            PromptRoleV2::SystemInstruction
            | PromptRoleV2::DeveloperInstruction
            | PromptRoleV2::UserTemplate => ContextRoleV2::TrustedInstruction,
        };
        let tokenization = TokenizationReceiptV2::new(
            realization.realization_id.clone(),
            realization.payload_digest,
            realization.tokenizer_digest,
            u64::from(realization.token_cost),
        )
        .map_err(|error| PromptPipelineErrorV1::ContextCompiler(format!("{error:?}")))?;
        candidates.push(ContextCandidateV2 {
            item_id: realization.realization_id.clone(),
            role,
            content_digest: realization.payload_digest,
            source_digest: selected.binding_digest,
            generation_vector_digest: portfolio.generation_vector_digest,
            tokenization,
            expected_value: FixedQ32::ONE,
            trusted_admission_digest: Some(selected.binding_digest),
            contains_secret: false,
        });
    }

    let compiled = compile_v2(ContextCompilationRequestV2 {
        compilation_id: request.compilation_id,
        objective_digest: portfolio.objective_digest,
        prompt_portfolio_digest: portfolio.receipt.receipt_digest,
        generation_vector_digest: portfolio.generation_vector_digest,
        model_profile: request.model_profile,
        token_budget: request.token_budget,
        truncation_policy_digest: request.truncation_policy_digest,
        candidates,
        mandatory_groups: request.mandatory_groups,
    })
    .map_err(|error| PromptPipelineErrorV1::ContextCompiler(format!("{error:?}")))?;

    for selected in &portfolio.selected {
        if !compiled
            .receipt
            .selected_item_ids
            .contains(&selected.realization.realization_id)
        {
            return Err(PromptPipelineErrorV1::SelectedRealizationMissing(
                selected.realization.realization_id.to_string(),
            ));
        }
    }
    Ok(PreparedPromptContextV1 { exercise, compiled })
}

pub fn prepare_prompt_delivery_v1(
    registry: &PromptRegistry,
    portfolio: &SelectedPromptPortfolioV1,
    prepared: &PreparedPromptContextV1,
    request: PromptDeliveryPrepareRequestV1,
) -> Result<PreparedPromptDeliveryV1, PromptPipelineErrorV1> {
    if prepared.compiled.receipt.objective_digest != portfolio.objective_digest
        || prepared.compiled.receipt.prompt_portfolio_digest != portfolio.receipt.receipt_digest
        || prepared.compiled.receipt.generation_vector_digest != portfolio.generation_vector_digest
    {
        return Err(PromptPipelineErrorV1::PortfolioContextBindingMismatch);
    }

    // The second check closes the selection->compile->dispatch revocation window.
    let exercise = exercise_v1(registry, portfolio, request.exercise)
        .map_err(|error| PromptPipelineErrorV1::Optimizer(format!("{error:?}")))?;
    ensure_exercisable(exercise.decision)?;

    let serialization = record_serialization(
        &prepared.compiled,
        request.serialization_id,
        request.payload_digest,
    )
    .map_err(|error| PromptPipelineErrorV1::ContextCompiler(format!("{error:?}")))?;
    let attachment = build_attachment(&prepared.compiled, &serialization, request.attachment_id)
        .map_err(|error| PromptPipelineErrorV1::ContextCompiler(format!("{error:?}")))?;
    Ok(PreparedPromptDeliveryV1 {
        exercise,
        serialization,
        attachment,
    })
}

pub fn observe_prompt_delivery_v1(
    prepared: &PreparedPromptDeliveryV1,
    observation_id: StableId,
    observed_payload_digest: Option<Digest32>,
    terminal_observed: bool,
    disposition: ContextDeliveryDispositionV2,
    observed_unix_ms: u64,
) -> Result<ContextDeliveryObservationV2, PromptPipelineErrorV1> {
    observe_delivery(
        &prepared.attachment,
        observation_id,
        observed_payload_digest,
        terminal_observed,
        disposition,
        observed_unix_ms,
    )
    .map_err(|error| PromptPipelineErrorV1::ContextCompiler(format!("{error:?}")))
}

fn ensure_model_tuple_matches(
    portfolio: &SelectedPromptPortfolioV1,
    profile: &ContextModelProfileV2,
) -> Result<(), PromptPipelineErrorV1> {
    if profile.model_digest != portfolio.model_tuple.model_digest
        || profile.tokenizer_digest != portfolio.model_tuple.tokenizer_digest
        || profile.template_digest != portfolio.model_tuple.template_digest
        || profile.tool_schema_digest != portfolio.model_tuple.tool_schema_digest
    {
        return Err(PromptPipelineErrorV1::ModelTupleMismatch);
    }
    Ok(())
}

fn ensure_exercisable(decision: PromptExerciseActionV1) -> Result<(), PromptPipelineErrorV1> {
    match decision {
        PromptExerciseActionV1::Exercise | PromptExerciseActionV1::NoIntervention => Ok(()),
        PromptExerciseActionV1::Wait | PromptExerciseActionV1::RejectStale => {
            Err(PromptPipelineErrorV1::ExerciseRejected(decision))
        }
    }
}

#[cfg(test)]
#[path = "prompt_pipeline_tests.rs"]
mod tests;
