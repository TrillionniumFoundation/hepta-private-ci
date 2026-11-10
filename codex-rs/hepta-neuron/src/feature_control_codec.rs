//! Bounded exact control payload and terminal observation bytes. Runtime pins
//! come from the original frozen definition; a saved digest verifies readback.

use codex_hepta_infer_core::durable_control::Error as ControlError;
use serde::Deserialize;
use serde::Serialize;

use super::*;

pub(super) const MAX_RESULT_BYTES: u32 = 32_768;

pub(super) fn payload(
    request: &NeuronFeatureRequestV1,
    semantic_request: Digest32,
    scope: Digest32,
    predecessor: Digest32,
    admitted_at_micros: u64,
    deadline_micros: u64,
) -> Result<Vec<u8>, NeuronModelError> {
    serde_json::to_vec(&(
        "hepta.neuron.feature-control-input.v1",
        semantic_request.as_array(), scope.as_array(), predecessor.as_array(),
        request.request_id.as_str(), request.generation.get(), request.model_id.as_str(),
        request.encoder_digest.as_array(), request.head_digest.as_array(),
        request.weights_digest.as_array(), request.input_digest.as_array(),
        &request.feature_vector_q24, request.expected_output_width,
        admitted_at_micros, deadline_micros,
    )).map_err(|_| NeuronModelError::Rejected)
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Saved {
    schema_version: u32,
    request_digest: [u8; 32],
    receipt_digest: [u8; 32],
    drive_q24: Vec<i64>,
    prediction_q24: Vec<i64>,
    observed_memory_bytes: u64,
    transient_allocation_bytes: u64,
    queue_age_micros: u64,
    latency_micros: u64,
    status: u8,
}

pub(super) fn encode(receipt: &NeuronFeatureReceiptV1) -> Result<Vec<u8>, NeuronModelError> {
    let status = match receipt.status {
        NeuronFeatureTerminalStatusV1::Succeeded => 1,
        NeuronFeatureTerminalStatusV1::Failed => 2,
        NeuronFeatureTerminalStatusV1::Cancelled => 3,
        NeuronFeatureTerminalStatusV1::Indeterminate => return Err(NeuronModelError::Indeterminate),
    };
    let bytes = serde_json::to_vec(&Saved {
        schema_version: 1,
        request_digest: receipt.request_digest.into_array(),
        receipt_digest: receipt.receipt_digest.into_array(),
        drive_q24: receipt.drive_q24.clone(),
        prediction_q24: receipt.prediction_q24.clone(),
        observed_memory_bytes: receipt.observed_memory_bytes,
        transient_allocation_bytes: receipt.transient_allocation_bytes,
        queue_age_micros: receipt.queue_age_micros,
        latency_micros: receipt.latency_micros,
        status,
    }).map_err(|_| NeuronModelError::Indeterminate)?;
    if bytes.len() > MAX_RESULT_BYTES as usize {
        return Err(NeuronModelError::Indeterminate);
    }
    Ok(bytes)
}

pub(super) fn decode(
    request: &NeuronFeatureRequestV1,
    runtime: &NeuronModelRuntimeTupleV1,
    bytes: &[u8],
) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
    if bytes.len() > MAX_RESULT_BYTES as usize {
        return Err(NeuronModelError::Indeterminate);
    }
    let saved: Saved = serde_json::from_slice(bytes).map_err(|_| NeuronModelError::Indeterminate)?;
    let expected = neuron_feature_request_digest_v1(request).map_err(|_| NeuronModelError::Indeterminate)?;
    if saved.schema_version != 1 || saved.request_digest != expected.into_array() {
        return Err(NeuronModelError::Indeterminate);
    }
    let status = match saved.status {
        1 => NeuronFeatureTerminalStatusV1::Succeeded,
        2 => NeuronFeatureTerminalStatusV1::Failed,
        3 => NeuronFeatureTerminalStatusV1::Cancelled,
        _ => return Err(NeuronModelError::Indeterminate),
    };
    let receipt = build_neuron_feature_receipt_v1(request, runtime.clone(), NeuronFeatureObservationV1 {
        encoder_digest: request.encoder_digest,
        head_digest: request.head_digest,
        drive_q24: saved.drive_q24,
        prediction_q24: saved.prediction_q24,
        observed_memory_bytes: saved.observed_memory_bytes,
        transient_allocation_bytes: saved.transient_allocation_bytes,
        queue_age_micros: saved.queue_age_micros,
        latency_micros: saved.latency_micros,
        status,
    }).map_err(|_| NeuronModelError::Indeterminate)?;
    if receipt.receipt_digest.into_array() != saved.receipt_digest || encode(&receipt)? != bytes {
        return Err(NeuronModelError::Indeterminate);
    }
    Ok(receipt)
}

pub(super) fn control_error(_: ControlError) -> NeuronModelError {
    // No error from an already-contacted original owner proves no execution.
    NeuronModelError::Indeterminate
}
