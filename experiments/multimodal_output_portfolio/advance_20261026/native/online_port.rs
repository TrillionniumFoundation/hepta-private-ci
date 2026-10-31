//! Original inference.control ABI, executing the actual exported network and kernel.
use crate::{
    control::{Forecast, Kernel, WIDTH},
    measure,
    semantic::Q,
};
use codex_hepta_infer_core::{
    NeuronFeatureObservationV1, NeuronFeatureReceiptV1, NeuronFeatureRequestV1,
    NeuronFeatureTerminalStatusV1, NeuronModelRuntimeTupleV1, build_neuron_feature_receipt_v1,
};
use codex_hepta_neuron::{NeuronInferenceControlPort, NeuronModelError, NeuronRuntimeConfigV1};
use codex_hepta_types::Digest32;
use std::time::Instant;

pub struct Control {
    pub config: NeuronRuntimeConfigV1,
    pub kernel: Kernel,
    pub measured_resident_heap_bytes: usize,
    pub forwards: usize,
    pub last_receipt: Option<NeuronFeatureReceiptV1>,
    pub last_forecast: Option<Forecast>,
    pub cached: Option<(Vec<i64>, Forecast)>,
    pub numeric_modulation: bool,
}
impl Control {
    pub fn forecast(&mut self, x: &[i64]) -> Result<Forecast, NeuronModelError> {
        let mut key = x.to_vec();
        key[178] = 0;
        key[179] = 0;
        key[181..214].fill(0);
        if let Some((old, value)) = &self.cached {
            if *old == key {
                return Ok(value.clone());
            }
        }
        let value = self.kernel.forecast(x)?;
        self.forwards += 1;
        self.cached = Some((key, value.clone()));
        Ok(value)
    }
}
impl NeuronInferenceControlPort for Control {
    fn execute_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        let began = Instant::now();
        let baseline = measure::live_bytes();
        if request.generation != self.config.generation
            || request.model_id != self.config.model_id
            || request.encoder_digest != self.config.encoder_digest
            || request.head_digest != self.config.head_digest
            || request.weights_digest != self.config.weights_digest
            || request.expected_output_width != 33
            || request.feature_vector_q24.len() != WIDTH
            || request.input_digest == Digest32::ZERO
        {
            return Err(NeuronModelError::Rejected);
        }
        let f = self.forecast(&request.feature_vector_q24)?;
        let action = (request.feature_vector_q24[178] / crate::control::INDEX_Q) as usize;
        let mut prediction = vec![0; 33];
        prediction[0] = (f.calibrated[action] * Q as f64).round() as i64;
        // Coordinate 1 is known observed context, not a prediction of future quality.
        // It equals itself in prediction/drive and preserves the correctness residual.
        if self.numeric_modulation {
            prediction[1] = request.feature_vector_q24[179];
        }
        let mut drive = prediction.clone();
        drive[0] = Q;
        self.last_forecast = Some(f);
        let c = &self.config;
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
