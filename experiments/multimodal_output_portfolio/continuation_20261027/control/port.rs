//! Actual frozen finite encoder and trained state readout behind inference.control.
use crate::measure;
use crate::Q;
use codex_hepta_infer_core::build_neuron_feature_receipt_v1;
use codex_hepta_infer_core::NeuronFeatureObservationV1;
use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;
use codex_hepta_infer_core::NeuronModelRuntimeTupleV1;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronModelError;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use serde::Deserialize;
use std::time::Instant;

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Model {
    pub schema: String,
    pub weights: Vec<f64>,
}

pub struct Port {
    pub config: NeuronRuntimeConfigV1,
    pub model: Model,
    pub proposed_repair: bool,
    pub logit: f64,
}

pub fn encode(phase: i64, feedback: i64) -> Result<Vec<i64>, NeuronModelError> {
    if !(0..=3).contains(&phase)
        || ![-Q, -Q / 2, 0, Q].contains(&feedback)
        || (phase != 1 && feedback != 0)
    {
        return Err(NeuronModelError::Rejected);
    }
    let mut drive = vec![0; 10];
    if phase == 1 {
        drive[0] = (-feedback).max(0);
        drive[1] = feedback.max(0);
        drive[2] = Q / 4;
    }
    Ok(drive)
}

impl NeuronInferenceControlPort for Port {
    fn execute_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        let start = Instant::now();
        let baseline = measure::start_window();
        let c = &self.config;
        let x = &request.feature_vector_q24;
        if request.generation != c.generation
            || request.model_id != c.model_id
            || request.encoder_digest != c.encoder_digest
            || request.head_digest != c.head_digest
            || request.weights_digest != c.weights_digest
            || request.expected_output_width != 10
            || x.len() != 12
            || !(0..=3).contains(&x[0])
            || ![-Q, -Q / 2, 0, Q].contains(&x[1])
            || (x[0] != 1 && x[1] != 0)
        {
            return Err(NeuronModelError::Rejected);
        }
        let drive = encode(x[0], x[1])?;
        // Prediction concerns exact public encoder validity, not semantic or
        // terminal task success. Terminal-policy predictions are separate.
        let prediction = drive.clone();
        self.logit = self.model.weights[0]
            + x[2..]
                .iter()
                .zip(&self.model.weights[1..])
                .map(|(value, weight)| *value as f64 / Q as f64 * weight)
                .sum::<f64>();
        self.proposed_repair = self.logit >= 0.0;
        build_neuron_feature_receipt_v1(
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
                observed_memory_bytes: measure::live_bytes() as u64,
                transient_allocation_bytes: measure::peak_delta(baseline) as u64,
                queue_age_micros: 0,
                latency_micros: start.elapsed().as_micros() as u64,
                status: NeuronFeatureTerminalStatusV1::Succeeded,
            },
        )
        .map_err(|_| NeuronModelError::Rejected)
    }
}
