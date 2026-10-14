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

struct BorrowOnlyControl {
    original_feature_address: *const i64,
    called_borrowed: bool,
    corrupt_receipt: bool,
}

impl NeuronInferenceControlPort for BorrowOnlyControl {
    fn execute_feature(
        &mut self,
        _request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        panic!("legacy owned fallback must not run for opt-in borrowed backend");
    }

    fn execute_feature_view(
        &mut self,
        request: &NeuronFeatureRequestViewV1<'_>,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        assert_eq!(
            self.original_feature_address,
            request.feature_vector_q24.as_ptr()
        );
        self.called_borrowed = true;
        let mut receipt = checked(
            codex_hepta_infer_core::build_neuron_feature_receipt_view_v1(
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
                    drive_q24: vec![Q; request.expected_output_width],
                    prediction_q24: vec![0; request.expected_output_width],
                    observed_memory_bytes: 4096,
                    transient_allocation_bytes: 2048,
                    queue_age_micros: 3,
                    latency_micros: 17,
                    status: NeuronFeatureTerminalStatusV1::Succeeded,
                },
            ),
        );
        if self.corrupt_receipt {
            receipt.receipt_digest = Digest32::of_bytes(b"tampered");
        }
        Ok(receipt)
    }
}

#[test]
fn opt_in_borrowed_control_receives_original_feature_buffer() {
    let original = request();
    let mut control = BorrowOnlyControl {
        original_feature_address: original.feature_vector_q24.as_ptr(),
        called_borrowed: false,
        corrupt_receipt: false,
    };
    let mut port = InferenceControlModelPort::new(&mut control);
    let output = checked(port.execute(&original));
    assert_eq!(output.drive_q24, vec![Q; 5]);
    assert!(control.called_borrowed);
}

#[test]
fn opted_in_borrowed_backend_still_rejects_tampered_receipt() {
    let original = request();
    let mut control = BorrowOnlyControl {
        original_feature_address: original.feature_vector_q24.as_ptr(),
        called_borrowed: false,
        corrupt_receipt: true,
    };
    let mut port = InferenceControlModelPort::new(&mut control);
    assert_eq!(port.execute(&original), Err(NeuronModelError::Rejected));
    assert!(control.called_borrowed);
}
