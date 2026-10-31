//! Actual encoder, recurrent content, policy and decoder inference.
use crate::codec::{Packet, Result};
use crate::math::{cat, linear, norm, passage, sigmoid, softplus, tanh};
pub const ACTIONS: [&str; 7] = [
    "shared", "image", "audio", "video", "text", "verify", "stop",
];
pub const MODALITIES: [&str; 4] = ["image", "audio", "video", "text"];
pub use crate::state::State;
pub struct Model {
    pub weights: Packet,
    pub width: usize,
    pub depth: usize,
    pub mode: String,
    pub boundary: String,
    pub initial_stop: bool,
    pub suppress_verify: bool,
}
impl Model {
    pub fn new(weights: Packet) -> Result<Self> {
        if weights.text("kind")? != "joint-generator-weights-v3" {
            return Err("wrong weight packet".into());
        }
        let width = weights
            .text("width")?
            .parse::<usize>()
            .map_err(|e| e.to_string())?;
        let depth = weights
            .text("depth")?
            .parse::<usize>()
            .map_err(|e| e.to_string())?;
        if !(1..=256).contains(&width) || !(1..=8).contains(&depth) {
            return Err("native width/depth bound".into());
        }
        let mode = weights.text("mode")?.to_string();
        let boundary = weights.text("boundary")?.to_string();
        if !["dual", "single", "no_adaptation", "ordinary"].contains(&mode.as_str())
            || !["fixed", "direct"].contains(&boundary.as_str())
        {
            return Err("unsupported core profile".into());
        }
        if weights.text("numeric_profile")? != "fp64-linux-libm-v1" {
            return Err("unknown numeric profile".into());
        }
        let initial_stop = weights
            .text("allow_initial_stop")?
            .parse::<bool>()
            .map_err(|e| e.to_string())?;
        let suppress_verify = weights
            .text("suppress_redundant_verify")?
            .parse::<bool>()
            .map_err(|e| e.to_string())?;
        let model = Self {
            weights,
            width,
            depth,
            mode,
            boundary,
            initial_stop,
            suppress_verify,
        };
        model.validate_weights()?;
        Ok(model)
    }
    fn validate_weights(&self) -> Result<()> {
        let w = self.width;
        let mut expected = std::collections::BTreeMap::new();
        let mut add = |name: String, shape: Vec<usize>| {
            expected.insert(name, shape);
        };
        for (name, o, i, bias) in [
            ("image_encoder.0", w, 1536, true),
            ("audio_encoder.0", w, 2048, true),
            ("video_encoder.0", w, 4 * w, true),
            ("encoder_fusion.0", w, 4 * w, true),
            ("initial_slots", 4 * w, w, true),
            ("feedback_projection", w, 3, true),
            ("transition_input", w, 3 * w, true),
            ("emissions.text", 80, 2 * w, true),
        ] {
            add(format!("{name}.weight"), vec![o, i]);
            if bias {
                add(format!("{name}.bias"), vec![o]);
            }
        }
        add("token_encoder.weight".into(), vec![128, w]);
        add("action_embedding.weight".into(), vec![5, w]);
        for m in MODALITIES {
            add(format!("adapters.{m}.0.weight"), vec![w, 3 * w]);
            add(format!("adapters.{m}.0.bias"), vec![w]);
        }
        for (m, h, o) in [("image", 64, 768), ("audio", 64, 1024), ("video", 96, 3072)] {
            add(format!("emissions.{m}.0.weight"), vec![h, 2 * w]);
            add(format!("emissions.{m}.0.bias"), vec![h]);
            add(format!("emissions.{m}.2.weight"), vec![o, h]);
            add(format!("emissions.{m}.2.bias"), vec![o]);
        }
        for name in ["actor", "critic", "delivery_critic"] {
            add(format!("{name}.0.weight"), vec![w, 2 * w + 5]);
            add(format!("{name}.0.bias"), vec![w]);
            let o = if name == "actor" { 7 } else { 1 };
            add(format!("{name}.2.weight"), vec![o, w]);
            add(format!("{name}.2.bias"), vec![o]);
        }
        for l in 0..self.depth {
            let p = format!("core.layers.{l}");
            for name in [
                "drift_bias",
                "raw_diffusion",
                "raw_recovery",
                "raw_regeneration",
                "raw_adaptation",
                "raw_adaptation_decay",
                "raw_content_rate",
            ] {
                add(format!("{p}.{name}"), vec![w]);
            }
            add(
                format!(
                    "{p}.{}",
                    if self.boundary == "direct" {
                        "raw_boundary"
                    } else {
                        "fixed_boundary"
                    }
                ),
                vec![w],
            );
            for name in ["drift_input", "content_state", "output"] {
                add(format!("{p}.{name}.weight"), vec![w, w]);
            }
            add(format!("{p}.content_input.weight"), vec![w, w]);
            add(format!("{p}.content_input.bias"), vec![w]);
            let g = if self.mode == "single" { w } else { 2 * w };
            add(format!("{p}.channel_gates.weight"), vec![g, 2 * w]);
            add(format!("{p}.channel_gates.bias"), vec![g]);
            add(format!("{p}.norm.weight"), vec![w]);
            add(format!("{p}.norm.bias"), vec![w]);
        }
        if expected.len() != self.weights.tensors.len() {
            return Err("unknown or missing model tensor".into());
        }
        for (name, shape) in expected {
            if self
                .weights
                .tensors
                .get(&name)
                .is_none_or(|t| t.shape != shape)
            {
                return Err(format!("model shape mismatch {name}"));
            }
        }
        Ok(())
    }
    pub fn validate_input(&self, p: &Packet) -> Result<()> {
        if p.text("kind")? != "joint-generator-public-v3" || p.tensors.len() != 7 {
            return Err("public schema mismatch".into());
        }
        for (name, shape) in [
            ("image", vec![1, 3, 16, 16]),
            ("image_mask", vec![1, 3, 16, 16]),
            ("audio", vec![1, 1024]),
            ("audio_mask", vec![1, 1024]),
            ("video", vec![1, 4, 3, 16, 16]),
            ("video_mask", vec![1, 4, 3, 16, 16]),
        ] {
            let x = p.get(name)?;
            if p.tensors[name].shape != shape
                || x.iter()
                    .any(|v| v.abs() > 1.0 || name.ends_with("_mask") && *v < 0.0)
            {
                return Err(format!("public shape/range {name}"));
            }
        }
        let tokens = p.get("tokens")?;
        if p.tensors["tokens"].shape != vec![1, tokens.len()]
            || tokens.is_empty()
            || tokens.len() > 4096
            || tokens
                .iter()
                .any(|v| *v < 0.0 || *v >= 128.0 || v.fract() != 0.0)
        {
            return Err("token domain".into());
        }
        Ok(())
    }
    pub fn encode(&self, p: &Packet) -> Result<State> {
        self.validate_input(p)?;
        let w = self.width;
        let image = tanh(linear(
            &self.weights,
            "image_encoder.0",
            &cat(&[p.get("image")?, p.get("image_mask")?]),
        )?);
        let mut frames = Vec::new();
        let video = p.get("video")?;
        let mask = p.get("video_mask")?;
        for i in 0..4 {
            frames.extend(tanh(linear(
                &self.weights,
                "image_encoder.0",
                &cat(&[
                    &video[i * 768..(i + 1) * 768],
                    &mask[i * 768..(i + 1) * 768],
                ]),
            )?));
        }
        let video = tanh(linear(&self.weights, "video_encoder.0", &frames)?);
        let audio = tanh(linear(
            &self.weights,
            "audio_encoder.0",
            &cat(&[p.get("audio")?, p.get("audio_mask")?]),
        )?);
        let mut text = vec![0.0; w];
        let table = self.weights.get("token_encoder.weight")?;
        let tokens = p.get("tokens")?;
        for token in tokens {
            let i = *token as usize;
            for j in 0..w {
                text[j] += table[i * w + j] / tokens.len() as f64;
            }
        }
        let context = tanh(linear(
            &self.weights,
            "encoder_fusion.0",
            &cat(&[&image, &audio, &video, &text]),
        )?);
        let slots = tanh(linear(&self.weights, "initial_slots", &context)?);
        let mut core = vec![[vec![0.0; w], vec![0.0; w], vec![0.0; w], vec![0.0; w]]; self.depth];
        core[0][0] = tanh(context.clone());
        Ok(State {
            shared: context.clone(),
            context,
            slots,
            core,
            feedback: vec![0.0; 3],
            steps: 0,
            stopped: false,
            verified: false,
            content_revision: 0,
            verified_revision: -1,
        })
    }
    pub fn outputs(&self, s: &State) -> Result<Vec<Vec<f64>>> {
        let mut result = Vec::new();
        for (i, m) in MODALITIES.iter().enumerate() {
            let input = cat(&[&s.shared, &s.slots[i * self.width..(i + 1) * self.width]]);
            result.push(if *m == "text" {
                linear(&self.weights, "emissions.text", &input)?
            } else {
                linear(
                    &self.weights,
                    &format!("emissions.{m}.2"),
                    &tanh(linear(&self.weights, &format!("emissions.{m}.0"), &input)?),
                )?
            });
        }
        Ok(result)
    }
    pub fn features(&self, s: &State, remaining: f64) -> Vec<f64> {
        let mut means = vec![0.0; self.width];
        for slot in s.slots.chunks_exact(self.width) {
            for (i, v) in slot.iter().enumerate() {
                means[i] += v / 4.0;
            }
        }
        cat(&[
            &s.shared,
            &means,
            &s.feedback,
            &[remaining, s.steps as f64 / 8.0],
        ])
    }
    pub fn inspect(&self, s: &State, remaining: f64) -> Result<Packet> {
        if !remaining.is_finite() || !(0.0..=1.0).contains(&remaining) {
            return Err("remaining budget fraction".into());
        }
        let mut p = s.packet();
        let outputs = self.outputs(s)?;
        for (m, x) in MODALITIES.iter().zip(outputs) {
            p.vector(&format!("output.{m}"), x);
        }
        let x = self.features(s, remaining);
        for name in ["actor", "critic", "delivery_critic"] {
            let mut y = linear(
                &self.weights,
                &format!("{name}.2"),
                &tanh(linear(&self.weights, &format!("{name}.0"), &x)?),
            )?;
            if name == "actor" {
                p.vector("actor.logits", y.clone());
                let mut legal = [true; 7];
                if s.steps == 0 && !self.initial_stop {
                    legal[6] = false;
                }
                if self.suppress_verify && s.verified {
                    legal[5] = false;
                }
                if s.steps >= 6 || s.stopped {
                    legal = [false, false, false, false, false, false, true];
                }
                let max = y
                    .iter()
                    .enumerate()
                    .filter(|(i, _)| legal[*i])
                    .map(|(_, v)| *v)
                    .fold(f64::NEG_INFINITY, f64::max);
                let mut total = 0.0;
                for (i, v) in y.iter_mut().enumerate() {
                    *v = if legal[i] { (*v - max).exp() } else { 0.0 };
                    total += *v;
                }
                for v in &mut y {
                    *v /= total;
                }
                p.vector("policy.probabilities", y);
            } else {
                p.vector(name, y);
            }
        }
        Ok(p)
    }
    pub fn advance(&self, s: &State, action: &str, public: &Packet) -> Result<State> {
        if s.stopped
            || !ACTIONS.contains(&action)
            || s.steps >= 6 && action != "stop"
            || s.steps == 0 && action == "stop" && !self.initial_stop
        {
            return Err("illegal continuation".into());
        }
        let mut next = s.clone();
        next.steps += 1;
        if action == "stop" {
            next.stopped = true;
            return Ok(next);
        }
        if action == "verify" {
            if self.suppress_verify && s.verified {
                return Err("redundant verification masked".into());
            }
            let out = self.outputs(s)?;
            for (i, m) in ["image", "audio", "video"].iter().enumerate() {
                let target = public.get(m)?;
                let mask = public.get(&format!("{m}_mask"))?;
                next.feedback[i] = out[i]
                    .iter()
                    .zip(target)
                    .zip(mask)
                    .map(|((v, t), mask)| {
                        let v = if i == 1 { v.tanh() } else { sigmoid(*v) };
                        (v - t).powi(2) * mask
                    })
                    .sum::<f64>()
                    / target.len() as f64;
            }
            next.verified = true;
            next.verified_revision = s.content_revision as i64;
            return Ok(next);
        }
        next.verified = false;
        next.content_revision += 1;
        let w = self.width;
        let mut means = vec![0.0; w];
        for slot in s.slots.chunks_exact(w) {
            for (i, v) in slot.iter().enumerate() {
                means[i] += v / 4.0;
            }
        }
        let mut signal = linear(
            &self.weights,
            "transition_input",
            &cat(&[&s.context, &s.shared, &means]),
        )?;
        let feedback = linear(&self.weights, "feedback_projection", &s.feedback)?;
        let index = ACTIONS.iter().position(|a| *a == action).unwrap();
        let embedding = self.weights.get("action_embedding.weight")?;
        for i in 0..w {
            signal[i] += embedding[index * w + i];
            signal[i] += feedback[i];
        }
        for l in 0..self.depth {
            let (x, state) = self.layer(l, &signal, &s.core[l])?;
            signal = x;
            next.core[l] = state;
        }
        next.shared = tanh(signal);
        for (i, m) in MODALITIES.iter().enumerate() {
            if action == *m || action == "shared" {
                let slot = &s.slots[i * w..(i + 1) * w];
                let delta = tanh(linear(
                    &self.weights,
                    &format!("adapters.{m}.0"),
                    &cat(&[&next.shared, slot, &s.context]),
                )?);
                for j in 0..w {
                    next.slots[i * w + j] = slot[j] + 0.25 * delta[j];
                }
            }
        }
        Ok(next)
    }
    fn layer(&self, l: usize, x: &[f64], s: &[Vec<f64>; 4]) -> Result<(Vec<f64>, [Vec<f64>; 4])> {
        let p = format!("core.layers.{l}");
        let w = self.width;
        let signal = norm(&self.weights, &format!("{p}.norm"), x)?;
        let gates = linear(
            &self.weights,
            &format!("{p}.channel_gates"),
            &cat(&[&signal, &s[0]]),
        )?;
        let drive = linear(&self.weights, &format!("{p}.drift_input"), &signal)?;
        let ci = linear(&self.weights, &format!("{p}.content_input"), &signal)?;
        let cs = linear(&self.weights, &format!("{p}.content_state"), &s[0])?;
        let get = |name: &str| self.weights.get(&format!("{p}.{name}"));
        let diffusion = get("raw_diffusion")?;
        let recovery = get("raw_recovery")?;
        let regen = get("raw_regeneration")?;
        let bias = get("drift_bias")?;
        let adapt = get("raw_adaptation")?;
        let decay = get("raw_adaptation_decay")?;
        let rate = get("raw_content_rate")?;
        let boundary = get(if self.boundary == "direct" {
            "raw_boundary"
        } else {
            "fixed_boundary"
        })?;
        let mut next = [vec![0.0; w], vec![0.0; w], vec![0.0; w], vec![0.0; w]];
        let dt: f64 = 0.5;
        for i in 0..w {
            let rec = softplus(recovery[i]) * sigmoid(gates[i]);
            let reg = if self.mode == "single" {
                0.0
            } else {
                softplus(regen[i]) * sigmoid(gates[w + i])
            };
            let drift = bias[i] + drive[i].tanh() - rec * s[1][i] + reg * s[3][i] - s[2][i];
            let sigma = softplus(diffusion[i]) + 1e-4;
            let bound = if self.boundary == "direct" {
                softplus(boundary[i]) + 1e-4
            } else {
                boundary[i]
            };
            let (voltage, event) = if self.mode == "ordinary" {
                let event = sigmoid((dt * drift - (bound - s[1][i])) / (sigma * dt.sqrt()));
                ((1.0 - event) * (s[1][i] + dt * drift), event)
            } else {
                passage(s[1][i], bound, drift, sigma, dt)
            };
            let write = 1.0 - (1.0 - event) * (-softplus(rate[i]) * dt).exp();
            next[0][i] = (1.0 - write) * s[0][i] + write * (ci[i] + cs[i]).tanh();
            next[1][i] = voltage;
            next[2][i] = if self.mode == "no_adaptation" {
                s[2][i]
            } else {
                s[2][i] * (-softplus(decay[i]) * dt).exp() + softplus(adapt[i]) * event
            };
            next[3][i] = event;
        }
        let mut result = linear(&self.weights, &format!("{p}.output"), &next[0])?;
        for (i, v) in result.iter_mut().enumerate() {
            *v += x[i];
        }
        Ok((result, next))
    }
}
