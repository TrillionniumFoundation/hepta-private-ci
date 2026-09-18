//! Typed handoff from canonical prompt compilation to runtime delivery and
//! learning-ledger exposure admission.
//!
//! This module never observes delivery itself. A runtime-owned caller must
//! supply the terminal delivery observation.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_context_compiler::{
    ContextAttachmentV2, ContextCompilerV2Error, ContextDeliveryDispositionV2,
    ContextDeliveryObservationV2, ContextSerializationReceiptV2, build_attachment,
    record_serialization,
};
use codex_hepta_learning_ledger::{
    CausalV2Error, PromptPortfolioExposureReceiptV1, PromptPortfolioExposureV1,
    validate_prompt_portfolio_exposure,
};
use codex_hepta_prompt_optimizer::canonical::ExerciseDispositionV1;
use codex_hepta_types::{Digest32, StableId};

use crate::CanonicalPromptContextReceiptV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalPromptAttachmentReceiptV1 {
    pub serialization: ContextSerializationReceiptV2,
    pub attachment: ContextAttachmentV2,
}

#[derive(Debug)]
pub enum CanonicalPromptDeliveryErrorV1 {
    Context(ContextCompilerV2Error),
    Learning(CausalV2Error),
    PromptNotExercised,
    CompilationMismatch,
    DeliveryNotTerminal,
    DeliveredPayloadMissing,
}

impl fmt::Display for CanonicalPromptDeliveryErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for CanonicalPromptDeliveryErrorV1 {}

pub fn prepare_canonical_prompt_attachment_v1(
    pipeline: &CanonicalPromptContextReceiptV1,
    serialization_id: StableId,
    attachment_id: StableId,
    payload_digest: Digest32,
) -> Result<CanonicalPromptAttachmentReceiptV1, CanonicalPromptDeliveryErrorV1> {
    if pipeline.exercise.disposition != ExerciseDispositionV1::Exercise {
        return Err(CanonicalPromptDeliveryErrorV1::PromptNotExercised);
    }
    if pipeline.context.receipt.prompt_portfolio_digest != pipeline.portfolio.receipt_digest {
        return Err(CanonicalPromptDeliveryErrorV1::CompilationMismatch);
    }
    let serialization =
        record_serialization(&pipeline.context, serialization_id, payload_digest)
            .map_err(CanonicalPromptDeliveryErrorV1::Context)?;
    let attachment = build_attachment(&pipeline.context, &serialization, attachment_id)
        .map_err(CanonicalPromptDeliveryErrorV1::Context)?;
    Ok(CanonicalPromptAttachmentReceiptV1 {
        serialization,
        attachment,
    })
}

pub fn admit_canonical_prompt_delivery_v1(
    pipeline: &CanonicalPromptContextReceiptV1,
    handoff: &CanonicalPromptAttachmentReceiptV1,
    delivery: &ContextDeliveryObservationV2,
    exposure_id: StableId,
    episode_id: StableId,
) -> Result<PromptPortfolioExposureReceiptV1, CanonicalPromptDeliveryErrorV1> {
    if pipeline.exercise.disposition != ExerciseDispositionV1::Exercise {
        return Err(CanonicalPromptDeliveryErrorV1::PromptNotExercised);
    }
    handoff
        .serialization
        .validate_for(&pipeline.context)
        .map_err(CanonicalPromptDeliveryErrorV1::Context)?;
    handoff
        .attachment
        .validate(&pipeline.context, &handoff.serialization)
        .map_err(CanonicalPromptDeliveryErrorV1::Context)?;
    delivery
        .validate_for(&handoff.attachment)
        .map_err(CanonicalPromptDeliveryErrorV1::Context)?;
    if delivery.disposition != ContextDeliveryDispositionV2::Delivered
        || !delivery.terminal_observed
    {
        return Err(CanonicalPromptDeliveryErrorV1::DeliveryNotTerminal);
    }
    let Some(observed_payload_digest) = delivery.observed_payload_digest else {
        return Err(CanonicalPromptDeliveryErrorV1::DeliveredPayloadMissing);
    };
    if pipeline.context.receipt.receipt_digest != handoff.attachment.compilation_receipt_digest
        || delivery.expected_payload_digest != handoff.serialization.payload_digest
    {
        return Err(CanonicalPromptDeliveryErrorV1::CompilationMismatch);
    }

    validate_prompt_portfolio_exposure(&PromptPortfolioExposureV1 {
        exposure_id,
        episode_id,
        objective_digest: pipeline.candidates.objective_digest,
        candidate_set_digest: pipeline.candidates.receipt_digest,
        pricing_receipt_digest: pipeline.pricing.receipt_digest,
        portfolio_receipt_digest: pipeline.portfolio.receipt_digest,
        exercise_receipt_digest: pipeline.exercise.receipt_digest,
        context_compilation_receipt_digest: pipeline.context.receipt.receipt_digest,
        delivery_observation_digest: delivery.observation_digest,
        selected_factor_ids: pipeline.portfolio.selected_factor_ids.clone(),
        selected_realization_ids: pipeline.portfolio.selected_realization_ids.clone(),
        observed_payload_digest,
        observed_unix_ms: delivery.observed_unix_ms,
    })
    .map_err(CanonicalPromptDeliveryErrorV1::Learning)
}
