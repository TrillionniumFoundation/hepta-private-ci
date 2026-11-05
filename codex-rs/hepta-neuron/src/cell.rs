//! Native prepare -> shared inference -> legal policy -> owner CAS pipeline.
//! The sparse kernel and calibration are the same mechanisms as NeuronRuntime.

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::InferenceControlModelPort;
use crate::NeuronInferenceControlPort;
use crate::NeuronModelPort;
use crate::NeuronModelRequestV1;
use crate::SparseCheckpoint;
use crate::SparseTick;
use crate::cell_binding::inference_request_id;
use crate::cell_binding::operation_digest;
use crate::cell_binding::semantic_request_digest;
use crate::cell_types::*;
use crate::runtime_types::calibrate;
use crate::runtime_types::validate_model_output;
use crate::sparse_tick;

pub fn prepare_cell_step(
    definition: &CellDefinitionV1,
    owner: &impl CellStateOwnerV1,
    encoder: &impl CellInputEncoderV1,
    input: CellStepInputV1,
    now_micros: u64,
) -> Result<PreparedCellStepV1, CellExecutionError> {
    let definition_digest = definition.semantic_digest()?;
    let request_digest = semantic_request_digest(definition_digest, &input);
    if owner.lookup(&input.scope, &input.operation_id, request_digest)?.is_some() {
        return Err(CellExecutionError::OperationAlreadyCommitted);
    }
    if input.scope.cell_id != definition.cell_id || input.scope.principal_digest.is_zero() {
        return Err(CellExecutionError::ScopeMismatch);
    }
    if input.monotonic_micros == 0
        || input.monotonic_micros > now_micros
        || input.deadline_micros <= now_micros
    {
        return Err(CellExecutionError::DeadlineExceeded);
    }
    if input.observation.len() > definition.max_input_bytes {
        return Err(CellExecutionError::CapacityExceeded);
    }
    if input.objective_digest.is_zero() || input.ndu_snapshot_digest.is_zero() {
        return Err(CellExecutionError::InvalidInput);
    }
    let snapshot = owner.snapshot(&input.scope)?;
    if snapshot.scope != input.scope || snapshot.writer_epoch == 0 {
        return Err(CellExecutionError::ScopeMismatch);
    }
    if snapshot.definition_digest != definition_digest {
        return Err(CellExecutionError::IncompatibleBundle);
    }
    if input.source_frontier.is_zero() || snapshot.source_frontier != input.source_frontier {
        return Err(CellExecutionError::StaleSource);
    }
    if input.candidates.len() != definition.candidates.len()
        || input.candidates.iter().zip(&definition.candidates).any(|(mask, candidate)| {
            mask.candidate_id != candidate.candidate_id
                || (candidate.kind == CellCandidateKindV1::Abstain && !mask.allowed)
        })
    {
        return Err(CellExecutionError::IncompleteCandidates);
    }
    let encoded = encoder.encode(&CellEncodingRequestV1 {
        scope: &input.scope,
        source_frontier: input.source_frontier,
        encoder_digest: definition.runtime.encoder_digest,
        observation: &input.observation,
        checkpoint: snapshot.checkpoint.as_ref(),
    })?;
    if encoded.encoder_digest != definition.runtime.encoder_digest
        || encoded.feature_vector_q24.len() != definition.runtime.input_feature_dimension
        || encoded.feature_vector_q24.iter().any(|v| !(-8 * (1 << 24)..=8 * (1 << 24)).contains(v))
        || encoded.consumed_bytes.checked_add(encoded.truncated_bytes) != Some(input.observation.len())
    {
        return Err(CellExecutionError::EncodingMismatch);
    }
    let r = &definition.runtime;
    let model_request = NeuronModelRequestV1 {
        request_id: inference_request_id(&input)?,
        config_id: r.config_id.clone(),
        generation: r.generation,
        model_id: r.model_id.clone(),
        encoder_digest: r.encoder_digest,
        head_digest: r.head_digest,
        weights_digest: r.weights_digest,
        input_digest: operation_digest(definition_digest, &snapshot, &input, &encoded),
        feature_vector_q24: encoded.feature_vector_q24.clone(),
        expected_output_width: r.state_width,
    };
    Ok(PreparedCellStepV1 {
        definition: definition.clone(),
        snapshot,
        input,
        encoded,
        model_request,
    })
}

/// Entry point for retry-aware hosts. A replay returns the exact committed
/// receipt without calling the encoder, model, numerical kernel or state writer.
pub fn enter_cell_step(
    definition: &CellDefinitionV1,
    owner: &impl CellStateOwnerV1,
    encoder: &impl CellInputEncoderV1,
    input: CellStepInputV1,
    now_micros: u64,
) -> Result<CellStepEntryV1, CellExecutionError> {
    let digest = semantic_request_digest(definition.semantic_digest()?, &input);
    if let Some(receipt) = owner.lookup(&input.scope, &input.operation_id, digest)? {
        return Ok(CellStepEntryV1::Replayed(receipt));
    }
    prepare_cell_step(definition, owner, encoder, input, now_micros).map(CellStepEntryV1::Ready)
}

pub fn infer_cell(
    prepared: PreparedCellStepV1,
    control: &mut impl NeuronInferenceControlPort,
    now_micros: u64,
) -> Result<InferredCellStepV1, CellExecutionError> {
    if now_micros < prepared.input.monotonic_micros || now_micros >= prepared.input.deadline_micros {
        return Err(CellExecutionError::DeadlineExceeded);
    }
    let output = InferenceControlModelPort::new(control)
        .execute(&prepared.model_request)
        .map_err(CellExecutionError::Backend)?;
    validate_model_output(&prepared.definition.runtime, &output)
        .map_err(|_| CellExecutionError::ModelBindingMismatch)?;
    Ok(InferredCellStepV1 { prepared, output })
}

pub fn decide_cell(
    inferred: InferredCellStepV1,
    now_micros: u64,
) -> Result<CellStateProposalV1, CellExecutionError> {
    let InferredCellStepV1 { prepared, output } = inferred;
    let PreparedCellStepV1 { definition, snapshot, input, encoded, model_request } = prepared;
    if now_micros < input.monotonic_micros || now_micros >= input.deadline_micros {
        return Err(CellExecutionError::DeadlineExceeded);
    }
    let sequence = snapshot.checkpoint.as_ref().map_or(0, SparseCheckpoint::sequence)
        .checked_add(1)
        .ok_or(CellExecutionError::CapacityExceeded)?;
    let tick = SparseTick {
        scope_digest: input.scope.digest(),
        objective_digest: input.objective_digest,
        ndu_digest: input.ndu_snapshot_digest,
        body_digest: definition.bundle_digest,
        input_digest: model_request.input_digest,
        sequence,
        monotonic_micros: input.monotonic_micros,
        drive_q24: output.drive_q24.clone(),
        prediction_q24: output.prediction_q24.clone(),
    };
    let (checkpoint, signal) = sparse_tick(&definition.native, &tick, snapshot.checkpoint.as_ref())
        .map_err(|_| CellExecutionError::StateTransitionRejected)?;
    let (confidence_ppm, ood_ppm, calibrated_abstain) =
        calibrate(&definition.runtime.calibration, &signal, sequence)
            .map_err(|_| CellExecutionError::StateTransitionRejected)?;
    let checkpoint_bytes = checkpoint.bounded_encoded_bytes() as u64;
    let resource = &definition.runtime.resource_envelope;
    let over_budget = output.runtime_receipt.latency_micros > resource.p99_latency_micros
        || output.runtime_receipt.resident_bytes > definition.max_resident_bytes
        || output.queue_age_micros > definition.max_queue_age_micros
        || output.transient_allocation_bytes > resource.transient_allocation_bytes
        || checkpoint_bytes > resource.checkpoint_bytes;
    let mut selected = definition.candidates.iter()
        .position(|c| c.kind == CellCandidateKindV1::Abstain)
        .ok_or(CellExecutionError::InvalidDefinition)?;
    if !calibrated_abstain && !over_budget {
        // Canonical order breaks ties. The mask prevents any masked output
        // from being selected; no positive legal signal results in abstention.
        let mut best = 0;
        for (index, (candidate, mask)) in definition.candidates.iter().zip(&input.candidates).enumerate() {
            let score = signal.activation_q24[candidate.activation_index];
            if mask.allowed && score > best {
                best = score;
                selected = index;
            }
        }
    }
    let policy = input.candidates.iter().enumerate().map(|(index, mask)| CellPolicyEntryV1 {
        candidate_id: mask.candidate_id.clone(),
        allowed: mask.allowed,
        probability_ppm: if index == selected { 1_000_000 } else { 0 },
    }).collect();
    let semantic_request_digest = semantic_request_digest(definition.semantic_digest()?, &input);
    let receipt = CellDecisionReceiptV1 {
        operation_id: input.operation_id,
        operation_digest: model_request.input_digest,
        semantic_request_digest,
        scope: input.scope,
        bundle_digest: definition.bundle_digest,
        source_frontier: input.source_frontier,
        checkpoint_before: snapshot.checkpoint.as_ref().map_or(Digest32::ZERO, SparseCheckpoint::digest),
        checkpoint_after: checkpoint.digest(),
        model_output_digest: output.output_digest,
        policy,
        selected_candidate: definition.candidates[selected].candidate_id.clone(),
        confidence_ppm,
        ood_ppm,
        cost: CellExecutionCostV1 {
            model_latency_micros: output.runtime_receipt.latency_micros,
            queue_age_micros: output.queue_age_micros,
            resident_bytes: output.runtime_receipt.resident_bytes,
            transient_allocation_bytes: output.transient_allocation_bytes,
            checkpoint_bytes,
            consumed_input_bytes: encoded.consumed_bytes,
            truncated_input_bytes: encoded.truncated_bytes,
        },
        authority: AuthorityPosture::DENY_ALL,
    };
    Ok(CellStateProposalV1 {
        snapshot,
        checkpoint,
        receipt,
        deadline_micros: input.deadline_micros,
        tick,
    })
}

pub fn commit_cell_step(
    owner: &mut impl CellStateOwnerV1,
    proposal: CellStateProposalV1,
    now_micros: u64,
) -> Result<CellDecisionReceiptV1, CellExecutionError> {
    owner.commit(proposal, now_micros)
}

#[cfg(test)]
#[path = "cell_tests.rs"]
mod tests;
