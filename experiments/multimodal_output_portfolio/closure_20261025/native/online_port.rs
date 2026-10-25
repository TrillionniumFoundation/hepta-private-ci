//! Real frozen-head execution through the existing inference.control contract.
use std::time::Instant;

use codex_hepta_infer_core::{NeuronFeatureObservationV1, NeuronFeatureReceiptV1,
    NeuronFeatureRequestV1, NeuronFeatureTerminalStatusV1, NeuronModelRuntimeTupleV1,
    build_neuron_feature_receipt_v1};
use codex_hepta_neuron::{NeuronInferenceControlPort, NeuronModelError};
use codex_hepta_types::Digest32;

use crate::{future_head::FutureHead, measure};

pub struct Control {
    pub head: FutureHead,
    pub forwards: usize,
    pub last_receipt: Option<NeuronFeatureReceiptV1>,
}

impl NeuronInferenceControlPort for Control {
    fn execute_feature(&mut self, request: &NeuronFeatureRequestV1)
        -> Result<NeuronFeatureReceiptV1, NeuronModelError>
    {
        let began = Instant::now();
        let baseline = measure::live_bytes();
        let c = &self.head.config;
        if request.generation != c.generation || request.model_id != c.model_id
            || request.encoder_digest != c.encoder_digest || request.head_digest != c.head_digest
            || request.weights_digest != c.weights_digest || request.expected_output_width != 33
            || request.feature_vector_q24.len() != 478 || request.input_digest == Digest32::ZERO
        {
            return Err(NeuronModelError::Rejected);
        }
        // The original head's forecast reads only the first 478 coordinates.
        // No observed future is supplied; the compatibility padding is zero.
        let mut prefix = request.feature_vector_q24.clone();
        prefix.resize(510, 0);
        let prediction = self.head.forecast(&prefix)?;
        self.forwards += 1;
        let mut drive = prediction.clone();
        drive[0] = 1 << 24;
        // Both copies of coordinates 1..33 are predictions, not observations.
        // Their cancellation exposes the unchanged calibrated probability only.
        let receipt = build_neuron_feature_receipt_v1(request,
            NeuronModelRuntimeTupleV1 {
                model_id: c.model_id.clone(), model_manifest_digest: c.model_manifest_digest,
                weights_digest: c.weights_digest, tokenizer_digest: c.tokenizer_digest,
                preprocessor_digest: c.preprocessor_digest, quantization_digest: c.quantization_digest,
                runtime_digest: c.runtime_digest, device_digest: c.device_digest,
            },
            NeuronFeatureObservationV1 {
                encoder_digest: c.encoder_digest, head_digest: c.head_digest,
                drive_q24: drive, prediction_q24: prediction,
                observed_memory_bytes: self.head.measured_resident_heap_bytes as u64,
                transient_allocation_bytes: measure::peak_delta(baseline) as u64,
                queue_age_micros: 0, latency_micros: began.elapsed().as_micros() as u64,
                status: NeuronFeatureTerminalStatusV1::Succeeded,
            }).map_err(|_| NeuronModelError::Rejected)?;
        self.last_receipt = Some(receipt.clone());
        Ok(receipt)
    }
}
