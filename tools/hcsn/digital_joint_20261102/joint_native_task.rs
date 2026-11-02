//! Fixed-deadline target with current-at-due sensing; no hidden label or oracle.
use crate::store;
use serde::Deserialize;
use serde::Serialize;
use std::path::Path;

pub const NAMES: [&str; 6] = ["STOP", "WAIT", "READ", "REPAIR", "SUBMIT_0", "SUBMIT_1"];

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Public {
    pub schema: String,
    pub id: String,
    pub deadline: usize,
    pub initial_budget: usize,
    pub target_tick: usize,
    pub prior_distance: f64,
    pub drive: Vec<i32>,
    pub duration: Vec<f64>,
    pub reliability: Vec<f64>,
    pub read_price: Vec<f64>,
    pub read_delay: Vec<usize>,
    pub packets: Vec<String>,
    pub packet_sha256: Vec<String>,
    pub latency_price: f64,
    pub repair_price: f64,
    pub failure_probability: f64,
}

impl Public {
    pub fn validate(&self) -> Result<(), String> {
        if self.schema != "joint-current-at-due-fixed-deadline-v1"
            || self.id.is_empty()
            || self.id.len() > 256
            || self.deadline != 6
            || self.initial_budget != 3
            || self.target_tick != 6
            || ![0.125, 0.375, 0.75].contains(&self.prior_distance)
            || self.drive.iter().any(|x| ![-1, 0, 1].contains(x))
            || [
                self.duration.len(),
                self.drive.len(),
                self.reliability.len(),
                self.read_price.len(),
                self.read_delay.len(),
                self.packets.len(),
                self.packet_sha256.len(),
            ]
            .iter()
            .any(|n| *n != 6)
            || self
                .duration
                .iter()
                .any(|x| !x.is_finite() || *x <= 0.0 || *x > 2.0)
            || self
                .reliability
                .iter()
                .any(|x| !x.is_finite() || !(0.5..=1.0).contains(x))
            || self.read_delay.iter().any(|d| ![1, 2].contains(d))
            || self
                .read_price
                .iter()
                .chain([&self.latency_price, &self.repair_price])
                .any(|x| !x.is_finite() || *x < 0.0)
            || !self.failure_probability.is_finite()
            || !(0.0..=1.0).contains(&self.failure_probability)
            || self.packet_sha256.iter().any(|s| {
                s.len() != 64
                    || !s
                        .bytes()
                        .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
            })
        {
            return Err("public task schema/dimension/numerical envelope".into());
        }
        for name in &self.packets {
            store::relative_packet(Path::new("."), name)?;
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Pending {
    pub source_tick: usize,
    pub due_tick: usize,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Observation {
    pub source_tick: usize,
    pub observation_tick: usize,
    pub observation: usize,
    pub reliability: f64,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct State {
    pub tick: usize,
    pub budget: usize,
    pub pending: Option<Pending>,
    pub broken: bool,
    pub last_symbol: i32,
    pub last_reliability: f64,
    pub history: Vec<Observation>,
    pub elapsed: f64,
    pub charges: f64,
    pub terminal: bool,
    pub submitted: Option<usize>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Completion {
    pub observation_tick: usize,
    #[serde(default, skip_serializing_if = "is_false")]
    pub failure: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub observation: Option<usize>,
}
fn is_false(value: &bool) -> bool {
    !*value
}

impl State {
    pub fn initial() -> Self {
        Self {
            tick: 0,
            budget: 3,
            pending: None,
            broken: false,
            last_symbol: 0,
            last_reliability: 0.5,
            history: vec![],
            elapsed: 0.0,
            charges: 0.0,
            terminal: false,
            submitted: None,
        }
    }

    pub fn validate(&self, public: &Public) -> Result<(), String> {
        if self.tick > 6
            || self.budget > 3
            || self.history.len() > 3
            || !self.elapsed.is_finite()
            || !self.charges.is_finite()
            || self.elapsed < 0.0
            || self.charges < 0.0
            || ![-1, 0, 1].contains(&self.last_symbol)
            || !self.last_reliability.is_finite()
            || !(0.5..=1.0).contains(&self.last_reliability)
            || self.submitted.is_some_and(|x| x > 1)
            || (!self.terminal && self.submitted.is_some())
            || (self.terminal && self.pending.is_some())
        {
            return Err("invalid task checkpoint".into());
        }
        let elapsed = public.duration[..self.tick].iter().sum::<f64>();
        if (elapsed - self.elapsed).abs() > 1e-12 {
            return Err("task elapsed clock mismatch".into());
        }
        if let Some(p) = &self.pending {
            if self.broken
                || p.source_tick >= self.tick
                || p.source_tick >= 6
                || p.due_tick != p.source_tick + public.read_delay[p.source_tick]
                || p.due_tick <= self.tick
                || p.due_tick > 6
            {
                return Err("invalid pending read".into());
            }
        }
        let mut previous = None;
        for item in &self.history {
            if item.source_tick >= item.observation_tick
                || item.source_tick >= 6
                || item.observation_tick > self.tick
                || item.observation_tick != item.source_tick + public.read_delay[item.source_tick]
                || item.observation > 1
                || item.reliability != public.reliability[item.observation_tick - 1]
                || previous.is_some_and(|p| p >= item.observation_tick)
            {
                return Err("invalid observation history".into());
            }
            previous = Some(item.observation_tick);
        }
        let (symbol, reliability) = self
            .history
            .last()
            .map(|x| (2 * x.observation as i32 - 1, x.reliability))
            .unwrap_or((0, 0.5));
        if self.last_symbol != symbol || self.last_reliability != reliability {
            return Err("last observation/history mismatch".into());
        }
        Ok(())
    }

    pub fn legal(&self, public: &Public) -> [bool; 6] {
        if self.terminal {
            return [false; 6];
        }
        let before = self.tick < 6;
        let read = before
            && self.budget > 0
            && !self.broken
            && self.pending.is_none()
            && self.tick + public.read_delay[self.tick] <= 6;
        [true, before, read, before && self.broken, true, true]
    }

    pub fn due(&self, public: &Public, action: usize) -> Result<Option<usize>, String> {
        if action >= 6 || !self.legal(public)[action] {
            return Err("illegal action; state unchanged".into());
        }
        if [0, 4, 5].contains(&action) {
            return Ok(None);
        }
        let created = Pending {
            source_tick: self.tick,
            due_tick: self.tick + public.read_delay[self.tick],
        };
        let pending = if action == 2 {
            Some(&created)
        } else {
            self.pending.as_ref()
        };
        Ok(pending
            .filter(|p| p.due_tick == self.tick + 1)
            .map(|p| p.due_tick - 1))
    }

    pub fn successor(
        &self,
        public: &Public,
        action: usize,
        completion: Option<&Completion>,
    ) -> Result<Self, String> {
        let source = self.due(public, action)?;
        if source.is_some() != completion.is_some() {
            return Err("unsolicited or missing completion".into());
        }
        let mut s = self.clone();
        if [0, 4, 5].contains(&action) {
            s.terminal = true;
            s.submitted = if action == 0 { None } else { Some(action - 4) };
            s.pending = None;
            return Ok(s);
        }
        let tick = s.tick;
        if action == 2 {
            s.budget -= 1;
            s.charges += public.read_price[tick];
            s.pending = Some(Pending {
                source_tick: tick,
                due_tick: tick + public.read_delay[tick],
            });
        } else if action == 3 {
            s.broken = false;
            s.charges += public.repair_price;
        }
        s.tick += 1;
        s.elapsed += public.duration[tick];
        s.charges += public.latency_price * public.duration[tick];
        if let Some(source_slot) = source {
            let done = completion.ok_or("missing completion")?;
            if done.observation_tick != source_slot + 1 || done.observation_tick != s.tick {
                return Err("current-at-due completion tick mismatch".into());
            }
            let source_tick = s
                .pending
                .as_ref()
                .ok_or("missing pending request")?
                .source_tick;
            s.pending = None;
            if done.failure {
                if done.observation.is_some() {
                    return Err("failure and observation conflict".into());
                }
                s.broken = true;
            } else {
                let y = done
                    .observation
                    .filter(|y| *y <= 1)
                    .ok_or("binary completion required")?;
                let reliability = public.reliability[source_slot];
                s.history.push(Observation {
                    source_tick,
                    observation_tick: done.observation_tick,
                    observation: y,
                    reliability,
                });
                s.last_symbol = 2 * y as i32 - 1;
                s.last_reliability = reliability;
            }
        }
        s.validate(public)?;
        Ok(s)
    }

    pub fn public_features(&self, public: &Public) -> Vec<f64> {
        let mut v = vec![
            self.tick as f64 / 6.0,
            self.budget as f64 / 3.0,
            self.elapsed / 9.0,
            self.charges,
            f64::from(u8::from(self.broken)),
            f64::from(u8::from(self.pending.is_some())),
            self.pending
                .as_ref()
                .map(|p| (p.due_tick - self.tick) as f64 / 2.0)
                .unwrap_or(0.0),
            self.last_symbol as f64,
            self.last_reliability,
            public.latency_price,
            public.repair_price,
            public.failure_probability,
        ];
        for i in 0..6 {
            v.extend([
                public.duration[i] / 2.0,
                public.reliability[i],
                public.read_price[i],
                public.read_delay[i] as f64 / 2.0,
            ]);
        }
        v.extend(public.drive.iter().map(|x| f64::from(*x)));
        v.push(public.prior_distance);
        v
    }

    pub fn history_features(&self) -> [f64; 12] {
        let mut out = [0.0; 12];
        for item in &self.history {
            out[item.observation_tick - 1] = 2.0 * item.observation as f64 - 1.0;
            out[5 + item.observation_tick] = 2.0 * item.reliability - 1.0;
        }
        out
    }
}

pub fn public_names() -> Vec<String> {
    let mut names = [
        "tick_fraction",
        "budget_fraction",
        "elapsed_over_9",
        "charges",
        "broken",
        "pending",
        "pending_slots_over_2",
        "last_symbol",
        "last_reliability",
        "latency_price",
        "repair_price",
        "failure_probability",
    ]
    .iter()
    .map(|s| (*s).to_owned())
    .collect::<Vec<_>>();
    for i in 0..6 {
        for name in [
            "duration_over_2",
            "reliability",
            "read_price",
            "delay_over_2",
        ] {
            names.push(format!("slot_{i}_{name}"));
        }
    }
    names.extend((0..6).map(|i| format!("drive_{i}")));
    names.push("prior_distance".into());
    names
}

pub fn fixed_action(state: &State, legal: [bool; 6], belief: f64) -> usize {
    let submit = if belief > 0.5 { 5 } else { 4 };
    if belief.max(1.0 - belief) >= 0.8
        || state.tick == 6
        || (state.budget == 0 && state.pending.is_none())
    {
        return submit;
    }
    if legal[3] {
        3
    } else if legal[2] {
        2
    } else if legal[1] {
        1
    } else {
        submit
    }
}
