//! Exact inherited factorial task semantics. Labels are never loaded here.
use serde::Deserialize;
use serde::Serialize;
use std::path::Component;
use std::path::Path;

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Action {
    Stop,
    Skip,
    Read,
    Fire,
}
impl Action {
    pub const ALL: [Self; 4] = [Self::Stop, Self::Skip, Self::Read, Self::Fire];
    pub fn index(self) -> usize {
        match self {
            Self::Stop => 0,
            Self::Skip => 1,
            Self::Read => 2,
            Self::Fire => 3,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Public {
    pub id: String,
    pub deadline: usize,
    pub budget: usize,
    pub reliability: Vec<Vec<f64>>,
    pub price: Vec<Vec<f64>>,
    pub duration: Vec<f64>,
    pub packets: Vec<Vec<String>>,
    pub packet_sha256: Vec<Vec<String>>,
    pub multiplier: f64,
    pub latency_price: f64,
}

impl Public {
    pub fn validate(&self) -> Result<(), String> {
        if self.id.is_empty()
            || self.id.len() > 128
            || !(2..=10).contains(&self.deadline)
            || self.budget > 10
            || self.duration.len() != self.deadline
            || !self.multiplier.is_finite()
            || self.multiplier < 0.0
            || !self.latency_price.is_finite()
            || self.latency_price < 0.0
            || [&self.reliability, &self.price]
                .iter()
                .any(|rows| rows.len() != 2 || rows.iter().any(|r| r.len() != self.deadline))
            || [&self.packets, &self.packet_sha256]
                .iter()
                .any(|rows| rows.len() != 2 || rows.iter().any(|r| r.len() != self.deadline))
            || self
                .reliability
                .iter()
                .flatten()
                .any(|v| !v.is_finite() || !(0.0..=1.0).contains(v))
            || self
                .price
                .iter()
                .flatten()
                .any(|v| !v.is_finite() || *v < 0.0)
            || self.duration.iter().any(|v| {
                !v.is_finite()
                    || *v < 1e-6
                    || *v > 64.0
                    || (v * 1e6 - (v * 1e6).round()).abs() > 1e-6
            })
        {
            return Err("public task envelope".into());
        }
        for j in 0..2 {
            for t in 0..self.deadline {
                let name = &self.packets[j][t];
                let mut parts = Path::new(name).components();
                if !matches!(parts.next(), Some(Component::Normal(_)))
                    || parts.next().is_some()
                    || name != &format!("job{j}_tick{t}.json")
                    || self.packet_sha256[j][t].len() != 64
                    || !self.packet_sha256[j][t]
                        .bytes()
                        .all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase())
                {
                    return Err("public packet identity".into());
                }
            }
        }
        if self
            .price
            .iter()
            .flatten()
            .any(|p| !(p * self.multiplier * 32.0).is_finite())
            || !(self.duration.iter().sum::<f64>() * self.latency_price * 32.0).is_finite()
        {
            return Err("task cost overflow".into());
        }
        Ok(())
    }

    pub fn elapsed(&self, tick: usize, steps: usize) -> f64 {
        self.duration[tick.min(self.deadline)..(tick + steps).min(self.deadline)]
            .iter()
            .sum()
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Answer {
    pub job: usize,
    pub prediction: usize,
    pub posterior: f64,
    pub tick: usize,
    pub reads: usize,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Counts {
    #[serde(rename = "READ")]
    pub read: u64,
    #[serde(rename = "SKIP")]
    pub skip: u64,
    #[serde(rename = "FIRE")]
    pub fire: u64,
    #[serde(rename = "STOP")]
    pub stop: u64,
    pub content_invocations: u64,
    pub packet_file_reads: u64,
    pub failed_read_attempts: u64,
    pub payload_bytes: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Event {
    pub action: Action,
    pub job: usize,
    pub tick: usize,
    pub budget_before: usize,
    pub posterior_before: f64,
    pub pending_packet: Option<String>,
    pub duration: f64,
    pub query_charge: f64,
    pub latency_charge: f64,
    pub observation: Option<usize>,
    pub payload_sha256: Option<String>,
    pub payload_bytes: u64,
    pub error: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct State {
    pub job: usize,
    pub tick: usize,
    pub budget: usize,
    pub posterior: f64,
    pub terminal: bool,
    pub reads_in_job: usize,
    pub query_cost: f64,
    pub latency_cost: f64,
    pub charged_cost: f64,
    pub task_elapsed: f64,
    pub elapsed_micros: u64,
    pub answers: Vec<Answer>,
    pub counts: Counts,
    pub history: Vec<Event>,
    pub in_flight: Option<Action>,
    pub pending_observation: Option<String>,
    pub recovery_ticks_remaining: usize,
}

impl State {
    pub fn initial(public: &Public) -> Self {
        Self {
            job: 0,
            tick: 0,
            budget: public.budget,
            posterior: 0.5,
            terminal: false,
            reads_in_job: 0,
            query_cost: 0.0,
            latency_cost: 0.0,
            charged_cost: 0.0,
            task_elapsed: 0.0,
            elapsed_micros: 0,
            answers: vec![],
            counts: Counts::default(),
            history: vec![],
            in_flight: None,
            pending_observation: None,
            recovery_ticks_remaining: 0,
        }
    }

    pub fn legal(&self, public: &Public) -> [bool; 4] {
        let active = !self.terminal && self.job < 2 && self.tick < public.deadline;
        [
            !self.terminal,
            active && self.tick + 1 < public.deadline,
            active && self.budget > 0 && self.tick + 1 < public.deadline,
            active,
        ]
    }

    pub fn driver(&self, public: &Public) -> f64 {
        0.8 * (2.0 * self.posterior - 1.0)
            + 0.2 * (2.0 * public.reliability[self.job][self.tick] - 1.0)
    }

    pub fn event(&self, public: &Public, action: Action) -> Result<Event, String> {
        if !self.legal(public)[action.index()] {
            return Err("illegal autonomous action".into());
        }
        let duration = match action {
            Action::Stop => 0.0,
            Action::Fire => public.elapsed(self.tick, 2),
            Action::Read | Action::Skip => public.elapsed(self.tick, 1),
        };
        Ok(Event {
            action,
            job: self.job,
            tick: self.tick,
            budget_before: self.budget,
            posterior_before: self.posterior,
            pending_packet: Some(public.packets[self.job][self.tick].clone()),
            duration,
            query_charge: if action == Action::Read {
                public.multiplier * public.price[self.job][self.tick]
            } else {
                0.0
            },
            latency_charge: public.latency_price * duration,
            observation: None,
            payload_sha256: None,
            payload_bytes: 0,
            error: None,
        })
    }

    pub fn apply(
        &mut self,
        public: &Public,
        confusion: [[f64; 2]; 2],
        event: Event,
    ) -> Result<(), String> {
        let expected = self.event(public, event.action)?;
        if expected.job != event.job
            || expected.tick != event.tick
            || expected.budget_before != event.budget_before
            || expected.posterior_before != event.posterior_before
            || expected.pending_packet != event.pending_packet
            || expected.duration != event.duration
            || expected.query_charge != event.query_charge
            || expected.latency_charge != event.latency_charge
        {
            return Err("task event prefix mismatch".into());
        }
        self.task_elapsed += event.duration;
        self.elapsed_micros += (event.duration * 1e6).round() as u64;
        self.query_cost += event.query_charge;
        self.latency_cost += event.latency_charge;
        self.charged_cost = self.query_cost + self.latency_cost;
        match event.action {
            Action::Stop => {
                self.counts.stop += 1;
                self.terminal = true;
            }
            Action::Skip => {
                self.counts.skip += 1;
                self.tick += 1;
            }
            Action::Fire => {
                self.counts.fire += 1;
                self.answers.push(Answer {
                    job: self.job,
                    prediction: usize::from(self.posterior >= 0.5),
                    posterior: self.posterior,
                    tick: self.tick,
                    reads: self.reads_in_job,
                });
                self.job += 1;
                self.tick += 2;
                self.posterior = 0.5;
                self.reads_in_job = 0;
            }
            Action::Read => {
                self.counts.read += 1;
                if event.error.is_some() {
                    if event.observation.is_some()
                        || event.payload_sha256.is_some()
                        || event.payload_bytes != 0
                    {
                        return Err("failed READ cannot have a completed output".into());
                    }
                    self.counts.failed_read_attempts += 1;
                    self.terminal = true;
                } else {
                    let o = event
                        .observation
                        .filter(|v| *v < 2)
                        .ok_or("READ missing observation")?;
                    if event.payload_sha256.as_ref()
                        != Some(&public.packet_sha256[self.job][self.tick])
                        || event.payload_bytes > 32768
                    {
                        return Err("READ output identity".into());
                    }
                    let r = public.reliability[self.job][self.tick];
                    let negative = r * confusion[0][o] + (1.0 - r) * confusion[1][o];
                    let positive = r * confusion[1][o] + (1.0 - r) * confusion[0][o];
                    let mass = (1.0 - self.posterior) * negative + self.posterior * positive;
                    self.posterior = self.posterior * positive / mass;
                    self.tick += 1;
                    self.budget -= 1;
                    self.reads_in_job += 1;
                    self.counts.content_invocations += 1;
                    self.counts.packet_file_reads += 1;
                    self.counts.payload_bytes += event.payload_bytes;
                }
            }
        }
        if event.action != Action::Read
            && (event.error.is_some()
                || event.observation.is_some()
                || event.payload_sha256.is_some()
                || event.payload_bytes != 0)
        {
            return Err("non-READ cannot carry content output".into());
        }
        self.terminal |= self.job >= 2 || self.tick >= public.deadline;
        self.history.push(event);
        if !self.posterior.is_finite()
            || !(0.0..=1.0).contains(&self.posterior)
            || !self.charged_cost.is_finite()
            || !self.task_elapsed.is_finite()
        {
            return Err("task arithmetic envelope".into());
        }
        Ok(())
    }

    pub fn validate(&self, public: &Public, confusion: [[f64; 2]; 2]) -> Result<(), String> {
        if self.history.len() > 32
            || self.in_flight.is_some()
            || self.pending_observation.is_some()
            || self.recovery_ticks_remaining != 0
        {
            return Err("unacknowledged task state".into());
        }
        let mut replay = Self::initial(public);
        for event in &self.history {
            replay.apply(public, confusion, event.clone())?;
        }
        if replay != *self {
            return Err("task history/checkpoint inconsistency".into());
        }
        Ok(())
    }
}
