//! Full conditional-mass CTMC and PyTorch-compatible GRU policy execution.
use crate::task;
use serde::Deserialize;
use serde::Serialize;
use std::collections::BTreeMap;

type Matrix = Vec<Vec<f64>>;

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Controller {
    Fixed,
    Value,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Network {
    w1: Matrix,
    b1: Vec<f64>,
    w2: Matrix,
    b2: Vec<f64>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Table {
    dt: f64,
    drive: i32,
    matrix: Matrix,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Gru {
    #[serde(rename = "initial_hidden.weight")]
    initial_w: Matrix,
    #[serde(rename = "initial_hidden.bias")]
    initial_b: Vec<f64>,
    #[serde(rename = "recurrent.weight_ih")]
    input_w: Matrix,
    #[serde(rename = "recurrent.weight_hh")]
    hidden_w: Matrix,
    #[serde(rename = "recurrent.bias_ih")]
    input_b: Vec<f64>,
    #[serde(rename = "recurrent.bias_hh")]
    hidden_b: Vec<f64>,
    #[serde(rename = "mass_decoder.weight")]
    mass_w: Matrix,
    #[serde(rename = "mass_decoder.bias")]
    mass_b: Vec<f64>,
    #[serde(rename = "bank1.weight")]
    bank1_w: Matrix,
    #[serde(rename = "bank1.bias")]
    bank1_b: Vec<f64>,
    #[serde(rename = "bank2.weight")]
    bank2_w: Matrix,
    #[serde(rename = "bank2.bias")]
    bank2_b: Vec<f64>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(tag = "kind", deny_unknown_fields)]
pub enum Core {
    #[serde(rename = "full_distribution_ctmc")]
    Ctmc {
        tables: Vec<Table>,
        generators: BTreeMap<String, Matrix>,
        raw: Option<Vec<f64>>,
        physical: Option<BTreeMap<String, f64>>,
        optimizer_constraint: String,
    },
    #[serde(rename = "gru")]
    Gru { weights: Gru, forecast_bank: String },
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Policy {
    pub schema: String,
    pub family: String,
    pub fit: u64,
    n_grid: usize,
    public_dimensions: usize,
    head_dimensions: Vec<usize>,
    coordinates: Vec<f64>,
    confusion: Matrix,
    nominal_raw: Vec<f64>,
    network: Network,
    bank_semantics: String,
    target: String,
    core: Core,
    parameter_count: usize,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Scores {
    pub q: [f64; 6],
    pub belief: f64,
    #[serde(rename = "logit")]
    pub belief_logit: f64,
    pub mass: Vec<f64>,
    pub bank: Vec<f64>,
}

fn linear(w: &Matrix, b: &[f64], x: &[f64]) -> Vec<f64> {
    w.iter()
        .zip(b)
        .map(|(row, bias)| bias + row.iter().zip(x).map(|(a, b)| a * b).sum::<f64>())
        .collect()
}

fn shape(w: &Matrix, b: &[f64], rows: usize, columns: usize) -> bool {
    w.len() == rows
        && b.len() == rows
        && w.iter().all(|r| r.len() == columns)
        && w.iter().flatten().chain(b).all(|x| x.is_finite())
}

fn sigmoid(x: f64) -> f64 {
    let y = x.clamp(-700.0, 700.0);
    if y >= 0.0 {
        1.0 / (1.0 + (-y).exp())
    } else {
        let e = y.exp();
        e / (1.0 + e)
    }
}

fn softmax(values: &[f64]) -> Result<Vec<f64>, String> {
    let maximum = values.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    let mut result = values
        .iter()
        .map(|x| (x - maximum).exp())
        .collect::<Vec<_>>();
    let sum = result.iter().sum::<f64>();
    if !maximum.is_finite() || !sum.is_finite() || sum <= 0.0 {
        return Err("nonfinite softmax".into());
    }
    for value in &mut result {
        *value /= sum;
    }
    Ok(result)
}

fn multiply(mass: &[f64], matrix: &Matrix) -> Vec<f64> {
    (0..33)
        .map(|j| (0..33).map(|i| mass[i] * matrix[i][j]).sum())
        .collect()
}

impl Policy {
    pub fn validate(&self, public: &task::Public) -> Result<(), String> {
        let coordinates = (1..32)
            .map(|i| i as f64 / 16.0 - 1.0)
            .chain([-1.0, 1.0])
            .collect::<Vec<_>>();
        if self.schema != "joint-policy-v1"
            || self.n_grid != 31
            || self.public_dimensions != 43
            || self.head_dimensions != [85, 48, 4]
            || self.coordinates != coordinates
            || self.nominal_raw.len() != 8
            || self.nominal_raw.iter().any(|x| !x.is_finite())
            || self.confusion.len() != 2
            || self.confusion.iter().any(|r| {
                r.len() != 2
                    || r.iter().any(|x| !x.is_finite() || *x <= 0.0)
                    || (r.iter().sum::<f64>() - 1.0).abs() > 1e-12
            })
            || !shape(&self.network.w1, &self.network.b1, 48, 85)
            || !shape(&self.network.w2, &self.network.b2, 4, 48)
            || self.target
                != "sign(X_deadline6)>0, including early submit; learned belief is not privileged posterior"
            || self.bank_semantics
                != "no-new-observation predictive state probability at next boundary, two boundaries and deadline6; thresholds normalized(-.5,0,.5), strict>; actual scheduled future drives and durations"
        {
            return Err("joint policy schema/shape/semantic envelope".into());
        }
        match &self.core {
            Core::Gru {
                weights: g,
                forecast_bank,
            } => {
                if self.family != "gru"
                    || self.parameter_count != 26129
                    || forecast_bank
                        != "three horizons, four-bin softmax each; tail sums yield the three ordered threshold probabilities"
                    || !shape(&g.initial_w, &g.initial_b, 64, 33)
                    || !shape(&g.input_w, &g.input_b, 192, 5)
                    || !shape(&g.hidden_w, &g.hidden_b, 192, 64)
                    || !shape(&g.mass_w, &g.mass_b, 33, 64)
                    || !shape(&g.bank1_w, &g.bank1_b, 32, 107)
                    || !shape(&g.bank2_w, &g.bank2_b, 12, 32)
                {
                    return Err("GRU family/shape envelope".into());
                }
            }
            Core::Ctmc {
                tables,
                generators,
                raw,
                physical,
                optimizer_constraint,
            } => {
                let count = if self.family == "renewal" {
                    4332
                } else if self.family == "full_markov" {
                    7492
                } else if self.family == "affine_markov" {
                    6436
                } else {
                    0
                };
                if count == 0
                    || self.parameter_count != count
                    || generators.len() != 3
                    || tables.is_empty()
                    || tables.len() > 48
                    || optimizer_constraint.is_empty()
                    || raw
                        .as_ref()
                        .is_some_and(|v| v.len() != 8 || v.iter().any(|x| !x.is_finite()))
                    || physical
                        .as_ref()
                        .is_some_and(|m| m.values().any(|v| !v.is_finite()))
                {
                    return Err("CTMC family/metadata envelope".into());
                }
                for drive in [-1, 0, 1] {
                    let q = generators
                        .get(&drive.to_string())
                        .ok_or("missing generator")?;
                    if q.len() != 33
                        || q.iter().any(|r| {
                            r.len() != 33
                                || r.iter().any(|v| !v.is_finite())
                                || r.iter().sum::<f64>().abs() > 1e-7
                        })
                        || (0..33).any(|i| (0..33).any(|j| i != j && q[i][j] < -1e-12))
                    {
                        return Err("invalid generator metadata".into());
                    }
                }
                for (i, t) in tables.iter().enumerate() {
                    if !t.dt.is_finite()
                        || t.dt <= 0.0
                        || t.dt > 2.0
                        || ![-1, 0, 1].contains(&t.drive)
                        || tables[..i]
                            .iter()
                            .any(|s| s.dt == t.dt && s.drive == t.drive)
                        || t.matrix.len() != 33
                        || t.matrix.iter().any(|r| {
                            r.len() != 33
                                || r.iter().any(|v| !v.is_finite() || *v < -1e-12)
                                || (r.iter().sum::<f64>() - 1.0).abs() > 1e-9
                        })
                    {
                        return Err("invalid CTMC transition table".into());
                    }
                }
                for i in 0..6 {
                    self.table(public.duration[i], public.drive[i])?;
                }
            }
        }
        Ok(())
    }

    fn table(&self, dt: f64, drive: i32) -> Result<&Matrix, String> {
        match &self.core {
            Core::Ctmc { tables, .. } => tables
                .iter()
                .find(|t| t.dt == dt && t.drive == drive)
                .map(|t| &t.matrix)
                .ok_or("missing public transition context".into()),
            Core::Gru { .. } => Err("GRU has no CTMC transition table".into()),
        }
    }

    fn thresholds(&self, mass: &[f64]) -> Vec<f64> {
        [-0.5, 0.0, 0.5]
            .iter()
            .map(|threshold| {
                mass.iter()
                    .zip(&self.coordinates)
                    .filter(|(_, x)| **x > *threshold)
                    .map(|(p, _)| p)
                    .sum()
            })
            .collect()
    }

    pub fn representation(
        &self,
        public: &task::Public,
        state: &task::State,
    ) -> Result<(Vec<f64>, Vec<f64>), String> {
        state.validate(public)?;
        let mut mass = vec![0.0; 33];
        for distance in [-public.prior_distance, public.prior_distance] {
            let index = (0..31)
                .min_by(|a, b| {
                    (self.coordinates[*a] - distance)
                        .abs()
                        .total_cmp(&(self.coordinates[*b] - distance).abs())
                })
                .ok_or("empty prior grid")?;
            mass[index] += 0.5;
        }
        let mut hidden = if let Core::Gru { weights: g, .. } = &self.core {
            linear(&g.initial_w, &g.initial_b, &mass)
                .iter()
                .map(|v| v.tanh())
                .collect::<Vec<_>>()
        } else {
            vec![]
        };
        for i in 0..state.tick {
            let observation = state.history.iter().find(|h| h.observation_tick == i + 1);
            match &self.core {
                Core::Gru { weights: g, .. } => {
                    let flag = if observation.is_some() { 1.0 } else { 0.0 };
                    let (y, r) = observation
                        .map(|o| (o.observation as f64, o.reliability))
                        .unwrap_or((0.0, 0.5));
                    let event = [
                        public.duration[i] / 2.0,
                        public.drive[i] as f64,
                        flag,
                        flag * (2.0 * y - 1.0),
                        flag * (2.0 * r - 1.0),
                    ];
                    let gi = linear(&g.input_w, &g.input_b, &event);
                    let gh = linear(&g.hidden_w, &g.hidden_b, &hidden);
                    hidden = (0..64)
                        .map(|j| {
                            let reset = sigmoid(gi[j] + gh[j]);
                            let update = sigmoid(gi[j + 64] + gh[j + 64]);
                            let candidate = (gi[j + 128] + reset * gh[j + 128]).tanh();
                            (1.0 - update) * candidate + update * hidden[j]
                        })
                        .collect();
                    mass = softmax(&linear(&g.mass_w, &g.mass_b, &hidden))?;
                }
                Core::Ctmc { .. } => {
                    mass = multiply(&mass, self.table(public.duration[i], public.drive[i])?);
                    if let Some(o) = observation {
                        for (j, p) in mass.iter_mut().enumerate() {
                            let sign = usize::from(self.coordinates[j] > 0.0);
                            *p *= o.reliability * self.confusion[sign][o.observation]
                                + (1.0 - o.reliability) * self.confusion[1 - sign][o.observation];
                        }
                        let sum = mass.iter().sum::<f64>();
                        if !sum.is_finite() || sum <= 0.0 {
                            return Err("impossible conditioned observation".into());
                        }
                        for p in &mut mass {
                            *p /= sum;
                        }
                    }
                }
            }
        }
        let bank = match &self.core {
            Core::Gru { weights: g, .. } => {
                let input = hidden
                    .iter()
                    .chain(&state.public_features(public))
                    .copied()
                    .collect::<Vec<_>>();
                let mid = linear(&g.bank1_w, &g.bank1_b, &input)
                    .iter()
                    .map(|v| v.tanh())
                    .collect::<Vec<_>>();
                let logits = linear(&g.bank2_w, &g.bank2_b, &mid);
                let mut tails = vec![];
                for row in logits.chunks(4) {
                    let bins = softmax(row)?;
                    tails.extend([bins[1..].iter().sum(), bins[2..].iter().sum(), bins[3]]);
                }
                tails
            }
            Core::Ctmc { .. } => {
                let mut forecasts = vec![vec![]; 7];
                forecasts[state.tick] = self.thresholds(&mass);
                let mut future = mass.clone();
                for i in state.tick..6 {
                    future = multiply(&future, self.table(public.duration[i], public.drive[i])?);
                    forecasts[i + 1] = self.thresholds(&future);
                }
                [
                    usize::min(state.tick + 1, 6),
                    usize::min(state.tick + 2, 6),
                    6,
                ]
                .iter()
                .flat_map(|i| forecasts[*i].clone())
                .collect()
            }
        };
        if mass
            .iter()
            .chain(&bank)
            .any(|v| !v.is_finite() || *v < -1e-9 || *v > 1.0 + 1e-9)
            || (mass.iter().sum::<f64>() - 1.0).abs() > 1e-8
        {
            return Err("invalid conditional distribution or bank".into());
        }
        Ok((mass, bank))
    }

    pub fn predict(&self, public: &task::Public, state: &task::State) -> Result<Scores, String> {
        let (mass, bank) = self.representation(public, state)?;
        self.predict_with_memory(public, state, mass, bank)
    }

    pub fn predict_with_memory(
        &self,
        public: &task::Public,
        state: &task::State,
        mass: Vec<f64>,
        bank: Vec<f64>,
    ) -> Result<Scores, String> {
        let x = state
            .public_features(public)
            .into_iter()
            .chain(mass.iter().copied())
            .chain(bank.iter().copied())
            .collect::<Vec<_>>();
        let hidden = linear(&self.network.w1, &self.network.b1, &x)
            .iter()
            .map(|v| v.tanh())
            .collect::<Vec<_>>();
        let output = linear(&self.network.w2, &self.network.b2, &hidden);
        if output.iter().any(|v| !v.is_finite()) {
            return Err("nonfinite joint neural scores".into());
        }
        let p = sigmoid(output[3]);
        Ok(Scores {
            q: [
                0.0,
                output[0],
                output[1],
                output[2],
                1.0 - 2.0 * p,
                2.0 * p - 1.0,
            ],
            belief: p,
            belief_logit: output[3],
            mass,
            bank,
        })
    }

    pub fn select(
        &self,
        public: &task::Public,
        state: &task::State,
        controller: Controller,
        scores: &Scores,
    ) -> Result<usize, String> {
        let legal = state.legal(public);
        if !legal.iter().any(|a| *a) {
            return Err("terminal policy query".into());
        }
        match controller {
            Controller::Fixed => Ok(task::fixed_action(state, legal, scores.belief)),
            Controller::Value => {
                let mut best = 0;
                for i in 1..6 {
                    if legal[i] && scores.q[i] > scores.q[best] {
                        best = i;
                    }
                }
                Ok(best)
            }
        }
    }
}
