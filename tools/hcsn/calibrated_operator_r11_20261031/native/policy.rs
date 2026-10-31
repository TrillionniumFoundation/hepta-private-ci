//! Frozen absolute-Q policy; fixed controls do not evaluate the critic.
use crate::cell::Family;
use crate::grid::Grid;
use crate::task::Action;
use crate::task::Public;
use crate::task::State;
use serde::Deserialize;
use serde::Serialize;
use std::cell::OnceCell;

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Controller {
    Fixed,
    Value,
    DirectFixed,
    Grid,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Norm {
    pub mean: Vec<f64>,
    pub scale: Vec<f64>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Weights {
    pub w: Vec<Vec<f64>>,
    pub b: Vec<f64>,
    pub v: Vec<Vec<f64>>,
    pub c: Vec<f64>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Policy {
    pub schema: String,
    pub family: Family,
    pub controller: Controller,
    pub input_width: usize,
    pub hidden_width: usize,
    pub norm: Norm,
    pub parameters: [f64; 11],
    pub weights: Weights,
    pub confusion: [[f64; 2]; 2],
    pub fixed_boundary: f64,
    pub multiplier: f64,
    pub latency_price: f64,
    pub seed: u64,
    pub feature_names: Vec<String>,
    pub grid_nodes: usize,
    pub residual_radius: f64,
    pub intervention: String,
    #[serde(skip)]
    grid: OnceCell<Grid>,
}

impl Policy {
    pub fn validate(
        &self,
        public: &Public,
        family: Family,
        controller: Controller,
    ) -> Result<(), String> {
        if self.schema != "hcsn.calibrated.operator.policy.v1"
            || self.family != family
            || self.controller != controller
            || family == Family::Sampled
            || (controller == Controller::DirectFixed && family != Family::Ordinary)
            || self.input_width != 67
            || self.hidden_width != 24
            || self.norm.mean.len() != 67
            || self.norm.scale.len() != 67
            || self.feature_names != feature_names()
            || self.weights.w.len() != 67
            || self.weights.w.iter().any(|r| r.len() != 24)
            || self.weights.v.len() != 24
            || self.weights.v.iter().any(|r| r.len() != 4)
            || self.weights.b.len() != 24
            || self.weights.c.len() != 4
            || self.fixed_boundary != 0.8
            || !self.residual_radius.is_finite()
            || self.residual_radius < 0.0
            || self.residual_radius > 0.002
            || !["none", "constant"].contains(&self.intervention.as_str())
            || self.multiplier != public.multiplier
            || self.latency_price != public.latency_price
        {
            return Err("policy shape/identity/task-contract mismatch".into());
        }
        if self.norm.mean.iter().any(|x| !x.is_finite())
            || self.norm.scale.iter().any(|x| !x.is_finite() || *x <= 0.0)
            || self
                .weights
                .w
                .iter()
                .flatten()
                .chain(self.weights.v.iter().flatten())
                .chain(&self.weights.b)
                .chain(&self.weights.c)
                .any(|x| !x.is_finite())
            || self.confusion.iter().any(|r| {
                r.iter().any(|x| !x.is_finite() || *x <= 0.0)
                    || (r.iter().sum::<f64>() - 1.0).abs() > 1e-10
            })
        {
            return Err("policy numerical envelope".into());
        }
        self.grid
            .set(Grid::new(public, self.confusion, self.grid_nodes)?)
            .map_err(|_| "grid already fitted".to_string())?;
        Ok(())
    }

    pub fn resident_bytes(&self) -> u64 {
        ((67 * 24 + 24 + 24 * 4 + 4 + 11 + 134) * 8
            + self.grid.get().map_or(0, Grid::resident_bytes)) as u64
    }

    pub fn predict(&self, public: &[f64], cell: [f64; 5]) -> Result<[f64; 4], String> {
        if public.len() != 62 {
            return Err("public feature width".into());
        }
        let grid = self.grid.get().ok_or("unfitted public schedule")?;
        let base = grid.q(
            public[0] as usize,
            public[1] as usize,
            public[2] as usize,
            public[3],
        );
        if self.controller == Controller::Grid {
            return Ok(base.map(|q| if q.is_finite() { q } else { 0. }));
        }
        let cell = if self.intervention == "constant" {
            [0.5; 5]
        } else {
            cell
        };
        let x = public
            .iter()
            .chain(&cell)
            .enumerate()
            .map(|(i, v)| (v - self.norm.mean[i]) / self.norm.scale[i])
            .collect::<Vec<_>>();
        if x.iter().any(|v| !v.is_finite()) {
            return Err("nonfinite standardized policy input".into());
        }
        let h: [f64; 24] = std::array::from_fn(|j| {
            (self.weights.b[j]
                + x.iter()
                    .enumerate()
                    .map(|(i, v)| v * self.weights.w[i][j])
                    .sum::<f64>())
            .tanh()
        });
        let output: [f64; 4] = std::array::from_fn(|j| {
            self.weights.c[j]
                + h.iter()
                    .enumerate()
                    .map(|(i, v)| v * self.weights.v[i][j])
                    .sum::<f64>()
        });
        let q = std::array::from_fn(|j| {
            if j == 0 || !base[j].is_finite() {
                0.
            } else {
                base[j] + self.residual_radius * output[j].tanh()
            }
        });
        if q.iter().any(|v| !v.is_finite()) {
            return Err("nonfinite policy value".into());
        }
        Ok(q)
    }
}

fn feature_names() -> Vec<String> {
    let mut names = [
        "job",
        "tick",
        "budget",
        "posterior",
        "deadline",
        "initial_budget",
        "multiplier",
        "latency_price",
    ]
    .into_iter()
    .map(str::to_owned)
    .collect::<Vec<_>>();
    for schedule in ["reliability", "price"] {
        for j in 0..2 {
            for t in 0..10 {
                names.push(format!("{schedule}_{j}_{t}"));
            }
        }
    }
    for t in 0..10 {
        names.push(format!("duration_{t}"));
    }
    for j in 0..2 {
        for k in 0..2 {
            names.push(format!("confusion_{j}_{k}"));
        }
    }
    for k in 0..4 {
        names.push(format!("cell_{k}"));
    }
    names.push("next_observation_probability".into());
    names
}

pub fn select(q: [f64; 4], legal: [bool; 4]) -> Action {
    let mut best = 0;
    for i in 1..4 {
        if legal[i] && q[i] > q[best] + 1e-12 {
            best = i;
        }
    }
    Action::ALL[best]
}

pub fn fixed(state: &State, legal: [bool; 4]) -> Action {
    if legal[3] && (state.posterior.max(1.0 - state.posterior) >= 0.8 || !legal[2]) {
        Action::Fire
    } else if legal[2] {
        Action::Read
    } else {
        Action::Stop
    }
}

pub fn features(public: &Public, state: &State, confusion: [[f64; 2]; 2]) -> Vec<f64> {
    let mut x = vec![
        state.job as f64,
        state.tick as f64,
        state.budget as f64,
        state.posterior,
        public.deadline as f64,
        public.budget as f64,
        public.multiplier,
        public.latency_price,
    ];
    for schedule in [&public.reliability, &public.price] {
        for row in schedule {
            for t in 0..10 {
                x.push(row.get(t).copied().unwrap_or(0.0));
            }
        }
    }
    for t in 0..10 {
        x.push(public.duration.get(t).copied().unwrap_or(0.0));
    }
    x.extend(confusion.into_iter().flatten());
    x
}
