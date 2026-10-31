//! Actual calibrated correctness and NDU moment layers in the inference.control port.
use std::time::Instant;

use codex_hepta_infer_core::NeuronFeatureObservationV1;
use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;
use codex_hepta_infer_core::NeuronModelRuntimeTupleV1;
use codex_hepta_infer_core::build_neuron_feature_receipt_v1;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronModelError;
use codex_hepta_types::Digest32;

use crate::measure;
use crate::value_head::ValueHead;
use codex_hepta_neuron::NeuronRuntimeConfigV1;

pub struct Control {
    pub config: NeuronRuntimeConfigV1,
    pub measured_resident_heap_bytes: usize,
    pub values: ValueHead,
    pub last_moments: Option<Vec<f64>>,
    pub last_raw_probabilities: Option<Vec<f64>>,
    pub forwards: usize,
    pub last_receipt: Option<NeuronFeatureReceiptV1>,
}

impl NeuronInferenceControlPort for Control {
    fn execute_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        let began = Instant::now();
        let baseline = measure::live_bytes();
        let c = &self.config;
        if request.generation != c.generation
            || request.model_id != c.model_id
            || request.encoder_digest != c.encoder_digest
            || request.head_digest != c.head_digest
            || request.weights_digest != c.weights_digest
            || request.expected_output_width != 33
            || request.feature_vector_q24.len() != 103
            || request.input_digest == Digest32::ZERO
        {
            return Err(NeuronModelError::Rejected);
        }
        let moments = self.values.moments(&request.feature_vector_q24)?;
        let (raw, probabilities) = self.values.probabilities(&request.feature_vector_q24)?;
        let action = ValueHead::action(&request.feature_vector_q24)?;
        let mut prediction = vec![0; 33];
        prediction[0] = (probabilities[action] * (1_i64 << 24) as f64).round() as i64;
        self.last_raw_probabilities = Some(raw);
        self.forwards += 1;
        self.last_moments = Some(moments);
        let mut drive = prediction.clone();
        drive[0] = 1 << 24;
        // The other 32 carrier coordinates are explicitly zero, not latent forecasts.
        // The original native error scale exposes the newly qualified probability.
        let receipt = build_neuron_feature_receipt_v1(
            request,
            NeuronModelRuntimeTupleV1 {
                model_id: c.model_id.clone(),
                model_manifest_digest: c.model_manifest_digest,
                weights_digest: c.weights_digest,
                tokenizer_digest: c.tokenizer_digest,
                preprocessor_digest: c.preprocessor_digest,
                quantization_digest: c.quantization_digest,
                runtime_digest: c.runtime_digest,
                device_digest: c.device_digest,
            },
            NeuronFeatureObservationV1 {
                encoder_digest: c.encoder_digest,
                head_digest: c.head_digest,
                drive_q24: drive,
                prediction_q24: prediction,
                observed_memory_bytes: self.measured_resident_heap_bytes as u64,
                transient_allocation_bytes: measure::peak_delta(baseline) as u64,
                queue_age_micros: 0,
                latency_micros: began.elapsed().as_micros() as u64,
                status: NeuronFeatureTerminalStatusV1::Succeeded,
            },
        )
        .map_err(|_| NeuronModelError::Rejected)?;
        self.last_receipt = Some(receipt.clone());
        Ok(receipt)
    }
}
