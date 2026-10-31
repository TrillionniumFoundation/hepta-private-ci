//! Frozen FullHX inference, actual packet reads and the owner's durable content state.
//! Parameters retain binary32 arithmetic; the symmetric ridge solve uses binary64.
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use std::collections::BTreeMap;
use std::fs::OpenOptions;
use std::io::Read;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;

const WIDTH: usize = 62;
const KEY: usize = 16;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Weights {
    schema: String,
    checkpoint_sha256: String,
    table_sha256: String,
    parameters: BTreeMap<String, Vec<f32>>,
    table: BTreeMap<String, Vec<f32>>,
}

pub struct Model {
    weights: Weights,
    pub digest: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub path: String,
    pub sha256: String,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Output {
    pub payload_sha256: String,
    pub payload_bytes: u64,
    pub observation: usize,
    pub logits_bits: [String; 4],
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct State {
    pub model_digest: String,
    pub completed_reads: u64,
    pub last: Option<Output>,
}

impl State {
    pub fn new(model: &Model) -> Self {
        Self {
            model_digest: model.digest.clone(),
            completed_reads: 0,
            last: None,
        }
    }

    pub fn validate(&self, model: &Model, sequence: u64) -> Result<(), String> {
        if self.model_digest != model.digest
            || self.completed_reads > sequence
            || (self.completed_reads == 0) != self.last.is_none()
        {
            return Err("content checkpoint/model mismatch".into());
        }
        if let Some(last) = &self.last {
            let parsed = last
                .logits_bits
                .iter()
                .map(|s| u32::from_str_radix(s, 16).ok().map(f32::from_bits))
                .collect::<Option<Vec<_>>>()
                .ok_or("invalid content logits")?;
            if parsed.iter().any(|x| !x.is_finite())
                || last.observation > 1
                || last.observation != usize::from(parsed[1] > parsed[0])
                || last.payload_bytes > 32_768
                || last.payload_sha256.parse::<Digest32>().is_err()
            {
                return Err("invalid content checkpoint".into());
            }
        }
        Ok(())
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Packet {
    schema: String,
    symbols: Vec<i32>,
    dt: Vec<f32>,
}

fn read_bounded(path: &Path, limit: u64) -> Result<Vec<u8>, String> {
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)
        .map_err(|e| e.to_string())?;
    if !file.metadata().map_err(|e| e.to_string())?.is_file() {
        return Err("content requires a regular file".into());
    }
    let mut bytes = Vec::new();
    file.take(limit + 1)
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    if bytes.len() as u64 > limit {
        return Err("content byte limit".into());
    }
    Ok(bytes)
}

impl Model {
    pub fn load(path: &Path, expected: &str) -> Result<Self, String> {
        let bytes = read_bounded(path, 2_000_000)?;
        let digest = Digest32::of_bytes(&bytes).to_string();
        if digest != expected {
            return Err("content weight digest mismatch".into());
        }
        let weights: Weights = serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
        let shapes = [
            ("bias", 62),
            ("boundary", 62),
            ("boundary_weights", 17),
            ("call", 62),
            ("inp", 17 * 62),
            ("key", 17 * 16),
            ("key_bias", 16),
            ("out", 62 * 4),
            ("out_bias", 4),
            ("read_current", 62),
            ("read_fast", 62),
            ("read_slow", 62),
            ("recover", 62),
            ("recurrent_diag", 62),
            ("regen", 62),
            ("tau_fast", 62),
            ("tau_slow", 62),
            ("value", 62 * 62),
            ("value_bias", 62),
            ("write", 17),
            ("write_bias", 1),
        ];
        if weights.schema != "hcsn.fullhx.frozen-f32.v1"
            || weights.checkpoint_sha256 != "4962cd6126dc5e393cf7dbe72bea5519125bfb7971a7e3665a36af908aff5fcb"
            || weights.table_sha256 != "c77e407162061c06a9a34c5822b8751ebb2a71b1a5ff2a584c60e6b6ec63e764"
            || weights.parameters.len() != shapes.len()
            || shapes
                .iter()
                .any(|(name, n)| weights.parameters.get(*name).is_none_or(|v| v.len() != *n))
        {
            return Err("frozen content model shape/provenance".into());
        }
        let scalars = [
            "call_step",
            "call_limit",
            "call_distance_limit",
            "call_end",
            "call_tail_rate",
            "risk_step",
            "risk_limit",
            "risk_end",
            "risk_tail_rate",
            "diffusion_scale",
            "epsilon_scaled",
            "patch_A",
            "patch_B",
            "boundary",
        ];
        if scalars
            .iter()
            .any(|name| weights.table.get(*name).is_none_or(|v| v.len() != 1))
            || ["call_coeff", "risk_coeff"]
                .iter()
                .any(|name| weights.table.get(*name).is_none_or(|v| v.len() != 4 * 4096))
            || weights.table.len() != 16
            || weights
                .parameters
                .values()
                .chain(weights.table.values())
                .flatten()
                .any(|x| !x.is_finite())
            || ["call_step", "risk_step", "diffusion_scale", "epsilon_scaled"]
                .iter()
                .any(|k| weights.table[*k][0] <= 0.)
        {
            return Err("frozen content table envelope".into());
        }
        Ok(Self { weights, digest })
    }

    pub fn read(&self, request: &Request) -> Result<Output, String> {
        let bytes = read_bounded(Path::new(&request.path), 32_768)?;
        let payload_sha256 = Digest32::of_bytes(&bytes).to_string();
        if payload_sha256 != request.sha256 {
            return Err("content packet digest mismatch".into());
        }
        let packet: Packet = serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
        let length = packet.symbols.len();
        if packet.schema != "hcsn.memory.packet.v1"
            || !(2..=128).contains(&length)
            || packet.symbols[length - 1] != -1
            || packet.symbols[..length - 1].iter().any(|x| !(0..4).contains(x))
            || packet.dt.len() != length
            || packet.dt.iter().any(|x| !x.is_finite() || *x <= 0.)
        {
            return Err("invalid content packet".into());
        }
        let p = &self.weights.parameters;
        let mut gram = [[0_f32; KEY]; KEY];
        let mut cross = [[0_f32; WIDTH]; KEY];
        let (mut xx, mut yy, mut current, mut key) = ([0_f32; WIDTH], [0_f32; WIDTH], [0_f32; WIDTH], [0_f32; KEY]);
        let mut mass = 1_f32;
        for index in 0..length {
            let mut u = [0_f32; 17];
            if index < length - 1 {
                u[packet.symbols[index] as usize] = 1.;
            }
            if index == 0 {
                u[4] = 1.;
            }
            if index == length - 1 {
                u[5] = 1.;
            }
            u[16] = packet.dt[index].ln_1p();
            let mut hidden = [0_f32; WIDTH];
            for (j, h) in hidden.iter_mut().enumerate() {
                *h = (dot_column(&u, &p["inp"], WIDTH, j) + p["bias"][j]).tanh();
            }
            for (j, k) in key.iter_mut().enumerate() {
                *k = (dot_column(&u, &p["key"], KEY, j) + p["key_bias"][j]).tanh() / 4.;
            }
            let shift = dot_column(&u, &p["boundary_weights"], 1, 0);
            let mut candidate = [0_f32; WIDTH];
            for j in 0..WIDTH {
                let (q, a) = full_gates(xx[j] - p["boundary"][j] - shift, &self.weights.table);
                let drive = 3. * (hidden[j] + 0.5 * p["recurrent_diag"][j].tanh() * (2. * q - 1.)).tanh();
                let fast = 0.2 + 4.8 * sigmoid(p["tau_fast"][j]);
                let slow = 2. + 98. * sigmoid(p["tau_slow"][j]);
                let ef = (-packet.dt[index] / fast).exp();
                let es = (-packet.dt[index] / slow).exp();
                xx[j] = ef * xx[j]
                    + (1. - ef) * (2. * sigmoid(p["call"][j]) * a + 4. * sigmoid(p["regen"][j]) * q - yy[j] + drive);
                yy[j] = es * yy[j] + (1. - es) * 6. * sigmoid(p["recover"][j]) * q;
                candidate[j] =
                    (dot_column(&hidden, &p["value"], WIDTH, j) + p["value_bias"][j] + 0.1 * xx[j].tanh()).tanh();
                current[j] = p["read_current"][j].tanh() * hidden[j]
                    + p["read_fast"][j].tanh() * xx[j].tanh()
                    + p["read_slow"][j].tanh() * yy[j].tanh();
            }
            if index < length - 1 {
                let write = closed_write(dot_column(&u, &p["write"], 1, 0) + p["write_bias"][0]);
                mass /= 1. + write * mass;
                let alpha = write * mass;
                for i in 0..KEY {
                    for j in 0..KEY {
                        gram[i][j] = (1. - alpha) * gram[i][j] + alpha * (key[i] * key[j]);
                    }
                    for j in 0..WIDTH {
                        cross[i][j] = (1. - alpha) * cross[i][j] + alpha * (key[i] * candidate[j]);
                    }
                }
            }
        }
        let fitted = solve(&gram, &cross, mass)?;
        let mut decoded = [0_f32; WIDTH];
        for j in 0..WIDTH {
            let read = (0..KEY).map(|i| f64::from(key[i]) * fitted[i][j]).sum::<f64>() as f32;
            decoded[j] = read.tanh() + current[j];
        }
        let logits: [f32; 4] = std::array::from_fn(|j| dot_column(&decoded, &p["out"], 4, j) + p["out_bias"][j]);
        if logits.iter().any(|x| !x.is_finite()) {
            return Err("nonfinite content result".into());
        }
        Ok(Output {
            payload_sha256,
            payload_bytes: bytes.len() as u64,
            observation: usize::from(logits[1] > logits[0]),
            logits_bits: logits.map(|x| format!("{:08x}", x.to_bits())),
        })
    }
}

fn dot_column(input: &[f32], matrix: &[f32], width: usize, column: usize) -> f32 {
    input
        .iter()
        .enumerate()
        .map(|(i, x)| x * matrix[i * width + column])
        .sum()
}
fn sigmoid(z: f32) -> f32 {
    let e = (-z.abs()).exp();
    if z >= 0. { 1. / (1. + e) } else { e / (1. + e) }
}
fn closed_write(z: f32) -> f32 {
    let x = z.max(0.);
    if x > 1. {
        let r = 1. / x;
        1. / (1. + r * r)
    } else {
        x * x / (1. + x * x)
    }
}
fn hermite(t: f32, y0: f32, y1: f32, m0: f32, m1: f32, step: f32) -> f32 {
    y0 + (y1 - y0) * t * t * (3. - 2. * t) + step * m0 * t * (1. - t).powi(2) + step * m1 * t * t * (t - 1.)
}
fn cubic(u: f32, coeff: &[f32], step: f32, end: f32, slope: f32) -> f32 {
    let i = ((u / step).floor() as usize).min(4095);
    let (y1, m1) = if i < 4095 {
        (coeff[3 * 4096 + i + 1], coeff[2 * 4096 + i + 1])
    } else {
        (end, slope)
    };
    hermite(
        (u - i as f32 * step) / step,
        coeff[3 * 4096 + i],
        y1,
        coeff[2 * 4096 + i],
        m1,
        step,
    )
}
fn full_gates(z: f32, t: &BTreeMap<String, Vec<f32>>) -> (f32, f32) {
    let scalar = |k: &str| t[k][0];
    let distance = z.abs();
    let eps = scalar("epsilon_scaled");
    let risk = if distance < eps {
        hermite(
            (distance / eps).min(1.),
            1.,
            t["risk_coeff"][3 * 4096],
            0.,
            t["risk_coeff"][2 * 4096],
            eps,
        )
    } else if distance > scalar("risk_limit") {
        scalar("risk_end") * (-scalar("risk_tail_rate") * (distance - scalar("risk_limit"))).exp()
    } else {
        cubic(
            distance - eps,
            &t["risk_coeff"],
            scalar("risk_step"),
            scalar("risk_end"),
            -scalar("risk_end") * scalar("risk_tail_rate"),
        )
    };
    if z >= 0. {
        return (1. - 0.5 * risk, 0.);
    }
    let safe = scalar("diffusion_scale") * (-z);
    let a = if safe > scalar("call_distance_limit") {
        1. - (1. - scalar("call_end")) * (-scalar("call_tail_rate") * (safe - scalar("call_distance_limit"))).exp()
    } else {
        cubic(
            (safe / scalar("diffusion_scale")).ln_1p().min(scalar("call_limit")),
            &t["call_coeff"],
            scalar("call_step"),
            scalar("call_end"),
            scalar("call_tail_rate")
                * (1. - scalar("call_end"))
                * (scalar("diffusion_scale") + scalar("call_distance_limit")),
        )
    };
    (0.5 * risk, a)
}
fn solve(gram: &[[f32; KEY]; KEY], cross: &[[f32; WIDTH]; KEY], mass: f32) -> Result<[[f64; WIDTH]; KEY], String> {
    let mut l = [[0_f64; KEY]; KEY];
    for i in 0..KEY {
        for j in 0..=i {
            let mut x = 0.5 * (f64::from(gram[i][j]) + f64::from(gram[j][i]));
            if i == j {
                x += 0.01 * f64::from(mass);
            }
            for k in 0..j {
                x -= l[i][k] * l[j][k];
            }
            if i == j {
                if !x.is_finite() || x <= 0. {
                    return Err("content ridge factorization".into());
                }
                l[i][j] = x.sqrt();
            } else {
                l[i][j] = x / l[j][j];
            }
        }
    }
    let mut fitted = [[0_f64; WIDTH]; KEY];
    for c in 0..WIDTH {
        for i in 0..KEY {
            let mut x = f64::from(cross[i][c]);
            for j in 0..i {
                x -= l[i][j] * fitted[j][c];
            }
            fitted[i][c] = x / l[i][i];
        }
        for i in (0..KEY).rev() {
            let mut x = fitted[i][c];
            for j in i + 1..KEY {
                x -= l[j][i] * fitted[j][c];
            }
            fitted[i][c] = x / l[i][i];
        }
    }
    Ok(fitted)
}
