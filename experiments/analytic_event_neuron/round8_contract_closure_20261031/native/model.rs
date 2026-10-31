//! Frozen R7 content encoder, finite kernel, both learned Q heads and RNG.
use crate::kernels::Kernel;
use crate::kernels::simplex;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use std::time::Instant;

pub const KERNEL_VERSION: &str = "r7-finite-v1";
pub const ACTIONS: [&str; 4] = ["READ", "WAIT", "REPAIR", "STOP"];
pub fn nanos(start: Instant) -> u64 {
    start.elapsed().as_nanos().try_into().unwrap_or(u64::MAX)
}

#[derive(Clone)]
struct Linear {
    weights: Vec<Vec<f64>>,
    bias: Vec<f64>,
}
impl Linear {
    fn load(v: &Value, name: &str, inputs: usize, outputs: usize) -> Result<Self, String> {
        let weights: Vec<Vec<f64>> =
            serde_json::from_value(v[format!("{name}.weight")].clone()).map_err(|e| e.to_string())?;
        let bias: Vec<f64> =
            serde_json::from_value(v[format!("{name}.bias")].clone()).map_err(|e| e.to_string())?;
        if weights.len() != outputs
            || bias.len() != outputs
            || weights.iter().any(|r| r.len() != inputs)
            || weights
                .iter()
                .flatten()
                .chain(&bias)
                .any(|x| !x.is_finite() || x.abs() > 1e6)
        {
            return Err("learned tensor shape/value".into());
        }
        Ok(Self { weights, bias })
    }
    fn apply(&self, x: &[f64]) -> Vec<f64> {
        self.weights
            .iter()
            .zip(&self.bias)
            .map(|(r, b)| r.iter().zip(x).map(|(a, v)| a * v).sum::<f64>() + b)
            .collect()
    }
}

#[derive(Clone)]
pub struct Model {
    pub digest: String,
    pub kernel: Kernel,
    content0: Linear,
    content2: Linear,
    kernel_content: Option<(Linear, Linear)>,
    drive: Linear,
    readout0: Linear,
    readout2: Linear,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Identity {
    pub model_sha256: String,
    pub kernel_version: String,
    pub seed: u64,
    pub head: usize,
    pub deployment: String,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct State {
    pub calls: u64,
    pub mass: Vec<f64>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub pair_before: String,
    pub sequence: u64,
    pub features: Vec<f64>,
    pub legal: [bool; 4],
    pub public_state_sha256: String,
}

#[derive(Clone, Debug, Default, Serialize)]
pub struct Costs {
    pub encode_nanos: u64,
    pub cdf_transition_nanos: u64,
    pub ctmc_transition_nanos: u64,
    pub propagate_nanos: u64,
    pub sample_nanos: u64,
    pub readout_nanos: u64,
}

#[derive(Clone, Debug, Serialize)]
pub struct Prediction {
    pub action: String,
    pub q: [f64; 4],
    pub mass: Vec<f64>,
    pub moments: [f64; 4],
    pub event_count: f64,
    pub expected_event_count: f64,
    pub drive: f64,
    pub costs: Costs,
}

impl Model {
    pub fn load(bytes: &[u8]) -> Result<Self, String> {
        let root: Value = serde_json::from_slice(bytes).map_err(|e| e.to_string())?;
        let calibrated = match root.get("schema") {
            None => false,
            Some(Value::String(s)) if s == "round8-fixed-cell-calibrator-v1" => true,
            _ => return Err("unsupported checkpoint schema".into()),
        };
        if root.get("kernel_version").is_some_and(|v| v != KERNEL_VERSION) {
            return Err("unsupported checkpoint kernel version".into());
        }
        let config = &root["configuration"];
        let n = config["n_grid"].as_u64().ok_or("missing grid")? as usize;
        let hidden = config["hidden"].as_u64().ok_or("missing hidden width")? as usize;
        if !(1..=64).contains(&hidden) {
            return Err("hidden width envelope".into());
        }
        let mode = config["mode"].as_str().ok_or("missing mode")?;
        let v = &root["state_dict"];
        let mut required = vec![
            "core.raw_leak",
            "core.raw_diffusion",
            "core.raw_boundary",
            "core.raw_reset_plus",
            "core.raw_reset_minus",
            "core.raw_recovery",
            "core.normalised_grid",
            "core.normalised_edges",
            "core.plus_generator_basis",
            "core.minus_generator_basis",
            "content.0.weight",
            "content.0.bias",
            "content.2.weight",
            "content.2.bias",
            "drive.weight",
            "drive.bias",
            "readout.0.weight",
            "readout.0.bias",
            "readout.2.weight",
            "readout.2.bias",
        ];
        if calibrated {
            required.extend([
                "kernel_content.0.weight",
                "kernel_content.0.bias",
                "kernel_content.2.weight",
                "kernel_content.2.bias",
            ]);
        }
        let stored = v.as_object().ok_or("missing state dictionary")?;
        if stored.len() != required.len() || required.iter().any(|key| !stored.contains_key(*key)) {
            return Err("checkpoint tensor/version contract mismatch".into());
        }
        let names = [
            "raw_leak",
            "raw_diffusion",
            "raw_boundary",
            "raw_reset_plus",
            "raw_reset_minus",
            "raw_recovery",
        ];
        let mut raw = [0.0; 6];
        for (i, name) in names.iter().enumerate() {
            raw[i] = v[format!("core.{name}")]
                .as_f64()
                .ok_or("missing physical parameter")?;
        }
        let kernel = Kernel::new(n, mode, raw)?;
        // Stored mesh/basis tensors are part of the artifact; do not silently reinterpret a changed grid.
        let nodes: Vec<f64> =
            serde_json::from_value(v["core.normalised_grid"].clone()).map_err(|e| e.to_string())?;
        let edges: Vec<f64> =
            serde_json::from_value(v["core.normalised_edges"].clone()).map_err(|e| e.to_string())?;
        if nodes.len() != n
            || edges.len() != n + 1
            || nodes
                .iter()
                .zip(&kernel.grid)
                .any(|(a, b)| (a * kernel.boundary - b).abs() > 1e-12)
            || edges
                .iter()
                .zip(&kernel.edges)
                .any(|(a, b)| (a * kernel.boundary - b).abs() > 1e-12)
        {
            return Err("checkpoint mesh contract mismatch".into());
        }
        for direction in ["plus", "minus"] {
            let basis: Vec<Vec<f64>> =
                serde_json::from_value(v[format!("core.{direction}_generator_basis")].clone())
                    .map_err(|e| e.to_string())?;
            if basis.len() != n || basis.iter().any(|r| r.len() != n + 2) {
                return Err("generator shape".into());
            }
            for (i, row) in basis.iter().enumerate() {
                let target = if direction == "plus" {
                    if i + 1 < n { i + 1 } else { n }
                } else if i > 0 {
                    i - 1
                } else {
                    n + 1
                };
                for (j, value) in row.iter().enumerate() {
                    let expected = if j == i {
                        -1.0
                    } else if j == target {
                        1.0
                    } else {
                        0.0
                    };
                    if *value != expected {
                        return Err("generator basis mismatch".into());
                    }
                }
            }
        }
        let kernel_content = if calibrated {
            Some((
                Linear::load(v, "kernel_content.0", 18, hidden)?,
                Linear::load(v, "kernel_content.2", hidden, 8)?,
            ))
        } else {
            None
        };
        Ok(Self {
            digest: Digest32::of_bytes(bytes).to_string(),
            kernel,
            kernel_content,
            content0: Linear::load(v, "content.0", 18, hidden)?,
            content2: Linear::load(v, "content.2", hidden, 8)?,
            drive: Linear::load(v, "drive", 8, 1)?,
            readout0: Linear::load(v, "readout.0", 30, hidden)?,
            readout2: Linear::load(v, "readout.2", hidden, 8)?,
        })
    }

    pub fn validate(&self, id: &Identity, state: &State) -> Result<(), String> {
        if id.model_sha256 != self.digest
            || id.kernel_version != KERNEL_VERSION
            || id.head > 1
            || !["mean", "hard"].contains(&id.deployment.as_str())
            || state.mass.len() != self.kernel.n + 2
            || state.calls > 1024
        {
            return Err("model/policy/version/state identity mismatch".into());
        }
        simplex(&state.mass, /*tolerance*/ 2e-10)?;
        if id.deployment == "hard" && state.mass.iter().filter(|x| **x == 1.0).count() != 1 {
            return Err("sampled state is not one-hot".into());
        }
        Ok(())
    }

    pub fn predict(
        &self,
        id: &Identity,
        previous: &State,
        request: &Request,
    ) -> Result<(State, Prediction), String> {
        self.validate(id, previous)?;
        if request.features.len() != 18
            || request.features.iter().any(|x| !x.is_finite() || x.abs() > 64.0)
            || !request.legal.iter().any(|x| *x)
            || request.sequence != previous.calls + 1
        {
            return Err("public input contract".into());
        }
        let mut costs = Costs::default();
        let start = Instant::now();
        let first: Vec<_> = self
            .content0
            .apply(&request.features)
            .iter()
            .map(|v| v.tanh())
            .collect();
        let content: Vec<_> = self.content2.apply(&first).iter().map(|v| v.tanh()).collect();
        let propagation = if let Some((first_layer, second_layer)) = &self.kernel_content {
            let first: Vec<_> = first_layer
                .apply(&request.features)
                .iter()
                .map(|v| v.tanh())
                .collect();
            second_layer
                .apply(&first)
                .iter()
                .map(|v| v.tanh())
                .collect::<Vec<_>>()
        } else {
            content.clone()
        };
        let drive = 1.5 * self.drive.apply(&propagation)[0].tanh();
        costs.encode_nanos = nanos(start);
        let start = Instant::now();
        let transition = self.kernel.transition(drive, /*dt*/ 1.0)?;
        if self.kernel.mode == "first_passage" {
            costs.ctmc_transition_nanos = nanos(start);
        } else {
            costs.cdf_transition_nanos = nanos(start);
        }
        let start = Instant::now();
        let s = previous.mass.len();
        let mut mass = vec![0.0; s];
        for i in 0..s {
            for (j, value) in mass.iter_mut().enumerate() {
                *value += previous.mass[i] * transition[i][j];
            }
        }
        let expected_events: f64 = (0..self.kernel.n)
            .map(|i| previous.mass[i] * (transition[i][s - 2] + transition[i][s - 1]))
            .sum();
        simplex(&mass, /*tolerance*/ 2e-10)?;
        costs.propagate_nanos = nanos(start);
        let start = Instant::now();
        let mut event_count = expected_events;
        if id.deployment == "hard" {
            let u = keyed_uniform(id.seed, previous.calls);
            let total: f64 = mass.iter().sum();
            let mut cumulative = 0.0;
            let mut index = s - 1;
            for (i, value) in mass.iter().enumerate() {
                cumulative += value / total;
                if u < cumulative {
                    index = i;
                    break;
                }
            }
            let old = previous
                .mass
                .iter()
                .position(|x| *x == 1.0)
                .ok_or("invalid sampled predecessor")?;
            event_count = if old < self.kernel.n && index >= self.kernel.n {
                1.0
            } else {
                0.0
            };
            mass.fill(0.0);
            mass[index] = 1.0;
        }
        costs.sample_nanos = nanos(start);
        let start = Instant::now();
        let mut q = [0.0; 4];
        let mut moments = [0.0; 4];
        for (i, p) in mass.iter().enumerate() {
            for (j, value) in moments.iter_mut().enumerate() {
                *value += p * self.kernel.basis[i][j];
            }
            if *p == 0.0 {
                continue;
            }
            let mut joined = request.features.clone();
            joined.extend(&content);
            joined.extend(if self.kernel.mode == "direct" {
                [0.0; 4]
            } else {
                self.kernel.basis[i]
            });
            let hidden: Vec<_> = self.readout0.apply(&joined).iter().map(|v| v.tanh()).collect();
            let values = self.readout2.apply(&hidden);
            for a in 0..4 {
                q[a] += p * values[id.head * 4 + a];
            }
        }
        moments[1] = (moments[1] - moments[0].powi(2)).max(0.0);
        let choice = (0..4)
            .filter(|i| request.legal[*i])
            .fold(None, |best: Option<usize>, i| {
                if best.is_none_or(|j| q[i] > q[j]) {
                    Some(i)
                } else {
                    best
                }
            })
            .ok_or("no legal action")?;
        if q.iter().any(|x| !x.is_finite()) {
            return Err("nonfinite action value".into());
        }
        costs.readout_nanos = nanos(start);
        Ok((
            State {
                calls: previous.calls + 1,
                mass: mass.clone(),
            },
            Prediction {
                action: ACTIONS[choice].into(),
                q,
                mass,
                moments,
                event_count,
                expected_event_count: expected_events,
                drive,
                costs,
            },
        ))
    }
}

pub fn keyed_uniform(seed: u64, calls: u64) -> f64 {
    let key = format!("round7/policy/v1/{seed}/{calls}/latent");
    let digest = Digest32::of_bytes(key.as_bytes());
    u64::from_be_bytes(digest.as_array()[..8].try_into().expect("eight bytes")) as f64
        / 18446744073709551616.0
}
