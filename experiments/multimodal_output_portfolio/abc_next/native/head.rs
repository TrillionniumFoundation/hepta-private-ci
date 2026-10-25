//! Execute the frozen learned head. Constant-success reference is an explicit
//! confidence adapter; it does not purport to forecast future latent dynamics.
use std::time::Instant;

use codex_hepta_neuron::LocalModelRuntimeReceiptV1;
use codex_hepta_neuron::NeuronModelError;
use codex_hepta_neuron::NeuronModelOutputV1;
use codex_hepta_neuron::NeuronModelPort;
use codex_hepta_neuron::NeuronModelRequestV1;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::canonical_model_output_digest_v1;
use codex_hepta_types::StableId;
use serde::Deserialize;

use crate::measure;

pub const Q: i64 = 1 << 24;

#[derive(Deserialize)]
pub struct Weights {
    pub w1: Vec<Vec<f64>>,
    pub b1: Vec<f64>,
    pub w2: Vec<f64>,
    pub b2: f64,
}
#[derive(Deserialize)]
pub struct Calibration {
    pub cuts: Vec<f64>,
    pub probabilities: Vec<f64>,
}

pub struct LearnedHead {
    pub weights: Weights,
    pub calibration: Calibration,
    pub config: NeuronRuntimeConfigV1,
    pub measured_resident_heap_bytes: usize,
}

impl LearnedHead {
    pub fn probability(&self, x: &[i64]) -> Result<f64, NeuronModelError> {
        if x.len() != 508 || self.weights.w1.len() != 32 || self.weights.b1.len() != 32
            || self.weights.w2.len() != 32 || self.weights.w1.iter().any(|row| row.len() != 508)
            || self.calibration.cuts.len() != 2 || self.calibration.probabilities.len() != 4
        {
            return Err(NeuronModelError::Rejected);
        }
        let mut logit = self.weights.b2;
        for hidden in 0..32 {
            let dot = self.weights.w1[hidden].iter().zip(x).fold(
                self.weights.b1[hidden], |sum, (weight, value)| sum + weight * (*value as f64 / Q as f64));
            logit += self.weights.w2[hidden] * dot.tanh();
        }
        let raw = 1.0 / (1.0 + (-logit).exp());
        let absent = x[480] == 0 && x[481] == 0 && x[492] == Q && x[503] == Q;
        let group = if absent { 3 } else {
            self.calibration.cuts.iter().filter(|cut| raw >= **cut).count()
        };
        let probability = self.calibration.probabilities[group];
        if !probability.is_finite() || !(0.0..=1.0).contains(&probability) {
            return Err(NeuronModelError::Rejected);
        }
        Ok(probability)
    }
}

impl NeuronModelPort for LearnedHead {
    fn execute(&mut self, request: &NeuronModelRequestV1) -> Result<NeuronModelOutputV1, NeuronModelError> {
        let started = Instant::now();
        let baseline = measure::live_bytes();
        let c = &self.config;
        if request.config_id != c.config_id || request.generation != c.generation
            || request.model_id != c.model_id || request.encoder_digest != c.encoder_digest
            || request.head_digest != c.head_digest || request.weights_digest != c.weights_digest
            || request.expected_output_width != c.state_width || request.input_digest.is_zero()
        {
            return Err(NeuronModelError::Rejected);
        }
        let probability = self.probability(&request.feature_vector_q24)?;
        let mut drive_q24 = vec![Q];
        drive_q24.extend_from_slice(&request.feature_vector_q24[..31]);
        let mut prediction_q24 = drive_q24.clone();
        prediction_q24[0] = (probability * Q as f64).round() as i64;
        let runtime_receipt = LocalModelRuntimeReceiptV1 {
            model_id: c.model_id.clone(), model_manifest_digest: c.model_manifest_digest,
            weights_digest: c.weights_digest, tokenizer_digest: c.tokenizer_digest,
            preprocessor_digest: c.preprocessor_digest,
            quantization_id: StableId::new("float64-q24-boundary").map_err(|_| NeuronModelError::Rejected)?,
            quantization_digest: c.quantization_digest,
            backend_id: StableId::new("rust-resident-correctness-v1").map_err(|_| NeuronModelError::Rejected)?,
            runtime_digest: c.runtime_digest, device_identity_digest: c.device_digest,
            latency_micros: started.elapsed().as_micros() as u64,
            resident_bytes: self.measured_resident_heap_bytes as u64,
        };
        let output_digest = canonical_model_output_digest_v1(&drive_q24, &prediction_q24, &runtime_receipt)
            .map_err(|_| NeuronModelError::Rejected)?;
        Ok(NeuronModelOutputV1 {
            encoder_digest: c.encoder_digest, head_digest: c.head_digest, output_digest,
            drive_q24, prediction_q24, queue_age_micros: 0,
            transient_allocation_bytes: measure::peak_delta(baseline) as u64, runtime_receipt,
        })
    }
}
