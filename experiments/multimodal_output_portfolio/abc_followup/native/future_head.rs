//! Causal future-output regression. Only the478 pre-transition coordinates
//! enter the learned forecast;32 observed coordinates enter the residual later.
use std::time::Instant;

use codex_hepta_neuron::*;
use codex_hepta_types::StableId;
use serde::Deserialize;

use crate::measure;

#[cfg(test)]
#[path="future_head_tests.rs"]
mod tests;

const Q: i64 = 1 << 24;

/// Distinguishes real future-state residuals from a probability-only carrier.
#[derive(Clone,Copy,Debug,Default,Deserialize)]
#[serde(rename_all="snake_case")]
pub enum OutputContract {
    #[default]
    StateResidual,
    FutureCorrectness,
}

#[derive(Deserialize)]
pub struct Weights {
    pub w1: Vec<Vec<f64>>,
    pub b1: Vec<f64>,
    pub w2: Vec<Vec<f64>>,
    pub b2: Vec<f64>,
    pub token_state: Vec<Vec<f64>>,
}

#[derive(Deserialize)]
pub struct Calibration {
    pub cuts: Vec<f64>,
    pub probabilities: Vec<f64>,
}

pub struct FutureHead {
    pub weights: Weights,
    pub calibration: Calibration,
    pub config: NeuronRuntimeConfigV1,
    pub contract: OutputContract,
    pub measured_resident_heap_bytes: usize,
}

impl FutureHead {
    pub fn forecast(&self, input: &[i64]) -> Result<Vec<i64>, NeuronModelError> {
        let w = &self.weights;
        if input.len() != 510 || w.w1.len() != 64 || w.b1.len() != 64
            || w.w2.len() != 33 || w.b2.len() != 33
            || w.w1.iter().any(|r| r.len() != 478)
            || w.w2.iter().any(|r| r.len() != 64)
            || w.token_state.len() != 24 || w.token_state.iter().any(|r| r.len() != 8)
            || self.calibration.cuts.len() != 2 || self.calibration.probabilities.len() != 8
        {
            return Err(NeuronModelError::Rejected);
        }
        let x: Vec<f64> = input[..478].iter().map(|v| *v as f64 / Q as f64).collect();
        let hidden: Vec<f64> = w.w1.iter().zip(&w.b1).map(|(row,bias)| {
            row.iter().zip(&x).fold(*bias, |sum,(a,b)| sum+a*b).tanh()
        }).collect();
        let out: Vec<f64> = w.w2.iter().zip(&w.b2).map(|(row,bias)| {
            row.iter().zip(&hidden).fold(*bias,|sum,(a,b)|sum+a*b)
        }).collect();
        let action = usize::from(x[477] > x[476]);
        let raw = 1.0 / (1.0 + (-out[32]).exp());
        let absent = input[448] == 0 && input[449] == 0 && input[460] == Q && input[471] == Q;
        let group = if absent {6+action} else {
            3*action+self.calibration.cuts.iter().filter(|cut|raw >= **cut).count()
        };
        let p = self.calibration.probabilities[group];
        let mut prediction = vec![(p*Q as f64).round() as i64];
        for j in 0..32 {
            let past = match j {
                0..=7 => x[192+j],
                8..=15 => x[224+j-8],
                16..=23 => (0..24).map(|i|x[304+i]*w.token_state[i][j-16]).sum(),
                24..=31 => (0..24).map(|i|x[352+i]*w.token_state[i][j-24]).sum(),
                _ => return Err(NeuronModelError::Rejected),
            };
            let delta = if action == 0 && j < 16 {0.0} else {out[j].tanh()};
            let value = (past+delta).clamp(-1.0,1.0);
            if !value.is_finite() || !p.is_finite() || !(0.0..=1.0).contains(&p) {
                return Err(NeuronModelError::Rejected);
            }
            prediction.push((value*Q as f64).round() as i64);
        }
        Ok(prediction)
    }
}

impl NeuronModelPort for FutureHead {
    fn execute(&mut self, request: &NeuronModelRequestV1) -> Result<NeuronModelOutputV1, NeuronModelError> {
        let started = Instant::now();
        let baseline = measure::live_bytes();
        let c = &self.config;
        if request.config_id != c.config_id || request.generation != c.generation
            || request.model_id != c.model_id || request.encoder_digest != c.encoder_digest
            || request.head_digest != c.head_digest || request.weights_digest != c.weights_digest
            || request.expected_output_width != 33 || request.input_digest.is_zero()
        { return Err(NeuronModelError::Rejected); }
        let mut prediction_q24 = self.forecast(&request.feature_vector_q24)?;
        let mut drive_q24 = vec![Q];
        drive_q24.extend_from_slice(&request.feature_vector_q24[478..510]);
        if matches!(self.contract,OutputContract::FutureCorrectness) {
            // Explicit confidence carrier: these copied observations are never
            // claimed to be latent forecasts. The actual forecast remains the
            // separate result of forecast(), driven only by the prefix.
            prediction_q24[1..].copy_from_slice(&drive_q24[1..]);
        }
        let runtime_receipt = LocalModelRuntimeReceiptV1 {
            model_id:c.model_id.clone(),model_manifest_digest:c.model_manifest_digest,
            weights_digest:c.weights_digest,tokenizer_digest:c.tokenizer_digest,
            preprocessor_digest:c.preprocessor_digest,
            quantization_id:StableId::new("float64-q24-boundary").map_err(|_|NeuronModelError::Rejected)?,
            quantization_digest:c.quantization_digest,
            backend_id:StableId::new("rust-causal-future-output-v1").map_err(|_|NeuronModelError::Rejected)?,
            runtime_digest:c.runtime_digest,device_identity_digest:c.device_digest,
            latency_micros:started.elapsed().as_micros() as u64,
            resident_bytes:self.measured_resident_heap_bytes as u64,
        };
        let output_digest=canonical_model_output_digest_v1(&drive_q24,&prediction_q24,&runtime_receipt)
            .map_err(|_|NeuronModelError::Rejected)?;
        Ok(NeuronModelOutputV1 {encoder_digest:c.encoder_digest,head_digest:c.head_digest,output_digest,
            drive_q24,prediction_q24,queue_age_micros:0,
            transient_allocation_bytes:measure::peak_delta(baseline) as u64,runtime_receipt})
    }
}
