use super::*;

use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn request() -> NeuronFeatureRequestV1 {
    NeuronFeatureRequestV1 {
        request_id: checked(StableId::new("request:neuron:1")),
        generation: checked(Generation::new(3)),
        model_id: checked(StableId::new("model.1")),
        encoder_digest: Digest32::of_bytes(b"encoder"),
        head_digest: Digest32::of_bytes(b"head"),
        weights_digest: Digest32::of_bytes(b"weights"),
        input_digest: Digest32::of_bytes(b"input"),
        feature_vector_q24: vec![Q / 4, -Q / 8],
        expected_output_width: 5,
    }
}

fn runtime() -> NeuronModelRuntimeTupleV1 {
    NeuronModelRuntimeTupleV1 {
        model_id: checked(StableId::new("model.1")),
        model_manifest_digest: Digest32::of_bytes(b"manifest"),
        weights_digest: Digest32::of_bytes(b"weights"),
        tokenizer_digest: Digest32::of_bytes(b"tokenizer"),
        preprocessor_digest: Digest32::of_bytes(b"preprocessor"),
        quantization_digest: Digest32::of_bytes(b"quantization"),
        runtime_digest: Digest32::of_bytes(b"runtime"),
        device_digest: Digest32::of_bytes(b"device"),
    }
}

fn observation() -> NeuronFeatureObservationV1 {
    NeuronFeatureObservationV1 {
        encoder_digest: Digest32::of_bytes(b"encoder"),
        head_digest: Digest32::of_bytes(b"head"),
        drive_q24: vec![Q, Q / 2, 0, 0, 0],
        prediction_q24: vec![0; 5],
        observed_memory_bytes: 4096,
        transient_allocation_bytes: 2048,
        queue_age_micros: 7,
        latency_micros: 23,
        status: NeuronFeatureTerminalStatusV1::Succeeded,
    }
}

#[test]
fn successful_receipt_binds_request_runtime_output_and_denies_authority() {
    let request = request();
    let receipt = checked(build_neuron_feature_receipt_v1(
        &request,
        runtime(),
        observation(),
    ));
    checked(verify_neuron_feature_receipt_v1(&request, &receipt));
    assert!(!receipt.request_digest.is_zero());
    assert!(!receipt.runtime_tuple_digest.is_zero());
    assert!(!receipt.output_digest.is_zero());
    assert!(!receipt.receipt_digest.is_zero());
    assert!(!receipt.authority.grants_any());
}

#[test]
fn runtime_tuple_or_output_identity_drift_is_rejected() {
    let request = request();
    let mut tuple = runtime();
    tuple.weights_digest = Digest32::of_bytes(b"other-weights");
    assert_eq!(
        build_neuron_feature_receipt_v1(&request, tuple, observation()),
        Err(NeuronFeatureContractError::RuntimeBindingMismatch)
    );

    let mut observed = observation();
    observed.head_digest = Digest32::of_bytes(b"other-head");
    assert_eq!(
        build_neuron_feature_receipt_v1(&request, runtime(), observed),
        Err(NeuronFeatureContractError::OutputIdentityMismatch)
    );
}

#[test]
fn non_success_status_cannot_smuggle_numerical_output() {
    let request = request();
    let mut observed = observation();
    observed.status = NeuronFeatureTerminalStatusV1::Indeterminate;
    assert_eq!(
        build_neuron_feature_receipt_v1(&request, runtime(), observed),
        Err(NeuronFeatureContractError::NonTerminalOutputPresent)
    );

    let mut observed = observation();
    observed.status = NeuronFeatureTerminalStatusV1::Indeterminate;
    observed.drive_q24.clear();
    observed.prediction_q24.clear();
    let receipt = checked(build_neuron_feature_receipt_v1(
        &request,
        runtime(),
        observed,
    ));
    assert_eq!(receipt.status, NeuronFeatureTerminalStatusV1::Indeterminate);
}
