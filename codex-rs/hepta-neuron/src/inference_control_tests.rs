use super::*;

use codex_hepta_infer_core::NeuronFeatureObservationV1;
use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;
use codex_hepta_infer_core::NeuronModelRuntimeTupleV1;
use codex_hepta_infer_core::build_neuron_feature_receipt_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

const Q: i64 = 1 << 24;

fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

struct Control {
    corrupt_receipt: bool,
    status: NeuronFeatureTerminalStatusV1,
}

impl NeuronInferenceControlPort for Control {
    fn execute_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        let outputs = self.status == NeuronFeatureTerminalStatusV1::Succeeded;
        let mut receipt = checked(build_neuron_feature_receipt_v1(
            request,
            NeuronModelRuntimeTupleV1 {
                model_id: request.model_id.clone(),
                model_manifest_digest: Digest32::of_bytes(b"manifest"),
                weights_digest: request.weights_digest,
                tokenizer_digest: Digest32::of_bytes(b"tokenizer"),
                preprocessor_digest: Digest32::of_bytes(b"preprocessor"),
                quantization_digest: Digest32::of_bytes(b"quantization"),
                runtime_digest: Digest32::of_bytes(b"runtime"),
                device_digest: Digest32::of_bytes(b"device"),
            },
            NeuronFeatureObservationV1 {
                encoder_digest: request.encoder_digest,
                head_digest: request.head_digest,
                drive_q24: if outputs {
                    vec![Q; request.expected_output_width]
                } else {
                    Vec::new()
                },
                prediction_q24: if outputs {
                    vec![0; request.expected_output_width]
                } else {
                    Vec::new()
                },
                observed_memory_bytes: 4096,
                transient_allocation_bytes: 2048,
                queue_age_micros: 3,
                latency_micros: 17,
                status: self.status,
            },
        ));
        if self.corrupt_receipt {
            receipt.receipt_digest = Digest32::of_bytes(b"tampered");
        }
        Ok(receipt)
    }
}

fn request() -> NeuronModelRequestV1 {
    NeuronModelRequestV1 {
        request_id: checked(StableId::new("tick:1")),
        config_id: checked(StableId::new("config:1")),
        generation: checked(Generation::new(1)),
        model_id: checked(StableId::new("model.1")),
        encoder_digest: Digest32::of_bytes(b"encoder"),
        head_digest: Digest32::of_bytes(b"head"),
        weights_digest: Digest32::of_bytes(b"weights"),
        input_digest: Digest32::of_bytes(b"input"),
        feature_vector_q24: vec![Q / 4, -Q / 8],
        expected_output_width: 5,
    }
}

#[test]
fn inference_control_receipt_maps_to_exact_local_runtime_evidence() {
    let mut control = Control {
        corrupt_receipt: false,
        status: NeuronFeatureTerminalStatusV1::Succeeded,
    };
    let mut port = InferenceControlModelPort::new(&mut control);
    let output = checked(port.execute(&request()));
    assert_eq!(
        output.runtime_receipt.model_manifest_digest,
        Digest32::of_bytes(b"manifest")
    );
    assert_eq!(
        output.runtime_receipt.quantization_digest,
        Digest32::of_bytes(b"quantization")
    );
    assert_eq!(
        output.runtime_receipt.runtime_digest,
        Digest32::of_bytes(b"runtime")
    );
    assert_eq!(output.drive_q24, vec![Q; 5]);
}

#[test]
fn corrupted_or_indeterminate_control_receipt_fails_closed() {
    let mut control = Control {
        corrupt_receipt: true,
        status: NeuronFeatureTerminalStatusV1::Succeeded,
    };
    let mut port = InferenceControlModelPort::new(&mut control);
    assert_eq!(port.execute(&request()), Err(NeuronModelError::Rejected));

    let mut control = Control {
        corrupt_receipt: false,
        status: NeuronFeatureTerminalStatusV1::Indeterminate,
    };
    let mut port = InferenceControlModelPort::new(&mut control);
    assert_eq!(
        port.execute(&request()),
        Err(NeuronModelError::Indeterminate)
    );
}
