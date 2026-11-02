//! Native forward pass of the actual fitted learned-latent-model checkpoints.
use crate::common::{Result, checksum, ensure, read};
use crate::numeric::{self, Matrix, Vector};
use std::collections::BTreeMap;
use std::path::Path;
pub type Beliefs = [Vector; 4];
pub struct Decision {
    pub read: bool,
    pub answer_before: usize,
    pub pre_logits: [f32; 4],
    pub pre_prob: [f32; 4],
    pub post_logits: [[f32; 4]; 4],
    pub post_prob: [[f32; 4]; 4],
    pub read_value: f32,
    pub action_gap: f32,
    pub min_head_gap: f32,
}
pub struct Model {
    pub identity: String,
    pub checkpoint_sha: String,
    pub control: String,
    pub threshold: f32,
    q: Matrix,
    phase: [f64; 10],
    encoded: [[f32; 4]; 4],
    emission: [[f32; 4]; 4],
    channel: [[f32; 4]; 4],
    h0w: Vec<f32>,
    h0b: Vec<f32>,
    h2w: Vec<f32>,
    h2b: Vec<f32>,
    cache: BTreeMap<u64, Matrix>,
}
fn softmax(x: [f32; 4]) -> [f32; 4] {
    let top = x.iter().copied().fold(f32::NEG_INFINITY, f32::max);
    let mut y = x.map(|v| (v - top).exp());
    // Match the declared FP32 operator: sum first, then reciprocal multiply.
    let reciprocal = 1_f32 / y.iter().sum::<f32>();
    for v in &mut y {
        *v *= reciprocal;
    }
    y
}
fn maximum(x: &[f32; 4]) -> (usize, f32, f32) {
    let mut best = 0;
    for i in 1..4 {
        if x[i] > x[best] {
            best = i;
        }
    }
    let second = x
        .iter()
        .enumerate()
        .filter(|(i, _)| *i != best)
        .map(|(_, v)| *v)
        .fold(f32::NEG_INFINITY, f32::max);
    (best, x[best], x[best] - second)
}
impl Model {
    pub fn open(path: &Path) -> Result<Self> {
        let text = read(path)?;
        let mut lines = text.lines();
        let header: Vec<_> = lines.next().ok_or("model header")?.split('\t').collect();
        ensure(
            header.len() == 4 && header[0] == "LEARNED2" && header[1].len() == 64,
            "learned model identity",
        )?;
        ensure(matches!(header[2], "light" | "value"), "controller")?;
        let threshold: f32 = header[3].parse()?;
        ensure(threshold.is_finite(), "nonfinite controller threshold")?;
        let mut data = BTreeMap::new();
        for line in lines {
            let mut fields = line.split_whitespace();
            let key = fields.next().ok_or("model field")?;
            let values: std::result::Result<Vec<f64>, _> = fields.map(str::parse).collect();
            ensure(data.insert(key, values?).is_none(), "duplicate model field")?;
        }
        for (name, count) in [
            ("Q", 1600),
            ("GAMMA", 1),
            ("PHASE", 10),
            ("SYMBOL", 16),
            ("ENCODED", 16),
            ("EMISSION", 16),
            ("H0W", 1280),
            ("H0B", 32),
            ("H2W", 128),
            ("H2B", 4),
            ("CHANNEL", 16),
            ("DURATIONS", 6),
        ] {
            let row = data.get(name).ok_or("missing model field")?;
            ensure(
                row.len() == count && row.iter().all(|v| v.is_finite()),
                "parameter shape/value",
            )?;
            if matches!(
                name,
                "SYMBOL" | "ENCODED" | "EMISSION" | "H0W" | "H0B" | "H2W" | "H2B" | "CHANNEL"
            ) {
                ensure(
                    row.iter().all(|v| (*v as f32).is_finite()),
                    "FP32 parameter overflow",
                )?;
            }
        }
        let gamma = data["GAMMA"][0];
        ensure(gamma > 0. && gamma < 4., "unqualified learned timescale")?;
        let mut q = [[0.; 40]; 40];
        for i in 0..40 {
            for j in 0..40 {
                q[i][j] = data["Q"][i * 40 + j] * gamma;
                ensure(
                    q[i][j].is_finite() && (i == j || q[i][j] >= 0.),
                    "generator entry",
                )?;
            }
            ensure(
                q[i][i] <= 0. && q[i].iter().sum::<f64>().abs() < 5e-12,
                "generator row",
            )?;
        }
        let mut phase = [0.; 10];
        phase.copy_from_slice(&data["PHASE"]);
        ensure(
            phase.iter().all(|v| *v >= 0.) && (phase.iter().sum::<f64>() - 1.).abs() < 1e-12,
            "phase prior",
        )?;
        let mut encoded = [[0.; 4]; 4];
        let mut emission = [[0.; 4]; 4];
        let mut channel = [[0.; 4]; 4];
        for i in 0..4 {
            let independently_encoded =
                softmax(std::array::from_fn(|j| data["SYMBOL"][j * 4 + i] as f32));
            let row = softmax(std::array::from_fn(|j| data["SYMBOL"][i * 4 + j] as f32));
            for j in 0..4 {
                // These immutable graph operations are folded by the exporter.
                // Independent native softmax checks their source-law agreement;
                // exact FP32 constants prevent a libm rounding change in state.
                encoded[i][j] = data["ENCODED"][i * 4 + j] as f32;
                emission[i][j] = data["EMISSION"][i * 4 + j] as f32;
                ensure(
                    (encoded[i][j] - independently_encoded[j]).abs() <= 2e-7
                        && (emission[i][j] - (0.01_f32 + 0.96_f32 * row[j])).abs() <= 2e-7,
                    "folded learned symbol mismatch",
                )?;
                channel[i][j] = data["CHANNEL"][i * 4 + j] as f32;
            }
            for probabilities in [encoded[i], emission[i], channel[i]] {
                ensure(
                    probabilities.iter().all(|v| *v >= 0. && *v <= 1.)
                        && (probabilities.iter().sum::<f32>() - 1.).abs() < 1e-6,
                    "invalid probability constant",
                )?;
            }
        }
        let fp32 = |name| data[name].iter().map(|v| *v as f32).collect();
        Ok(Self {
            identity: format!("{}:bytes-{:016x}", header[1], checksum(text.as_bytes())),
            checkpoint_sha: header[1].into(),
            control: header[2].into(),
            threshold,
            q,
            phase,
            encoded,
            emission,
            channel,
            h0w: fp32("H0W"),
            h0b: fp32("H0B"),
            h2w: fp32("H2W"),
            h2b: fp32("H2B"),
            cache: BTreeMap::new(),
        })
    }
    pub fn initial(&self, tokens: [usize; 4]) -> Result<Beliefs> {
        let mut state = [[0.; 40]; 4];
        for key in 0..4 {
            ensure(tokens[key] < 4, "initial token")?;
            for phase in 0..10 {
                for code in 0..4 {
                    state[key][phase * 4 + code] =
                        self.phase[phase] * self.encoded[tokens[key]][code] as f64;
                }
            }
        }
        Ok(state)
    }
    pub fn write(&self, state: &mut Beliefs, key: usize, token: usize) -> Result<()> {
        ensure(key < 4 && token < 4, "write address/token")?;
        for phase in 0..10 {
            let mass = state[key][phase * 4..phase * 4 + 4].iter().sum::<f64>();
            for code in 0..4 {
                state[key][phase * 4 + code] = mass * self.encoded[token][code] as f64;
            }
        }
        Ok(())
    }
    pub fn advance(&mut self, state: &mut Beliefs, dt: f64) -> Result<()> {
        let key = dt.to_bits();
        if !self.cache.contains_key(&key) {
            self.cache
                .insert(key, numeric::propagate(&self.q, dt, &[0.; 40])?.p);
        }
        for row in state {
            *row = numeric::row(row, &self.cache[&key]);
        }
        Ok(())
    }
    fn observed(&self, state: &Vector, token: usize) -> Result<Vector> {
        ensure(token < 4, "read token")?;
        let mut out = *state;
        for i in 0..40 {
            out[i] *= self.emission[i % 4][token] as f64;
        }
        let mass = out.iter().sum::<f64>();
        ensure(mass.is_finite() && mass > 1e-250, "read normalization")?;
        for value in &mut out {
            *value /= mass;
        }
        Ok(out)
    }
    pub fn apply_read(&self, state: &mut Beliefs, key: usize, token: usize) -> Result<()> {
        ensure(key < 4, "read address")?;
        state[key] = self.observed(&state[key], token)?;
        Ok(())
    }
    pub fn logits(&self, state: &Vector) -> [f32; 4] {
        let mut hidden = [0_f32; 32];
        for i in 0..32 {
            let mut sum = self.h0b[i];
            for j in 0..40 {
                sum += self.h0w[i * 40 + j] * state[j] as f32;
            }
            hidden[i] = sum.tanh();
        }
        std::array::from_fn(|i| {
            let mut sum = self.h2b[i];
            for j in 0..32 {
                sum += self.h2w[i * 32 + j] * hidden[j];
            }
            sum
        })
    }
    pub fn choose(&self, state: &Beliefs, key: usize, fee: f32) -> Result<Decision> {
        ensure(key < 4 && fee.is_finite() && fee >= 0., "decision context")?;
        let pre_logits = self.logits(&state[key]);
        let pre_prob = softmax(pre_logits);
        let mut post_logits = [[0.; 4]; 4];
        let mut post_prob = [[0.; 4]; 4];
        let mut min_head_gap = maximum(&pre_logits).2;
        let mut read_value = 0_f32;
        for token in 0..4 {
            post_logits[token] = self.logits(&self.observed(&state[key], token)?);
            post_prob[token] = softmax(post_logits[token]);
            min_head_gap = min_head_gap.min(maximum(&post_logits[token]).2);
            let mut chance = 0_f32;
            for code in 0..4 {
                chance += pre_prob[code] * self.channel[code][token];
            }
            read_value += chance * maximum(&post_prob[token]).1;
        }
        let signed = read_value - fee - maximum(&pre_prob).1;
        let read = if self.control == "value" {
            signed > 0.
        } else {
            fee <= self.threshold
        };
        let action_gap = if self.control == "value" {
            signed.abs()
        } else {
            (fee - self.threshold).abs()
        };
        ensure(
            pre_logits
                .iter()
                .chain(pre_prob.iter())
                .chain(post_logits.iter().flatten())
                .chain(post_prob.iter().flatten())
                .all(|v| v.is_finite())
                && read_value.is_finite()
                && action_gap.is_finite(),
            "nonfinite learned decision",
        )?;
        ensure(min_head_gap > 2e-5, "UNCERTIFIED_LEARNED_HEAD_GAP")?;
        ensure(
            self.control != "value" || action_gap > 5e-5,
            "UNCERTIFIED_LEARNED_ACTION_GAP",
        )?;
        Ok(Decision {
            read,
            answer_before: maximum(&pre_logits).0,
            pre_logits,
            pre_prob,
            post_logits,
            post_prob,
            read_value,
            action_gap,
            min_head_gap,
        })
    }
    pub fn answer(&self, state: &Beliefs, key: usize) -> Result<(usize, f32)> {
        ensure(key < 4, "answer address")?;
        let (answer, _, gap) = maximum(&self.logits(&state[key]));
        ensure(gap > 2e-5, "UNCERTIFIED_LEARNED_ANSWER_GAP")?;
        Ok((answer, gap))
    }
}
