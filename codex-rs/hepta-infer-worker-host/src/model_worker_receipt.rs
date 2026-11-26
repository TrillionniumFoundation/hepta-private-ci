//! Preserve the existing V1 feature receipt preimage for both worker profiles.
use super::*;

pub(super) fn build_feature_receipt(
    request_copy: NeuronFeatureRequest,
    observed: NeuronFeatureExecutionObservation,
    generation: Generation,
) -> Result<NeuronFeatureReceiptV1, Error> {
    let control_request = NeuronFeatureRequestV1 {
        request_id: StableId::new(request_copy.authorization.request_id)
            .map_err(|_| Error::FeatureContract)?,
        generation,
        model_id: StableId::new(observed.manifest.model_id.clone())
            .map_err(|_| Error::FeatureContract)?,
        encoder_digest: parse_digest32(&request_copy.encoder_digest)?,
        head_digest: parse_digest32(&request_copy.head_digest)?,
        weights_digest: parse_digest32(&request_copy.weights_digest)?,
        input_digest: parse_digest32(&request_copy.input_digest)?,
        feature_vector_q24: request_copy.feature_vector_q24,
        expected_output_width: request_copy.expected_output_width,
    };
    let runtime_tuple = NeuronModelRuntimeTupleV1 {
        model_id: control_request.model_id.clone(),
        model_manifest_digest: parse_digest32(&observed.manifest.model_digest)?,
        weights_digest: parse_digest32(&observed.manifest.weights_digest)?,
        tokenizer_digest: parse_digest32(&observed.manifest.tokenizer_digest)?,
        preprocessor_digest: parse_digest32(&observed.manifest.preprocessor_digest)?,
        quantization_digest: parse_digest32(&observed.manifest.quantization_digest)?,
        runtime_digest: parse_digest32(&observed.manifest.runtime_digest)?,
        device_digest: parse_digest32(&observed.manifest.device_digest)?,
    };
    let status = match observed.status {
        ExecutionStatus::Succeeded => NeuronFeatureTerminalStatusV1::Succeeded,
        ExecutionStatus::Failed => NeuronFeatureTerminalStatusV1::Failed,
        ExecutionStatus::Cancelled => NeuronFeatureTerminalStatusV1::Cancelled,
        ExecutionStatus::Indeterminate => NeuronFeatureTerminalStatusV1::Indeterminate,
    };
    build_neuron_feature_receipt_v1(
        &control_request,
        runtime_tuple,
        NeuronFeatureObservationV1 {
            encoder_digest: parse_digest32(&observed.encoder_digest)?,
            head_digest: parse_digest32(&observed.head_digest)?,
            drive_q24: observed.drive_q24,
            prediction_q24: observed.prediction_q24,
            observed_memory_bytes: observed.observed_memory_bytes,
            transient_allocation_bytes: observed.transient_allocation_bytes,
            queue_age_micros: observed.queue_age_micros,
            latency_micros: observed.latency_micros,
            status,
        },
    )
    .map_err(|_| Error::FeatureContract)
}
