//! Durable dispatch admission and read-only recovery of the original request.
//! Backend errors, missing receipts and indeterminate receipts never imply that
//! no compute happened. They retain the admission and cannot enable re-dispatch.

use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::neuron_feature_request_digest_v1;

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
    /// Bind the original pending Cell admission for readback only. Implementers
    /// must neither issue another claim nor dispatch during this hook.
    fn bind_cell_readback(
        &mut self,
        _admission: &CellInferenceAdmissionV1,
    ) -> Result<(), NeuronModelError> {
        Ok(())
    }

    fn read_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<Option<NeuronFeatureReceiptV1>, NeuronModelError>;
}

pub(crate) fn admission_for_step(
    prepared: &PreparedCellStepV1,
    now_micros: u64,
) -> Result<CellInferenceAdmissionV1, CellExecutionError> {
    if now_micros < prepared.input.monotonic_micros || now_micros >= prepared.input.deadline_micros
    {
        return Err(CellExecutionError::DeadlineExceeded);
    }
    Ok(CellInferenceAdmissionV1 {
        snapshot: prepared.snapshot.clone(),
        operation_id: prepared.input.operation_id.clone(),
        semantic_request_digest: semantic_request_digest(
            prepared.definition.semantic_digest()?,
            &prepared.input,
        ),
        model_request: prepared.model_request.clone(),
        deadline_micros: prepared.input.deadline_micros,
        admitted_at_micros: now_micros,
        host_queue_age_micros: Some(0),
    })
}

/// Persist dispatch admission before contacting the shared control port.
/// The supplied timestamp bounds admission. Because that durable write may
/// block, the concrete control port must sample its clock and revalidate Cell
/// and enclosing Circuit lease/deadline immediately before native dispatch.
/// A refused dispatch retains pending state and permits only read-only recovery.
/// This compatibility entry reports only the control port's queue time; it does
/// not measure the host admission wait. Use [`infer_cell_with_clock`] when that
/// wait must be included in policy, cost, and recovery.
pub fn infer_cell(
    prepared: PreparedCellStepV1,
    owner: &mut impl CellStateOwnerV1,
    control: &mut impl NeuronInferenceControlPort,
    now_micros: u64,
) -> Result<InferredCellStepV1, CellExecutionError> {
    let admission = admission_for_step(&prepared, now_micros)?;
    owner.admit_inference(admission.clone())?;
    control.bind_cell_inference(&admission).map_err(CellExecutionError::Backend)?;
    let output = InferenceControlModelPort::new(control)
        .execute(&prepared.model_request)
        .map_err(CellExecutionError::Backend)?;
    validate_model_output(&prepared.definition.runtime, &output)
        .map_err(|_| CellExecutionError::ModelBindingMismatch)?;
    Ok(InferredCellStepV1 {
        prepared,
        output,
        not_before_micros: now_micros,
    })
}

/// Measure the host wait across durable admission, then recheck the live Cell
/// deadline and queue bound before native contact. The control port still owns
/// any enclosing Circuit lease and its own queue/dispatch deadline checks.
///
/// The first clock sample starts this entry's host wait; earlier caller queue
/// time is outside this measurement. No durable write separates the second
/// sample from the control call. Persist that original sample even on a native
/// error or invalid receipt. If it cannot be persisted, retain pending state;
/// readback must never replace missing cost with zero or elapsed recovery time.
/// The host must preserve the Cell clock epoch across journal reopen/migration.
pub fn infer_cell_with_clock(
    prepared: PreparedCellStepV1,
    owner: &mut impl CellStateOwnerV1,
    control: &mut impl NeuronInferenceControlPort,
    mut clock_micros: impl FnMut() -> u64,
) -> Result<InferredCellStepV1, CellExecutionError> {
    let request = feature_request(&prepared.model_request);
    let request_digest =
        neuron_feature_request_digest_v1(&request).map_err(|_| CellExecutionError::InvalidInput)?;
    let admitted_at_micros = clock_micros();
    let mut admission = admission_for_step(&prepared, admitted_at_micros)?;
    admission.host_queue_age_micros = None;
    owner.admit_inference(admission.clone())?;
    control.bind_cell_inference(&admission).map_err(CellExecutionError::Backend)?;
    let dispatch_at_micros = clock_micros();
    let host_queue_age_micros = dispatch_at_micros
        .checked_sub(admitted_at_micros)
        .filter(|age| *age <= prepared.definition.max_queue_age_micros)
        .ok_or(CellExecutionError::DeadlineExceeded)?;
    if dispatch_at_micros >= prepared.input.deadline_micros {
        return Err(CellExecutionError::DeadlineExceeded);
    }
    let result = control.execute_feature(&request);
    owner.record_host_queue_age(
        &prepared.input.scope,
        &prepared.input.operation_id,
        request_digest,
        host_queue_age_micros,
    )?;
    let pending = owner
        .pending_inference(&prepared.input.scope)?
        .ok_or(CellExecutionError::InferenceNotAdmitted)?;
    if pending.operation_id != prepared.input.operation_id
        || pending.model_request != prepared.model_request
        || pending.host_queue_age_micros != Some(host_queue_age_micros)
    {
        return Err(CellExecutionError::OperationConflict);
    }
    let mut receipt_port = ReceiptPort(result.map_err(CellExecutionError::Backend)?);
    let mut output = InferenceControlModelPort::new(&mut receipt_port)
        .execute(&prepared.model_request)
        .map_err(CellExecutionError::Backend)?;
    output.queue_age_micros = output
        .queue_age_micros
        .checked_add(host_queue_age_micros)
        .ok_or(CellExecutionError::CapacityExceeded)?;
    validate_model_output(&prepared.definition.runtime, &output)
        .map_err(|_| CellExecutionError::ModelBindingMismatch)?;
    Ok(InferredCellStepV1 {
        prepared,
        output,
        not_before_micros: dispatch_at_micros,
    })
}

/// Recover only the admitted request. The original raw input must still be
/// supplied by its fact owner. Re-encoding is checked against the persisted full
/// feature request; it cannot change the request or dispatch another computation.
/// After the deadline, decide/commit force abstention while retaining actual cost.
/// Missing host queue measurements retain pending state without reading or
/// repeating native work. Recovery time is never substituted for actual usage.
pub fn recover_cell_inference(
    definition: &CellDefinitionV1,
    owner: &impl CellStateOwnerV1,
    encoder: &impl CellInputEncoderV1,
    input: CellStepInputV1,
    readback: &mut impl CellInferenceReadbackPortV1,
    now_micros: u64,
) -> Result<InferredCellStepV1, CellExecutionError> {
    let pending = owner
        .pending_inference(&input.scope)?
        .ok_or(CellExecutionError::InferenceNotAdmitted)?;
    if now_micros < pending.admitted_at_micros {
        return Err(CellExecutionError::DeadlineExceeded);
    }
    let digest = semantic_request_digest(definition.semantic_digest()?, &input);
    if pending.operation_id != input.operation_id || pending.semantic_request_digest != digest {
        return Err(CellExecutionError::OperationConflict);
    }
    if owner.snapshot(&input.scope)? != pending.snapshot {
        return Err(CellExecutionError::CommitConflict);
    }
    let prepared = prepare_from_snapshot(
        definition,
        pending.snapshot.clone(),
        encoder,
        input,
        now_micros,
        CellPreparationModeV1::AdmittedRecovery,
    )?;
    if prepared.model_request != pending.model_request
        || prepared.input.deadline_micros != pending.deadline_micros
    {
        return Err(CellExecutionError::OperationConflict);
    }
    let host_queue_age_micros = pending
        .host_queue_age_micros
        .ok_or(CellExecutionError::UnmeasuredQueueCost)?;
    let request = feature_request(&prepared.model_request);
    readback.bind_cell_readback(&pending).map_err(CellExecutionError::Backend)?;
    let receipt = readback
        .read_feature(&request)
        .map_err(CellExecutionError::Backend)?
        .ok_or(CellExecutionError::InferencePending)?;
    let mut receipt_port = ReceiptPort(receipt);
    let mut output = InferenceControlModelPort::new(&mut receipt_port)
        .execute(&prepared.model_request)
        .map_err(CellExecutionError::Backend)?;
    output.queue_age_micros = output
        .queue_age_micros
        .checked_add(host_queue_age_micros)
        .ok_or(CellExecutionError::CapacityExceeded)?;
    validate_model_output(&prepared.definition.runtime, &output)
        .map_err(|_| CellExecutionError::ModelBindingMismatch)?;
    Ok(InferredCellStepV1 {
        prepared,
        output,
        not_before_micros: now_micros,
    })
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
