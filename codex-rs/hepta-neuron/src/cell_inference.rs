//! Durable dispatch admission and read-only recovery of the original request.
//! Backend errors, missing receipts and indeterminate receipts never imply that
//! no compute happened. They retain the admission and cannot enable re-dispatch.

use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;

use crate::InferenceControlModelPort;
use crate::NeuronInferenceControlPort;
use crate::NeuronModelError;
use crate::NeuronModelPort;
use crate::NeuronModelRequestV1;
use crate::cell::CellPreparationModeV1;
use crate::cell::prepare_from_snapshot;
use crate::cell_binding::semantic_request_digest;
use crate::cell_types::*;
use crate::runtime_types::validate_model_output;

/// Implement against the original inference.control owner's persisted request.
/// This method must only inspect that request; it must never submit, reserve or
/// execute work. Missing/failed/indeterminate observations retain Cell pending
/// state. No default implementation claims that absence proves no contact.
pub trait CellInferenceReadbackPortV1 {
    fn read_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<Option<NeuronFeatureReceiptV1>, NeuronModelError>;
}

pub(crate) fn admission_for_step(
    prepared: &PreparedCellStepV1,
    now_micros: u64,
) -> Result<CellInferenceAdmissionV1, CellExecutionError> {
    if now_micros < prepared.input.monotonic_micros || now_micros >= prepared.input.deadline_micros {
        return Err(CellExecutionError::DeadlineExceeded);
    }
    Ok(CellInferenceAdmissionV1 {
        snapshot: prepared.snapshot.clone(),
        operation_id: prepared.input.operation_id.clone(),
        semantic_request_digest: semantic_request_digest(prepared.definition.semantic_digest()?, &prepared.input),
        model_request: prepared.model_request.clone(),
        deadline_micros: prepared.input.deadline_micros,
        admitted_at_micros: now_micros,
    })
}

pub fn infer_cell(
    prepared: PreparedCellStepV1,
    owner: &mut impl CellStateOwnerV1,
    control: &mut impl NeuronInferenceControlPort,
    now_micros: u64,
) -> Result<InferredCellStepV1, CellExecutionError> {
    owner.admit_inference(admission_for_step(&prepared, now_micros)?)?;
    let output = InferenceControlModelPort::new(control)
        .execute(&prepared.model_request)
        .map_err(CellExecutionError::Backend)?;
    validate_model_output(&prepared.definition.runtime, &output)
        .map_err(|_| CellExecutionError::ModelBindingMismatch)?;
    Ok(InferredCellStepV1 { prepared, output })
}

/// Recover only the admitted request. The original raw input must still be
/// supplied by its fact owner. Re-encoding is checked against the persisted full
/// feature request; it cannot change the request or dispatch another computation.
/// After the deadline, decide/commit force abstention while retaining actual cost.
pub fn recover_cell_inference(
    definition: &CellDefinitionV1,
    owner: &impl CellStateOwnerV1,
    encoder: &impl CellInputEncoderV1,
    input: CellStepInputV1,
    readback: &mut impl CellInferenceReadbackPortV1,
    now_micros: u64,
) -> Result<InferredCellStepV1, CellExecutionError> {
    let pending = owner.pending_inference(&input.scope)?
        .ok_or(CellExecutionError::InferenceNotAdmitted)?;
    let digest = semantic_request_digest(definition.semantic_digest()?, &input);
    if pending.operation_id != input.operation_id || pending.semantic_request_digest != digest {
        return Err(CellExecutionError::OperationConflict);
    }
    if owner.snapshot(&input.scope)? != pending.snapshot {
        return Err(CellExecutionError::CommitConflict);
    }
    let prepared = prepare_from_snapshot(
        definition, pending.snapshot, encoder, input, now_micros,
        CellPreparationModeV1::AdmittedRecovery,
    )?;
    if prepared.model_request != pending.model_request || prepared.input.deadline_micros != pending.deadline_micros {
        return Err(CellExecutionError::OperationConflict);
    }
    let request = feature_request(&prepared.model_request);
    let receipt = readback.read_feature(&request)
        .map_err(CellExecutionError::Backend)?
        .ok_or(CellExecutionError::InferencePending)?;
    let mut receipt_port = ReceiptPort(receipt);
    let output = InferenceControlModelPort::new(&mut receipt_port)
        .execute(&prepared.model_request)
        .map_err(CellExecutionError::Backend)?;
    validate_model_output(&prepared.definition.runtime, &output)
        .map_err(|_| CellExecutionError::ModelBindingMismatch)?;
    Ok(InferredCellStepV1 { prepared, output })
}

pub(crate) struct ReceiptPort(pub(crate) NeuronFeatureReceiptV1);

impl NeuronInferenceControlPort for ReceiptPort {
    fn execute_feature(
        &mut self,
        _: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        Ok(self.0.clone())
    }
}

pub(crate) fn feature_request(request: &NeuronModelRequestV1) -> NeuronFeatureRequestV1 {
    NeuronFeatureRequestV1 {
        request_id: request.request_id.clone(),
        generation: request.generation,
        model_id: request.model_id.clone(),
        encoder_digest: request.encoder_digest,
        head_digest: request.head_digest,
        weights_digest: request.weights_digest,
        input_digest: request.input_digest,
        feature_vector_q24: request.feature_vector_q24.clone(),
        expected_output_width: request.expected_output_width,
    }
}

#[cfg(test)]
#[path = "cell_inference_tests.rs"]
mod tests;
