//! Exact frozen teacher final moments and independently qualified H1/H2 admission.
use codex_hepta_neuron::NeuronModelError;
use serde::Deserialize;

const Q: i64 = 1 << 24;

#[derive(Deserialize)]
pub struct Layer {
    weight: Vec<Vec<f64>>,
    bias: Vec<f64>,
}

#[derive(Deserialize)]
pub struct ValueHead {
    schema: String,
    hidden: usize,
    gamma: f64,
    action_cost_already_in_targets: f64,
    actions: Vec<String>,
    heads: Vec<Layer>,
    admission: Admission,
}

#[derive(Deserialize)]
struct Admission {
    predictors: Vec<Layer>,
    strata: Vec<Vec<Stratum>>,
}

#[derive(Deserialize)]
struct Stratum {
    cuts: Vec<f64>,
    probabilities: Vec<f64>,
    absent_probability: f64,
}

impl ValueHead {
    pub fn action(input: &[i64]) -> Result<usize, NeuronModelError> {
        if input.len() != 103 {
            return Err(NeuronModelError::Rejected);
        }
        match (input[4], input[5]) {
            (0, 0) => Ok(0),
            (-16777216, 0) => Ok(1),
            (0, -16777216) => Ok(2),
            (16777216, 0) => Ok(3),
            (0, 16777216) => Ok(4),
            _ => Err(NeuronModelError::Rejected),
        }
    }

    pub fn probabilities(&self, input: &[i64]) -> Result<(Vec<f64>, Vec<f64>), NeuronModelError> {
        let a = &self.admission;
        if input.len() != 103
            || ![Q, 2 * Q].contains(&input[6])
            || a.predictors.len() != 2
            || a.strata.len() != 2
        {
            return Err(NeuronModelError::Rejected);
        }
        let horizon = (input[6] / Q - 1) as usize;
        let head = &a.predictors[horizon];
        if head.weight.len() != 5
            || head.bias.len() != 5
            || head.weight.iter().any(|row| row.len() != 64)
            || a.strata[horizon].len() != 5
        {
            return Err(NeuronModelError::Rejected);
        }
        let absent = input[0] == 0 && input[1] == 0 && input[2] == Q && input[3] == Q;
        let mut raw = Vec::new();
        let mut calibrated = Vec::new();
        for (action, (row, bias)) in head.weight.iter().zip(&head.bias).enumerate() {
            let stratum = &a.strata[horizon][action];
            if stratum.cuts.len() != 2
                || stratum.probabilities.len() != 3
                || stratum.cuts[0] >= stratum.cuts[1]
            {
                return Err(NeuronModelError::Rejected);
            }
            let logit = row
                .iter()
                .zip(&input[39..103])
                .fold(*bias, |sum, (w, x)| sum + w * (*x as f64 / Q as f64));
            let p = 1.0 / (1.0 + (-logit.clamp(-80.0, 80.0)).exp());
            let group = stratum.cuts.iter().filter(|cut| p >= **cut).count();
            let value = if absent {
                stratum.absent_probability
            } else {
                stratum.probabilities[group]
            };
            if !value.is_finite() || !(0.0..=1.0).contains(&value) {
                return Err(NeuronModelError::Rejected);
            }
            raw.push(p);
            calibrated.push(value);
        }
        Ok((raw, calibrated))
    }

    pub fn moments(&self, input: &[i64]) -> Result<Vec<f64>, NeuronModelError> {
        if self.schema != "hepta.next.native-h2-value-layers.v1"
            || self.hidden != 32
            || self.gamma != 2.0
            || self.action_cost_already_in_targets != 0.002
            || self.actions
                != [
                    "stop",
                    "refine_semantic",
                    "refine_image",
                    "refine_text",
                    "couple",
                ]
            || self.heads.len() != 2
            || input.len() != 103
            || ![Q, 2 * Q].contains(&input[6])
            || input[7..103].iter().any(|v| !(-Q..=Q).contains(v))
        {
            return Err(NeuronModelError::Rejected);
        }
        let layer = &self.heads[(input[6] / Q - 1) as usize];
        if layer.weight.len() != 5
            || layer.bias.len() != 5
            || layer.weight.iter().any(|row| row.len() != 32)
        {
            return Err(NeuronModelError::Rejected);
        }
        layer
            .weight
            .iter()
            .zip(&layer.bias)
            .map(|(row, bias)| {
                let raw = row
                    .iter()
                    .zip(&input[7..39])
                    .fold(*bias, |sum, (w, x)| sum + w * (*x as f64 / Q as f64));
                let value = if raw > 20.0 { raw } else { raw.exp().ln_1p() } + 1e-8;
                if value.is_finite() && value > 0.0 {
                    Ok(value)
                } else {
                    Err(NeuronModelError::Rejected)
                }
            })
            .collect()
    }
}
