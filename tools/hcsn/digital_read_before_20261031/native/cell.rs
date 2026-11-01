//! Hard sampling of the exported 17-state projected process, with exact table lookup.
use serde::Deserialize;
use serde::Serialize;
use std::collections::BTreeMap;

pub const STATES: usize = 17;
pub const FEATURES: usize = 12;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Context {
    pub dt: f64,
    pub symbol: f64,
    pub reliability: f64,
    pub transition: [[f64; STATES]; STATES],
    pub event_probability: [f64; STATES],
    pub features: [[f64; FEATURES]; STATES],
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ResetLaw {
    pub kind: String,
    pub normalized_sd: f64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Kernel {
    pub schema: String,
    pub mode: String,
    pub n_grid: usize,
    pub n_states: usize,
    pub state_order: String,
    pub raw_names: Vec<String>,
    pub raw: Vec<f64>,
    pub physical: BTreeMap<String, f64>,
    pub effective_parameter_count: usize,
    pub image_terms: usize,
    pub maximum_duration: f64,
    pub reset_law: ResetLaw,
    pub feature_contract: String,
    pub feature_names: Vec<String>,
    pub thresholds: Vec<f64>,
    pub horizons: Vec<f64>,
    pub initial: [f64; STATES],
    pub contexts: Vec<Context>,
    pub approximation: String,
}

impl Kernel {
    pub fn validate(&self, family: &str) -> Result<(), String> {
        let mode = match family {
            "ordinary_base" | "ordinary_bank" => "ordinary",
            "clocked_bank" => "clocked",
            "first_passage_bank" => "first_passage",
            _ => return Err("unsupported kernel family".into()),
        };
        let raw_names = [
            "boundary",
            "diffusion",
            "gain",
            "drift_bias",
            "reset_plus",
            "reset_minus",
            "recovery_rate",
        ];
        if self.schema != "digital-read-before-brownian-images-v1"
            || self.mode != mode
            || self.n_grid != 15
            || self.n_states != STATES
            || self.raw_names != raw_names
            || self.raw.len() != 7
            || self
                .raw
                .iter()
                .chain(self.physical.values())
                .any(|x| !x.is_finite())
            || self.physical.len() != 7
            || raw_names.iter().any(|n| !self.physical.contains_key(*n))
            || self.maximum_duration != 2.0
            || self.image_terms != 12
            || self.reset_law.kind != "folded Gaussian"
            || self.reset_law.normalized_sd != 0.12
            || self.feature_contract
                != "free_endpoint_conditional_on_active; refractory rows have no free forecast"
            || self.thresholds != [-0.5, 0.0, 0.5]
            || self.horizons != [0.25, 0.75, 1.5]
            || self.feature_names != representation_names(family)
            || self.effective_parameter_count != if mode == "ordinary" { 4 } else { 7 }
            || self
                .initial
                .iter()
                .enumerate()
                .any(|(i, p)| *p != if i == 7 { 1.0 } else { 0.0 })
            || self.contexts.is_empty()
            || self.contexts.len() > 2048
        {
            return Err("kernel schema/physical identity mismatch".into());
        }
        for (ci, context) in self.contexts.iter().enumerate() {
            if !context.dt.is_finite()
                || !(0.0..=2.0).contains(&context.dt)
                || ![-1.0, 0.0, 1.0].contains(&context.symbol)
                || !context.reliability.is_finite()
                || !(0.5..=1.0).contains(&context.reliability)
                || self.contexts[..ci].iter().any(|x| {
                    x.dt == context.dt
                        && x.symbol == context.symbol
                        && x.reliability == context.reliability
                })
            {
                return Err("invalid/duplicate kernel context".into());
            }
            for i in 0..STATES {
                let row = &context.transition[i];
                if row
                    .iter()
                    .any(|p| !p.is_finite() || *p < 0.0 || *p > 1.0 + 1e-10)
                    || (row.iter().sum::<f64>() - 1.0).abs() > 1e-8
                    || !context.event_probability[i].is_finite()
                    || !(0.0..=1.0 + 1e-10).contains(&context.event_probability[i])
                    || context.features[i].iter().any(|x| !x.is_finite())
                {
                    return Err("nonstochastic/nonfinite exported table".into());
                }
                if context.dt == 0.0
                    && row
                        .iter()
                        .enumerate()
                        .any(|(j, p)| *p != if j == i { 1.0 } else { 0.0 })
                {
                    return Err("zero duration must be identity".into());
                }
                let expected_event = if context.dt == 0.0 || i >= 15 || mode == "ordinary" {
                    0.0
                } else {
                    row[15] + row[16]
                };
                if (expected_event - context.event_probability[i]).abs() > 1e-8 {
                    return Err("event probability differs from transition contract".into());
                }
                if i >= 15
                    && (context.features[i][..10].iter().any(|x| *x != 0.0)
                        || context.features[i][10] != if i == 15 { 1.0 } else { 0.0 }
                        || context.features[i][11] != if i == 16 { 1.0 } else { 0.0 })
                {
                    return Err("refractory features violate active-only forecast".into());
                }
                if family != "ordinary_base"
                    && context.features[i][..9]
                        .iter()
                        .any(|x| !(0.0..=1.0).contains(x))
                {
                    return Err("invalid digital probability feature".into());
                }
            }
        }
        Ok(())
    }

    pub fn lookup(&self, dt: f64, symbol: i32, reliability: f64) -> Result<&Context, String> {
        self.contexts
            .iter()
            .find(|x| x.dt == dt && x.symbol == symbol as f64 && x.reliability == reliability)
            .ok_or_else(|| {
                format!(
                    "missing exact kernel context dt={dt} symbol={symbol} reliability={reliability}"
                )
            })
    }
}

pub fn representation_names(family: &str) -> Vec<String> {
    if family == "raw_history" {
        return (0..6)
            .map(|i| format!("history_symbol_{i}"))
            .chain((0..6).map(|i| format!("history_reliability_{i}")))
            .collect();
    }
    let mut names = if family == "ordinary_base" {
        (2..=10)
            .map(|i| format!("position_power_{i}"))
            .collect::<Vec<_>>()
    } else {
        ["0.25", "0.75", "1.5"]
            .iter()
            .flat_map(|h| {
                ["-0.5", "0", "0.5"]
                    .iter()
                    .map(move |k| format!("call_h{h}_k{k}"))
            })
            .collect()
    };
    names.extend(
        ["position", "lower_refractory", "upper_refractory"]
            .iter()
            .map(|s| (*s).into()),
    );
    names
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct State {
    pub index: usize,
    pub rng_hex: String,
    pub draws: u64,
    pub events: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Draw {
    pub before: usize,
    pub after: usize,
    pub uniform: f64,
    pub probability_of_event: f64,
    pub event: bool,
}

impl State {
    pub fn new(seed: u64) -> Self {
        Self {
            index: 7,
            rng_hex: format!("{seed:016x}"),
            draws: 0,
            events: 0,
        }
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.index >= STATES
            || self.rng_hex.len() != 16
            || u64::from_str_radix(&self.rng_hex, 16).is_err()
            || self.events > self.draws
        {
            return Err("cell checkpoint envelope".into());
        }
        Ok(())
    }

    pub fn advance(&mut self, context: &Context) -> Result<Draw, String> {
        self.validate()?;
        if context.dt <= 0.0 {
            return Err("sampling requires advancing interval".into());
        }
        let before = self.index;
        let rng = u64::from_str_radix(&self.rng_hex, 16)
            .map_err(|e| e.to_string())?
            .wrapping_add(0x9e3779b97f4a7c15);
        let mut z = (rng ^ (rng >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94d049bb133111eb);
        z ^= z >> 31;
        let uniform = (z >> 11) as f64 * (1.0 / 9_007_199_254_740_992.0);
        let mut cumulative = 0.0;
        let mut after = STATES - 1;
        for (j, probability) in context.transition[before].iter().enumerate() {
            cumulative += probability;
            if uniform < cumulative {
                after = j;
                break;
            }
        }
        let event = before < 15 && after >= 15;
        self.index = after;
        self.rng_hex = format!("{rng:016x}");
        self.draws += 1;
        self.events += u64::from(event);
        Ok(Draw {
            before,
            after,
            uniform,
            probability_of_event: context.event_probability[before],
            event,
        })
    }
}
