//! Frozen finite-state stopping readout through the genuine inference-control port.
use crate::measure;
use crate::Result;
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
use serde::Serialize;
use std::time::Instant;

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Model {
    pub schema: String,
    pub profile_id: String,
    pub transition_kind: String,
    pub evidence_scope: String,
    pub states: Vec<f64>,
    pub dt: f64,
    pub mu: f64,
    pub sigma: f64,
    pub rho: f64,
    pub killing_rate: f64,
    pub payoff_cost: f64,
    pub running_cost: f64,
    pub value: Vec<Vec<f64>>,
    pub continuation: Vec<Vec<f64>>,
    pub stop_value: Vec<f64>,
    pub action: Vec<Vec<Action>>,
    pub transition: Vec<Vec<f64>>,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum Action {
    Stop,
    Continue,
    Abstain,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Policy {
    FreeBoundary,
    ExactDp,
    ConstantThreshold { lower: f64, upper: f64 },
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Readout {
    pub action: Action,
    pub stop_value: f64,
    pub continuation: f64,
    pub value: f64,
    pub bellman_terms: usize,
}

pub fn best_action(stop: f64, continuation: f64, remaining: usize) -> Action {
    if stop.max(continuation) <= 0.0 {
        Action::Abstain
    } else if remaining == 0 || stop >= continuation {
        Action::Stop
    } else {
        Action::Continue
    }
}

impl Model {
    pub fn validate(&self) -> Result<()> {
        let n = self.states.len();
        if self.schema != "hepta.free-boundary.readout.v1"
            || self.profile_id.is_empty()
            || self.transition_kind != "survival_weighted_gaussian_bins"
            || self.evidence_scope != "engineering_correctness_only"
            || !(3..=201).contains(&n)
            || !(2..=65).contains(&self.value.len())
            || self.stop_value.len() != n
            || self.transition.len() != n
            || self.continuation.len() != self.value.len()
            || self.action.len() != self.value.len()
            || self.states.iter().any(|x| !x.is_finite() || x.abs() > 7.0)
            || self.states.windows(2).any(|x| x[0] >= x[1])
            || [self.dt, self.sigma]
                .iter()
                .any(|x| !x.is_finite() || *x <= 0.0)
            || [self.rho, self.killing_rate, self.running_cost]
                .iter()
                .any(|x| !x.is_finite() || *x < 0.0)
            || !self.mu.is_finite()
            || !self.payoff_cost.is_finite()
            || self.dt * (self.value.len() - 1) as f64 > 7.0
        {
            return Err("Unsupported finite stopping profile".into());
        }
        for row in &self.transition {
            if row.len() != n
                || row.iter().any(|x| !x.is_finite() || *x < 0.0)
                || (row.iter().sum::<f64>() - (-self.killing_rate * self.dt).exp()).abs() > 1e-12
            {
                return Err("Invalid survival-weighted transition row".into());
            }
        }
        for t in 0..self.value.len() {
            if self.value[t].len() != n
                || self.continuation[t].len() != n
                || self.action[t].len() != n
            {
                return Err("Inconsistent value-table shape".into());
            }
            for i in 0..n {
                let expected = self.readout(i, t, &Policy::ExactDp)?;
                if !self.value[t][i].is_finite()
                    || !self.continuation[t][i].is_finite()
                    || (self.stop_value[i] - (self.states[i] - self.payoff_cost)).abs() > 1e-12
                    || (self.value[t][i] - expected.value).abs() > 1e-12
                    || (self.continuation[t][i] - expected.continuation).abs() > 1e-12
                    || self.action[t][i] != expected.action
                {
                    return Err(format!("Bellman/profile mismatch at {t}/{i}").into());
                }
            }
        }
        Ok(())
    }

    pub fn readout(&self, i: usize, t: usize, policy: &Policy) -> Result<Readout> {
        if i >= self.states.len() || t >= self.value.len() {
            return Err("Observation outside registered finite domain".into());
        }
        let stop = self.stop_value[i];
        let (action, continuation, terms) = match policy {
            Policy::FreeBoundary => (self.action[t][i], self.continuation[t][i], 0),
            Policy::ExactDp => {
                let continuation = if t == 0 {
                    0.0
                } else {
                    -self.running_cost * self.dt
                        + (-self.rho * self.dt).exp()
                            * self.transition[i]
                                .iter()
                                .zip(&self.value[t - 1])
                                .map(|(p, v)| p * v)
                                .sum::<f64>()
                };
                (
                    best_action(stop, continuation, t),
                    continuation,
                    if t == 0 { 0 } else { self.states.len() },
                )
            }
            Policy::ConstantThreshold { lower, upper } => {
                if !lower.is_finite()
                    || !upper.is_finite()
                    || *lower > self.payoff_cost
                    || *upper < self.payoff_cost
                {
                    return Err("Invalid constant stopping/abstention threshold pair".into());
                }
                let action = if t == 0 {
                    if stop > 0.0 {
                        Action::Stop
                    } else {
                        Action::Abstain
                    }
                } else if self.states[i] <= *lower {
                    Action::Abstain
                } else if self.states[i] >= *upper {
                    if stop > 0.0 {
                        Action::Stop
                    } else {
                        Action::Abstain
                    }
                } else {
                    Action::Continue
                };
                (action, self.continuation[t][i], 0)
            }
        };
        Ok(Readout {
            action,
            stop_value: stop,
            continuation,
            value: stop.max(continuation).max(0.0),
            bellman_terms: terms,
        })
    }

    pub fn features(&self, state: usize, remaining: usize) -> Result<Vec<i64>> {
        if state >= self.states.len() || remaining >= self.value.len() {
            return Err("Observation outside registered finite domain".into());
        }
        Ok(vec![
            state as i64,
            remaining as i64,
            (self.states[state] * Q as f64).round() as i64,
            (remaining as f64 * self.dt * Q as f64).round() as i64,
        ])
    }
}

pub fn drive(features: &[i64]) -> Result<Vec<i64>> {
    if features.len() != 4 || features[0] < 0 || features[1] < 0 || features[2].abs() > 7 * Q {
        return Err("Invalid finite-domain encoded features".into());
    }
    let mut drive = vec![0; 10];
    drive[0] = features[2].max(0);
    drive[1] = (-features[2]).max(0);
    drive[2] = Q / 4;
    Ok(drive)
}

pub struct Port {
    pub config: NeuronRuntimeConfigV1,
    pub model: Model,
    pub policy: Policy,
    pub last: Option<Readout>,
}

impl NeuronInferenceControlPort for Port {
    fn execute_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> std::result::Result<NeuronFeatureReceiptV1, NeuronModelError> {
        let started = Instant::now();
        let baseline = measure::start_window();
        let c = &self.config;
        let x = &request.feature_vector_q24;
        if request.generation != c.generation
            || request.model_id != c.model_id
            || request.encoder_digest != c.encoder_digest
            || request.head_digest != c.head_digest
            || request.weights_digest != c.weights_digest
            || request.expected_output_width != 10
            || x.len() != 4
            || x[0] < 0
            || x[1] < 0
        {
            return Err(NeuronModelError::Rejected);
        }
        let expected = self
            .model
            .features(x[0] as usize, x[1] as usize)
            .map_err(|_| NeuronModelError::Rejected)?;
        if *x != expected {
            return Err(NeuronModelError::Rejected);
        }
        let encoded = drive(x).map_err(|_| NeuronModelError::Rejected)?;
        self.last = Some(
            self.model
                .readout(x[0] as usize, x[1] as usize, &self.policy)
                .map_err(|_| NeuronModelError::Rejected)?,
        );
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
                drive_q24: encoded.clone(),
                prediction_q24: encoded,
                observed_memory_bytes: measure::live_bytes() as u64,
                transient_allocation_bytes: measure::peak_delta(baseline) as u64,
                queue_age_micros: 0,
                latency_micros: started.elapsed().as_micros() as u64,
                status: NeuronFeatureTerminalStatusV1::Succeeded,
            },
        )
        .map_err(|_| NeuronModelError::Rejected)
    }
}
