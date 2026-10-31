//! Frozen residual MLP execution in Rust, followed by canonical Q24 score conversion.
use crate::contract::id;
use crate::contract::Q;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use std::time::Instant;

#[derive(Clone, Deserialize, Serialize)]
pub struct Normalization {
    pub mean: Vec<f64>,
    pub scale: Vec<f64>,
}
#[derive(Clone, Deserialize, Serialize)]
pub struct Weights {
    pub w: Vec<Vec<f64>>,
    pub b: Vec<f64>,
    pub v: Vec<Vec<f64>>,
    pub c: Vec<f64>,
}
#[derive(Clone, Deserialize, Serialize)]
pub struct Checkpoint {
    pub norm: Normalization,
    pub weights: Weights,
}
impl Checkpoint {
    pub fn validate(&self) -> Result<(), String> {
        let n = self.norm.mean.len();
        let h = self.weights.b.len();
        if n == 0
            || n > 496
            || h == 0
            || h > 1024
            || self.norm.scale.len() != n
            || self.weights.w.len() != n
            || self.weights.w.iter().any(|row| row.len() != h)
            || self.weights.v.len() != h
            || self.weights.v.iter().any(|row| row.len() != 4)
            || self.weights.c.len() != 4
        {
            return Err("checkpoint dimension mismatch".into());
        }
        if self.norm.scale.iter().any(|v| !v.is_finite() || *v <= 0.0)
            || self
                .norm
                .mean
                .iter()
                .chain(&self.weights.b)
                .chain(&self.weights.c)
                .chain(self.weights.w.iter().flatten())
                .chain(self.weights.v.iter().flatten())
                .any(|v| !v.is_finite())
        {
            return Err("nonfinite checkpoint or nonpositive normalization scale".into());
        }
        Ok(())
    }

    pub fn infer(&self, packed: &[i64]) -> Result<([f64; 4], Vec<i64>), String> {
        let n = self.norm.mean.len();
        if packed.len() != n + 8 {
            return Err("packed model width".into());
        }
        let mut hidden = self.weights.b.clone();
        for (i, &feature) in packed[..n].iter().enumerate() {
            let x = ((feature as f64 / Q as f64 - self.norm.mean[i]) / self.norm.scale[i])
                .clamp(-8.0, 8.0);
            for (j, value) in hidden.iter_mut().enumerate() {
                *value += x * self.weights.w[i][j];
            }
        }
        hidden.iter_mut().for_each(|value| *value = value.tanh());
        let mut scores = [0.0; 4];
        for (action, score) in scores.iter_mut().enumerate().skip(1) {
            let mut correction = self.weights.c[action];
            for (j, value) in hidden.iter().enumerate() {
                correction += value * self.weights.v[j][action];
            }
            *score = packed[n + action] as f64 / Q as f64 + correction.max(0.0);
        }
        let mut drive = vec![0; 5];
        for action in 0..4 {
            if packed[n + 4 + action] == Q {
                if !scores[action].is_finite() || !(-4.0..4.0).contains(&scores[action]) {
                    return Err("score outside declared native offset envelope".into());
                }
                drive[action] = ((scores[action] + 4.0) * Q as f64).round() as i64;
            } else if packed[n + 4 + action] != 0 {
                return Err("nonbinary native mask".into());
            }
        }
        Ok((scores, drive))
    }
}

pub struct FrozenModel {
    pub checkpoint: Checkpoint,
    pub config: NeuronRuntimeConfigV1,
    pub checkpoint_bytes: usize,
    pub last_scores: Option<[f64; 4]>,
}
impl NeuronModelPort for FrozenModel {
    fn execute(
        &mut self,
        request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        if request.weights_digest != self.config.weights_digest
            || request.head_digest != self.config.head_digest
            || request.encoder_digest != self.config.encoder_digest
            || request.expected_output_width != 5
        {
            return Err(NeuronModelError::Rejected);
        }
        let start = Instant::now();
        let (scores, drive_q24) = self
            .checkpoint
            .infer(&request.feature_vector_q24)
            .map_err(|_| NeuronModelError::Rejected)?;
        let prediction_q24 = drive_q24.clone();
        let runtime_receipt = LocalModelRuntimeReceiptV1 {
            model_id: self.config.model_id.clone(),
            model_manifest_digest: self.config.model_manifest_digest,
            weights_digest: self.config.weights_digest,
            tokenizer_digest: self.config.tokenizer_digest,
            preprocessor_digest: self.config.preprocessor_digest,
            quantization_id: id("signed.q24").map_err(|_| NeuronModelError::Unavailable)?,
            quantization_digest: self.config.quantization_digest,
            backend_id: id("rust.f64.tanh.residual").map_err(|_| NeuronModelError::Unavailable)?,
            runtime_digest: self.config.runtime_digest,
            device_identity_digest: self.config.device_digest,
            latency_micros: start.elapsed().as_micros().try_into().unwrap_or(u64::MAX),
            resident_bytes: self.checkpoint_bytes as u64,
        };
        let output_digest =
            canonical_model_output_digest_v1(&drive_q24, &prediction_q24, &runtime_receipt)
                .map_err(|_| NeuronModelError::Unavailable)?;
        self.last_scores = Some(scores);
        Ok(NeuronModelOutputV1 {
            encoder_digest: request.encoder_digest,
            head_digest: request.head_digest,
            output_digest,
            drive_q24,
            prediction_q24,
            queue_age_micros: 0,
            transient_allocation_bytes: ((self.checkpoint.weights.b.len() + 10) * size_of::<f64>())
                as u64,
            runtime_receipt,
        })
    }
}

pub fn load(bytes: &[u8]) -> Result<(Checkpoint, Digest32), String> {
    if bytes.len() > 16 * 1024 * 1024 {
        return Err("checkpoint too large".into());
    }
    let checkpoint: Checkpoint =
        serde_json::from_slice(bytes).map_err(|error| error.to_string())?;
    checkpoint.validate()?;
    Ok((checkpoint, Digest32::of_bytes(bytes)))
}
