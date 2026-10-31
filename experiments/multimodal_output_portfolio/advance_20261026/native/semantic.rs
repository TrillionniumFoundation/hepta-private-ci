//! Exact exported posterior network and actual-output finite utility table.
//! Target indices here enumerate the registered outcome space, never a hidden label.
use codex_hepta_neuron::NeuronModelError;
use serde::Deserialize;

pub const Q: i64 = 1 << 24;
pub const FEATURES: usize = 176;
pub const ACTIONS: usize = 100;

#[derive(Deserialize)]
pub struct Parameters {
    #[serde(rename = "first.weight")]
    first_weight: Vec<Vec<f64>>,
    #[serde(rename = "first.bias")]
    first_bias: Vec<f64>,
    #[serde(rename = "last.weight")]
    last_weight: Vec<Vec<f64>>,
    #[serde(rename = "last.bias")]
    last_bias: Vec<f64>,
}

#[derive(Deserialize)]
pub struct SemanticHead {
    schema: String,
    features_per_digit: usize,
    hidden: usize,
    activation: String,
    residual_bound: f64,
    raw_probability_floor: f64,
    text_route_bypasses_adapter: bool,
    pub parameter_sha256: String,
    state_dict: Parameters,
    pub utility_action_by_target: Vec<Vec<f64>>,
    pub strict_success_action_by_target: Vec<Vec<u8>>,
    pub gamma: f64,
    action_code: String,
    pub endpoint_table_sha256: String,
}

impl SemanticHead {
    pub fn validate(&self) -> Result<(), NeuronModelError> {
        let p = &self.state_dict;
        if self.schema != "hepta.advance.semantic-adapter-native.v1"
            || self.features_per_digit != 78
            || self.hidden != 32
            || self.activation != "tanh"
            || ![2.0, 8.0].contains(&self.residual_bound)
            || self.raw_probability_floor != 1e-8
            || !self.text_route_bypasses_adapter
            || self.gamma != 2.0
            || self.action_code != "left*10+right"
            || p.first_weight.len() != 32
            || p.first_bias.len() != 32
            || p.first_weight.iter().any(|r| r.len() != 78)
            || p.last_weight.len() != 10
            || p.last_bias.len() != 10
            || p.last_weight.iter().any(|r| r.len() != 32)
            || self.utility_action_by_target.len() != ACTIONS
            || self.strict_success_action_by_target.len() != ACTIONS
            || self.utility_action_by_target.iter().any(|r| {
                r.len() != ACTIONS || r.iter().any(|u| !u.is_finite() || !(0.0..=1.0).contains(u))
            })
            || self
                .strict_success_action_by_target
                .iter()
                .any(|r| r.len() != ACTIONS || r.iter().any(|v| *v > 1))
            || p.first_weight
                .iter()
                .flatten()
                .chain(&p.first_bias)
                .chain(p.last_weight.iter().flatten())
                .chain(&p.last_bias)
                .any(|v| !v.is_finite())
        {
            return Err(NeuronModelError::Rejected);
        }
        Ok(())
    }

    pub fn posterior(&self, features: &[i64], text: bool) -> Result<Vec<f64>, NeuronModelError> {
        if features.len() != FEATURES
            || features[..156]
                .iter()
                .any(|x| !(-4 * Q..=4 * Q).contains(x))
            || features[156..].iter().any(|x| !(0..=Q).contains(x))
        {
            return Err(NeuronModelError::Rejected);
        }
        let mut probabilities = Vec::with_capacity(2);
        for slot in 0..2 {
            let raw: Vec<f64> = features[156 + slot * 10..166 + slot * 10]
                .iter()
                .map(|x| *x as f64 / Q as f64)
                .collect();
            if (raw.iter().sum::<f64>() - 1.0).abs() > 1e-5 {
                return Err(NeuronModelError::Rejected);
            }
            if text {
                probabilities.push(raw);
                continue;
            }
            let x = &features[slot * 78..(slot + 1) * 78];
            let h: Vec<f64> = self
                .state_dict
                .first_weight
                .iter()
                .zip(&self.state_dict.first_bias)
                .map(|(w, b)| {
                    w.iter()
                        .zip(x)
                        .fold(*b, |s, (w, x)| s + w * (*x as f64 / Q as f64))
                        .tanh()
                })
                .collect();
            let mut logits: Vec<f64> = self
                .state_dict
                .last_weight
                .iter()
                .zip(&self.state_dict.last_bias)
                .enumerate()
                .map(|(k, (w, b))| {
                    raw[k].max(self.raw_probability_floor).ln()
                        + self.residual_bound
                            * w.iter().zip(&h).fold(*b, |s, (w, h)| s + w * h).tanh()
                })
                .collect();
            let maximum = logits.iter().copied().fold(f64::NEG_INFINITY, f64::max);
            logits.iter_mut().for_each(|x| *x = (*x - maximum).exp());
            let mass: f64 = logits.iter().sum();
            logits.iter_mut().for_each(|x| *x /= mass);
            probabilities.push(logits);
        }
        Ok((0..100)
            .map(|t| probabilities[0][t / 10] * probabilities[1][t % 10])
            .collect())
    }

    pub fn moments(&self, law: &[f64], cost: f64) -> Result<Vec<f64>, NeuronModelError> {
        validate_law(law)?;
        if !cost.is_finite() || cost < 0.0 {
            return Err(NeuronModelError::Rejected);
        }
        Ok(self
            .utility_action_by_target
            .iter()
            .map(|row| {
                row.iter()
                    .zip(law)
                    .map(|(u, p)| p * (-self.gamma * (u - cost)).exp())
                    .sum()
            })
            .collect())
    }

    pub fn success(&self, law: &[f64]) -> Result<Vec<f64>, NeuronModelError> {
        validate_law(law)?;
        Ok(self
            .strict_success_action_by_target
            .iter()
            .map(|row| {
                row.iter()
                    .zip(law)
                    .map(|(ok, p)| if *ok == 1 { *p } else { 0.0 })
                    .sum()
            })
            .collect())
    }
}

pub fn validate_law(law: &[f64]) -> Result<(), NeuronModelError> {
    if law.len() != 100
        || law.iter().any(|x| !x.is_finite() || *x < 0.0)
        || (law.iter().sum::<f64>() - 1.0).abs() > 1e-5
    {
        return Err(NeuronModelError::Rejected);
    }
    Ok(())
}
