//! Native counterpart of control/dynamic.py. No target label enters this module.
use crate::semantic::{Q, SemanticHead, validate_law};
use codex_hepta_neuron::NeuronModelError;
use serde::Deserialize;
use std::collections::BTreeMap;

pub const ACQUIRE: usize = 101;
pub const WIDTH: usize = 215;
pub const INDEX_Q: i64 = Q / 128;

#[derive(Deserialize)]
pub struct Curve {
    pub cuts: Vec<f64>,
    pub probabilities: Vec<f64>,
}
#[derive(Deserialize)]
pub struct Calibration {
    pub schema: String,
    pub roles: BTreeMap<String, Curve>,
}
#[derive(Deserialize)]
pub struct Likelihood {
    pub schema: String,
    pub pair_observation_by_target: Vec<Vec<f64>>,
}
#[derive(Clone)]
pub struct Forecast {
    pub law: Vec<f64>,
    pub moments: Vec<f64>,
    pub raw: Vec<f64>,
    pub calibrated: Vec<f64>,
    pub future_actions: Vec<Option<usize>>,
    pub future_rejected_mass: f64,
}

impl Calibration {
    pub fn validate(&self) -> Result<(), NeuronModelError> {
        if self.schema != "hepta.advance.operation-confidence.v1" {
            return Err(NeuronModelError::Rejected);
        }
        for role in ["emit", "acquire", "stop"] {
            let c = self.roles.get(role).ok_or(NeuronModelError::Rejected)?;
            if c.cuts != [0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9]
                || c.probabilities.len() != c.cuts.len() + 1
                || c.probabilities.windows(2).any(|p| p[0] > p[1])
                || c.probabilities
                    .iter()
                    .any(|p| !p.is_finite() || !(0.0..=1.0).contains(p))
            {
                return Err(NeuronModelError::Rejected);
            }
        }
        Ok(())
    }
    pub fn probability(&self, raw: f64, role: &str) -> f64 {
        let c = &self.roles[role];
        c.probabilities[c.cuts.iter().filter(|v| raw >= **v).count()]
    }
}

pub fn admitted(p: f64) -> bool {
    let q = (p * Q as f64).round() as i64;
    1_000_000 - (Q - q).unsigned_abs() * 1_000_000 / Q as u64 >= 750_000
}

impl Likelihood {
    pub fn validate(&self) -> Result<(), NeuronModelError> {
        if self.schema != "hepta.advance.audio-label-likelihood.v1"
            || self.pair_observation_by_target.len() != 100
            || self
                .pair_observation_by_target
                .iter()
                .any(|r| r.len() != 100 || r.iter().any(|p| !p.is_finite() || *p < 0.0))
            || (0..100).any(|t| {
                (self
                    .pair_observation_by_target
                    .iter()
                    .map(|r| r[t])
                    .sum::<f64>()
                    - 1.0)
                    .abs()
                    > 1e-10
            })
        {
            return Err(NeuronModelError::Rejected);
        }
        Ok(())
    }
    pub fn update(&self, law: &[f64], label: usize) -> Result<(Vec<f64>, f64), NeuronModelError> {
        validate_law(law)?;
        let row = self
            .pair_observation_by_target
            .get(label)
            .ok_or(NeuronModelError::Rejected)?;
        let mut posterior: Vec<f64> = row.iter().zip(law).map(|(l, p)| l * p).collect();
        let mass: f64 = posterior.iter().sum();
        if !mass.is_finite() || mass <= 0.0 {
            return Err(NeuronModelError::Rejected);
        }
        posterior.iter_mut().for_each(|p| *p /= mass);
        Ok((posterior, mass))
    }
}

pub struct Kernel {
    pub head: SemanticHead,
    pub calibration: Calibration,
    pub likelihood: Likelihood,
    pub emit_cost: f64,
    pub acquire_cost: f64,
    factors: Vec<Vec<f64>>,
}
impl Kernel {
    pub fn new(
        head: SemanticHead,
        calibration: Calibration,
        likelihood: Likelihood,
        emit_cost: f64,
        acquire_cost: f64,
    ) -> Result<Self, NeuronModelError> {
        head.validate()?;
        calibration.validate()?;
        likelihood.validate()?;
        if (0..100).any(|a| {
            (0..100).any(|t| {
                head.utility_action_by_target[a][t] != if a == t { 1.0 } else { 0.0 }
                    || head.strict_success_action_by_target[a][t] != u8::from(a == t)
            })
        }) {
            return Err(NeuronModelError::Rejected);
        }
        if !emit_cost.is_finite()
            || !acquire_cost.is_finite()
            || emit_cost < 0.0
            || acquire_cost < 0.0
        {
            return Err(NeuronModelError::Rejected);
        }
        let factors = head
            .utility_action_by_target
            .iter()
            .map(|r| {
                r.iter()
                    .map(|u| (-head.gamma * (u - emit_cost)).exp())
                    .collect()
            })
            .collect();
        Ok(Self {
            head,
            calibration,
            likelihood,
            emit_cost,
            acquire_cost,
            factors,
        })
    }
    fn terminal(&self, law: &[f64]) -> (Vec<f64>, Vec<f64>, Vec<f64>, Option<usize>) {
        let moments: Vec<f64> = self
            .factors
            .iter()
            .map(|r| r.iter().zip(law).map(|(u, p)| u * p).sum())
            .collect();
        let raw: Vec<f64> = self
            .head
            .strict_success_action_by_target
            .iter()
            .map(|r| {
                r.iter()
                    .zip(law)
                    .map(|(ok, p)| if *ok == 1 { *p } else { 0.0 })
                    .sum()
            })
            .collect();
        let calibrated: Vec<f64> = raw
            .iter()
            .map(|p| self.calibration.probability(*p, "emit"))
            .collect();
        let selected = (0..100)
            .filter(|i| admitted(calibrated[*i]))
            .min_by(|a, b| moments[*a].total_cmp(&moments[*b]).then(a.cmp(b)));
        (moments, raw, calibrated, selected)
    }
    pub fn forecast(&self, x: &[i64]) -> Result<Forecast, NeuronModelError> {
        if x.len() != WIDTH
            || !(0..=3).contains(&(x[176] / Q))
            || x[176] % Q != 0
            || ![Q, 2 * Q].contains(&x[177])
            || !(0..=101 * INDEX_Q).contains(&x[178])
            || x[178] % INDEX_Q != 0
            || !(-Q..=Q).contains(&x[179])
            || !(0..=100 * INDEX_Q).contains(&x[180])
            || x[180] % INDEX_Q != 0
            || x[181..214].iter().any(|v| !(-4 * Q..=4 * Q).contains(v))
            || ![0, Q].contains(&x[214])
        {
            return Err(NeuronModelError::Rejected);
        }
        if x[214] == Q {
            if x[..176].iter().any(|v| *v != 0) {
                return Err(NeuronModelError::Rejected);
            }
            return Ok(Forecast {
                law: vec![0.01; 100],
                moments: vec![self.head.gamma.exp(); 102],
                raw: vec![0.0; 102],
                calibrated: vec![0.0; 102],
                future_actions: vec![None; 100],
                future_rejected_mass: 1.0,
            });
        }
        let mut law = self.head.posterior(&x[..176], x[176] == Q)?;
        let sum: f64 = law.iter().sum();
        law.iter_mut().for_each(|p| *p /= sum);
        if x[180] > 0 {
            law = self
                .likelihood
                .update(&law, (x[180] / INDEX_Q - 1) as usize)?
                .0;
        }
        let (mut moments, mut raw, mut calibrated, _) = self.terminal(&law);
        moments.push(self.head.gamma.exp());
        raw.push(0.0);
        calibrated.push(0.0); // no actual retained bundle
        let (mut acquisition, mut success, mut rejected) = (0.0, 0.0, 0.0);
        let mut future_actions = vec![None; 100];
        if x[177] == 2 * Q && x[180] == 0 {
            for (o, action) in future_actions.iter_mut().enumerate() {
                let joint: Vec<f64> = law
                    .iter()
                    .zip(&self.likelihood.pair_observation_by_target[o])
                    .map(|(p, l)| p * l)
                    .collect();
                let mass: f64 = joint.iter().sum();
                if mass == 0.0 {
                    continue;
                }
                let posterior: Vec<f64> = joint.iter().map(|p| p / mass).collect();
                let (m, p, _, best) = self.terminal(&posterior);
                *action = best;
                let (v, s) = best.map_or((self.head.gamma.exp(), 0.0), |a| (m[a], p[a]));
                acquisition += mass * (self.head.gamma * self.acquire_cost).exp() * v;
                success += mass * s;
                if best.is_none() {
                    rejected += mass;
                }
            }
        } else {
            acquisition = self.head.gamma.exp();
            rejected = 1.0;
        }
        moments.push(acquisition);
        raw.push(success);
        calibrated.push(if x[177] == 2 * Q && x[180] == 0 {
            self.calibration.probability(success, "acquire")
        } else {
            0.0
        });
        Ok(Forecast {
            law,
            moments,
            raw,
            calibrated,
            future_actions,
            future_rejected_mass: rejected,
        })
    }
}
