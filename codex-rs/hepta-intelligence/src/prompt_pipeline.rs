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
    CompiledContextV2, ContextAttachmentV2, ContextCandidateV2, ContextCompilationRequestV2,
    ContextDeliveryDispositionV2, ContextDeliveryObservationV2, ContextModelProfileV2,
    ContextRoleV2, ContextSerializationReceiptV2, MandatoryContextGroupV2, TokenizationReceiptV2,
    build_attachment, compile_v2, observe_delivery, record_serialization,
};
use codex_hepta_prompt_optimizer::canonical::{
    PromptExerciseActionV1, PromptExerciseDecisionV1, PromptExerciseRequestV1,
    SelectedPromptPortfolioV1, exercise_v1,
};
use codex_hepta_prompt_registry::{PromptRealizationPayloadV2, PromptRegistry, PromptRoleV2};
use codex_hepta_types::{AuthorityPosture, Digest32, FixedQ32, StableId};

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
pub struct PromptPayloadMaterializationV1 {
    pub payloads: Vec<PromptRealizationPayloadV2>,
    pub bundle_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl PromptPayloadMaterializationV1 {
    pub fn validate(&self) -> Result<(), PromptPipelineErrorV1> {
        for payload in &self.payloads {
            payload
                .validate()
                .map_err(|error| PromptPipelineErrorV1::Registry(format!("{error:?}")))?;
        }
        if self.authority.grants_any()
            || self.bundle_digest != prompt_payload_bundle_digest(&self.payloads)
        {
            return Err(PromptPipelineErrorV1::PayloadMaterializationDrift);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedPromptContextV1 {
    pub exercise: PromptExerciseDecisionV1,
    pub compiled: CompiledContextV2,
    pub materialization: PromptPayloadMaterializationV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptDeliveryPrepareRequestV1 {
    pub exercise: PromptExerciseRequestV1,
    pub serialization_id: StableId,
    pub serialized_payload: Vec<u8>,
    pub attachment_id: StableId,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptSerializationOccurrenceV1 {
    pub realization_id: StableId,
    pub payload_digest: Digest32,
    pub start_offset: u64,
    pub end_offset: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptSerializationProofV1 {
    pub compilation_receipt_digest: Digest32,
    pub materialization_bundle_digest: Digest32,
    pub serialized_payload_digest: Digest32,
    pub occurrences: Vec<PromptSerializationOccurrenceV1>,
    pub proof_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl PromptSerializationProofV1 {
    pub fn validate(&self) -> Result<(), PromptPipelineErrorV1> {
        if self.compilation_receipt_digest.is_zero()
            || self.materialization_bundle_digest.is_zero()
            || self.serialized_payload_digest.is_zero()
            || self.proof_digest.is_zero()
            || self.authority.grants_any()
        {
            return Err(PromptPipelineErrorV1::SerializationProofDrift);
        }
        let mut previous_end = 0_u64;
        for occurrence in &self.occurrences {
            if occurrence.payload_digest.is_zero()
                || occurrence.start_offset >= occurrence.end_offset
                || occurrence.start_offset < previous_end
            {
                return Err(PromptPipelineErrorV1::SerializationProofDrift);
            }
            previous_end = occurrence.end_offset;
        }
        if self.proof_digest != prompt_serialization_proof_digest(self) {
            return Err(PromptPipelineErrorV1::SerializationProofDrift);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedPromptDeliveryV1 {
    pub exercise: PromptExerciseDecisionV1,
    pub serialization: ContextSerializationReceiptV2,
    pub attachment: ContextAttachmentV2,
    pub materialization: PromptPayloadMaterializationV1,
    pub serialization_proof: PromptSerializationProofV1,
    pub serialized_payload: Vec<u8>,
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
    Registry(String),
    PayloadMaterializationDrift,
    SerializedPayloadMissing(String),
    SerializationProofDrift,
    Arithmetic,
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
    let now_unix_ms = request.exercise.now_unix_ms;
    let exercise = exercise_v1(registry, portfolio, request.exercise)
        .map_err(|error| PromptPipelineErrorV1::Optimizer(format!("{error:?}")))?;
    ensure_exercisable(exercise.decision)?;
    let materialization = materialize_prompt_payloads(registry, portfolio, now_unix_ms)?;

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

    for (selected, payload) in portfolio.selected.iter().zip(&materialization.payloads) {
        let realization = &payload.binding;
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
            content_digest: payload.payload_digest,
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
    Ok(PreparedPromptContextV1 {
        exercise,
        compiled,
        materialization,
    })
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

    let PromptDeliveryPrepareRequestV1 {
        exercise: exercise_request,
        serialization_id,
        serialized_payload,
        attachment_id,
    } = request;

    // The second check closes the selection->compile->dispatch revocation window.
    let now_unix_ms = exercise_request.now_unix_ms;
    let exercise = exercise_v1(registry, portfolio, exercise_request)
        .map_err(|error| PromptPipelineErrorV1::Optimizer(format!("{error:?}")))?;
    ensure_exercisable(exercise.decision)?;

    // Re-read the exact bytes from the current registry snapshot immediately
    // before serialization. A receipt-only match is insufficient: the payload
    // materialization itself must remain byte-for-byte identical.
    let materialization = materialize_prompt_payloads(registry, portfolio, now_unix_ms)?;
    if materialization != prepared.materialization {
        return Err(PromptPipelineErrorV1::PayloadMaterializationDrift);
    }

    // Prove that every selected prompt realization occurs byte-for-byte in the
    // final serialization, in the same relative order as the compiled context.
    // A digest of arbitrary provider bytes is not enough to establish exposure.
    let serialization_proof =
        prove_prompt_serialization(&prepared.compiled, &materialization, &serialized_payload)?;
    let payload_digest = serialization_proof.serialized_payload_digest;
    let serialization = record_serialization(&prepared.compiled, serialization_id, payload_digest)
        .map_err(|error| PromptPipelineErrorV1::ContextCompiler(format!("{error:?}")))?;
    let attachment = build_attachment(&prepared.compiled, &serialization, attachment_id)
        .map_err(|error| PromptPipelineErrorV1::ContextCompiler(format!("{error:?}")))?;
    Ok(PreparedPromptDeliveryV1 {
        exercise,
        serialization,
        attachment,
        materialization,
        serialization_proof,
        serialized_payload,
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

fn materialize_prompt_payloads(
    registry: &PromptRegistry,
    portfolio: &SelectedPromptPortfolioV1,
    now_unix_ms: u64,
) -> Result<PromptPayloadMaterializationV1, PromptPipelineErrorV1> {
    let snapshot = registry
        .snapshot_v2(portfolio.generation_vector_digest, &portfolio.model_tuple)
        .map_err(|error| PromptPipelineErrorV1::Registry(format!("{error:?}")))?;
    let mut payloads = Vec::with_capacity(portfolio.selected.len());
    for selected in &portfolio.selected {
        let payload = registry
            .read_realization_payload_v2(
                &snapshot,
                portfolio.generation_vector_digest,
                &portfolio.model_tuple,
                now_unix_ms,
                &selected.realization.realization_id,
            )
            .map_err(|error| PromptPipelineErrorV1::Registry(format!("{error:?}")))?;
        if payload.binding != selected.realization
            || payload.binding.digest() != selected.binding_digest
            || payload.payload_digest != selected.realization.payload_digest
        {
            return Err(PromptPipelineErrorV1::PayloadMaterializationDrift);
        }
        payloads.push(payload);
    }
    let materialization = PromptPayloadMaterializationV1 {
        bundle_digest: prompt_payload_bundle_digest(&payloads),
        payloads,
        authority: AuthorityPosture::DENY_ALL,
    };
    materialization.validate()?;
    Ok(materialization)
}

fn prove_prompt_serialization(
    compiled: &CompiledContextV2,
    materialization: &PromptPayloadMaterializationV1,
    serialized_payload: &[u8],
) -> Result<PromptSerializationProofV1, PromptPipelineErrorV1> {
    compiled
        .validate()
        .map_err(|error| PromptPipelineErrorV1::ContextCompiler(format!("{error:?}")))?;
    materialization.validate()?;

    let mut cursor = 0_usize;
    let mut occurrences = Vec::with_capacity(materialization.payloads.len());
    for item_id in &compiled.receipt.selected_item_ids {
        let Some(payload) = materialization
            .payloads
            .iter()
            .find(|payload| payload.binding.realization_id == *item_id)
        else {
            continue;
        };
        if payload.payload.is_empty() {
            return Err(PromptPipelineErrorV1::SerializedPayloadMissing(
                item_id.to_string(),
            ));
        }
        let Some(relative_start) = find_subslice(&serialized_payload[cursor..], &payload.payload)
        else {
            return Err(PromptPipelineErrorV1::SerializedPayloadMissing(
                item_id.to_string(),
            ));
        };
        let start = cursor
            .checked_add(relative_start)
            .ok_or(PromptPipelineErrorV1::Arithmetic)?;
        let end = start
            .checked_add(payload.payload.len())
            .ok_or(PromptPipelineErrorV1::Arithmetic)?;
        occurrences.push(PromptSerializationOccurrenceV1 {
            realization_id: item_id.clone(),
            payload_digest: payload.payload_digest,
            start_offset: u64::try_from(start).map_err(|_| PromptPipelineErrorV1::Arithmetic)?,
            end_offset: u64::try_from(end).map_err(|_| PromptPipelineErrorV1::Arithmetic)?,
        });
        cursor = end;
    }
    if occurrences.len() != materialization.payloads.len() {
        return Err(PromptPipelineErrorV1::SerializationProofDrift);
    }

    let mut proof = PromptSerializationProofV1 {
        compilation_receipt_digest: compiled.receipt.receipt_digest,
        materialization_bundle_digest: materialization.bundle_digest,
        serialized_payload_digest: Digest32::of_bytes(serialized_payload),
        occurrences,
        proof_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    proof.proof_digest = prompt_serialization_proof_digest(&proof);
    proof.validate()?;
    Ok(proof)
}

fn prompt_serialization_proof_digest(proof: &PromptSerializationProofV1) -> Digest32 {
    let mut bytes = b"hepta.prompt-pipeline.serialization-proof.v1".to_vec();
    bytes.extend_from_slice(proof.compilation_receipt_digest.as_array());
    bytes.extend_from_slice(proof.materialization_bundle_digest.as_array());
    bytes.extend_from_slice(proof.serialized_payload_digest.as_array());
    push_len(&mut bytes, proof.occurrences.len());
    for occurrence in &proof.occurrences {
        push_id(&mut bytes, &occurrence.realization_id);
        bytes.extend_from_slice(occurrence.payload_digest.as_array());
        bytes.extend_from_slice(&occurrence.start_offset.to_be_bytes());
        bytes.extend_from_slice(&occurrence.end_offset.to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

fn find_subslice(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    if needle.is_empty() {
        return None;
    }
    haystack
        .windows(needle.len())
        .position(|window| window == needle)
}

fn prompt_payload_bundle_digest(payloads: &[PromptRealizationPayloadV2]) -> Digest32 {
    let mut bytes = b"hepta.prompt-pipeline.payload-materialization.v1".to_vec();
    push_len(&mut bytes, payloads.len());
    for payload in payloads {
        push_id(&mut bytes, &payload.binding.factor_id);
        push_id(&mut bytes, &payload.binding.realization_id);
        bytes.extend_from_slice(payload.binding.digest().as_array());
        bytes.extend_from_slice(payload.payload_digest.as_array());
        push_len(&mut bytes, payload.payload.len());
        bytes.extend_from_slice(&payload.payload);
    }
    Digest32::of_bytes(&bytes)
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    bytes.extend_from_slice(&u64::try_from(value).unwrap_or(u64::MAX).to_be_bytes());
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
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
