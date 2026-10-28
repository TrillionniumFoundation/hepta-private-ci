//! Exact hard bipolar integrate-and-fire evaluation of a trained checkpoint.
use crate::Result;
use codex_hepta_types::Digest32;
use serde::{Deserialize, Serialize};

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Surrogate {
    pub family: String,
    pub mu: f64,
    pub sigma: f64,
    pub lambda: f64,
    pub horizon: f64,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Neural {
    pub schema: String,
    pub feature_schema: String,
    pub weights: Vec<Vec<f64>>,
    pub readout: Vec<f64>,
    pub bias: f64,
    pub thresholds: Vec<f64>,
    pub surrogate: Surrogate,
    pub training_checkpoint_sha256: String,
}

#[derive(Clone, Deserialize, Serialize, PartialEq, Debug)]
#[serde(deny_unknown_fields)]
pub struct NeuralState {
    pub membrane: Vec<f64>,
    pub trace: Vec<f64>,
    pub raw_logit: f64,
    pub elapsed: usize,
}

impl NeuralState {
    pub fn zero() -> Self {
        Self {
            membrane: vec![0.0; 8],
            trace: vec![0.0; 8],
            raw_logit: 0.0,
            elapsed: 0,
        }
    }
}

impl Neural {
    pub fn validate(&self) -> Result<()> {
        let digest: Digest32 = self.training_checkpoint_sha256.parse()?;
        if self.schema != "hepta.adaptive-neuron.snn.v2"
            || self.feature_schema != "bernoulli-six-v1"
            || self.weights.len() != 6
            || self.readout.len() != 8
            || self.thresholds.len() != 8
            || self
                .weights
                .iter()
                .any(|r| r.len() != 8 || r.iter().any(|x| !x.is_finite() || x.abs() > 20.0))
            || self
                .readout
                .iter()
                .any(|x| !x.is_finite() || x.abs() > 20.0)
            || self
                .thresholds
                .iter()
                .any(|x| !x.is_finite() || *x <= 0.0 || *x > 8.0)
            || !self.bias.is_finite()
            || self.bias.abs() > 20.0
            || digest.is_zero()
            || !self.surrogate.mu.is_finite()
            || !self.surrogate.sigma.is_finite()
            || self.surrogate.sigma <= 0.0
            || !self.surrogate.lambda.is_finite()
            || self.surrogate.lambda < 0.0
            || self.surrogate.horizon != 1.0
        {
            return Err("Unsupported or unbound trained SNN checkpoint".into());
        }
        Ok(())
    }

    pub fn step(&self, state: &mut NeuralState, features: &[f64; 6]) -> Result<(f64, usize)> {
        if state.membrane.len() != 8
            || state.trace.len() != 8
            || features.iter().any(|x| !x.is_finite())
        {
            return Err("Invalid spiking state or causal features".into());
        }
        let mut spikes = 0;
        for j in 0..8 {
            let mut current = 0.0;
            for (i, feature) in features.iter().enumerate() {
                current += feature * self.weights[i][j];
            }
            let before = state.membrane[j] + current;
            let signed = if before > self.thresholds[j] {
                1.0
            } else if -before > self.thresholds[j] {
                -1.0
            } else {
                0.0
            };
            spikes += usize::from(signed != 0.0);
            state.membrane[j] = before - self.thresholds[j] * signed;
            state.trace[j] += signed;
        }
        let mut logit = 0.0;
        for j in 0..8 {
            logit += state.trace[j] * self.readout[j];
        }
        logit += self.bias;
        if !logit.is_finite() || state.membrane.iter().any(|x| !x.is_finite()) {
            return Err("Nonfinite trained spiking state".into());
        }
        Ok((logit, spikes))
    }
}
