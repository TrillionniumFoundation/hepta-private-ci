//! Causal task contract, mirrored by ../value/task.py. No private truth or payload.
use serde::Deserialize;
use serde::Serialize;

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "UPPERCASE")]
pub enum Action {
    Read,
    Wait,
    Stop,
}

impl Action {
    pub fn index(self) -> usize {
        match self {
            Self::Read => 0,
            Self::Wait => 1,
            Self::Stop => 2,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Packet {
    pub arrival: u64,
    pub reliability: f64,
    #[serde(default)]
    pub failure_probability: f64,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Config {
    pub deadline: u64,
    pub budget: u64,
    pub prior: f64,
    pub read_cost: f64,
    pub latency_cost: f64,
    pub stop_cost: f64,
    pub failure_cost: f64,
    pub invalid_cost: f64,
    pub refractory_ticks: u64,
    pub packets: Vec<Packet>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct State {
    pub clock: u64,
    pub budget_left: u64,
    pub recovery_until: u64,
    pub next_packet: usize,
    pub history: String,
    pub paid_cost: f64,
    pub terminated: bool,
    pub answer: Option<usize>,
}

impl Config {
    pub fn validate(&self) -> Result<(), String> {
        if !(self.prior > 0.0 && self.prior < 1.0)
            || self.budget > 8
            || !(1..=16).contains(&self.deadline)
            || self.refractory_ticks > 8
            || !(1..=4).contains(&self.packets.len())
            || self.packets.windows(2).any(|p| p[0].arrival > p[1].arrival)
        {
            return Err("task configuration envelope".into());
        }
        for packet in &self.packets {
            if !(packet.reliability > 0.5 && packet.reliability < 1.0)
                || !(packet.failure_probability >= 0.0 && packet.failure_probability < 1.0)
            {
                return Err("packet probability envelope".into());
            }
        }
        if [
            self.read_cost,
            self.latency_cost,
            self.stop_cost,
            self.failure_cost,
            self.invalid_cost,
        ]
        .iter()
        .any(|cost| !cost.is_finite() || *cost < 0.0 || *cost > 1e100)
        {
            return Err("task cost envelope".into());
        }
        Ok(())
    }

    pub fn initial(&self) -> State {
        State {
            clock: 0,
            budget_left: self.budget,
            recovery_until: 0,
            next_packet: 0,
            history: String::new(),
            paid_cost: 0.0,
            terminated: false,
            answer: None,
        }
    }

    pub fn log_odds(&self, state: &State) -> f64 {
        let mut odds = (self.prior / (1.0 - self.prior)).ln();
        for (bit, packet) in state.history.bytes().zip(&self.packets) {
            let increment = (packet.reliability / (1.0 - packet.reliability)).ln();
            match bit {
                b'1' => odds += increment,
                b'0' => odds -= increment,
                b'x' => (),
                _ => unreachable!("validated task history"),
            }
        }
        odds
    }

    pub fn posterior(&self, state: &State) -> f64 {
        1.0 / (1.0 + (-self.log_odds(state)).exp())
    }

    pub fn legal(&self, state: &State) -> [bool; 3] {
        if state.terminated {
            return [false; 3];
        }
        let wait = state.clock < self.deadline;
        let read = wait
            && state.budget_left > 0
            && state.clock >= state.recovery_until
            && self
                .packets
                .get(state.next_packet)
                .is_some_and(|p| p.arrival <= state.clock);
        [read, wait, true]
    }

    pub fn successor(
        &self,
        state: &State,
        requested: Action,
        observation: Option<char>,
    ) -> Result<(State, f64, Action), String> {
        state.validate(self)?;
        if state.terminated {
            return Err("terminal task".into());
        }
        let actual = if self.legal(state)[requested.index()] {
            requested
        } else {
            Action::Stop
        };
        let mut next = state.clone();
        let cost = match actual {
            Action::Stop => {
                next.terminated = true;
                next.answer = Some(usize::from(self.posterior(state) >= 0.5));
                self.stop_cost
                    + if actual != requested {
                        self.invalid_cost
                    } else {
                        0.0
                    }
            }
            Action::Wait => {
                next.clock += 1;
                self.latency_cost
            }
            Action::Read => {
                let bit = observation.ok_or("READ requires a decoded observation or failure")?;
                if !matches!(bit, '0' | '1' | 'x') {
                    return Err("invalid READ observation".into());
                }
                next.clock += 1;
                next.budget_left -= 1;
                next.recovery_until = next.clock + self.refractory_ticks;
                next.next_packet += 1;
                next.history.push(bit);
                self.read_cost + if bit == 'x' { self.failure_cost } else { 0.0 }
            }
        };
        next.paid_cost += cost;
        next.validate(self)?;
        Ok((next, cost, actual))
    }
}

impl State {
    pub fn key(&self) -> String {
        format!(
            "t={};b={};r={};i={};h={}",
            self.clock, self.budget_left, self.recovery_until, self.next_packet, self.history
        )
    }

    pub fn validate(&self, config: &Config) -> Result<(), String> {
        if self.clock > config.deadline
            || self.budget_left > config.budget
            || self.next_packet > config.packets.len()
            || self.history.len() != self.next_packet
            || self
                .history
                .bytes()
                .any(|bit| !matches!(bit, b'0' | b'1' | b'x'))
            || self.next_packet as u64 + self.budget_left != config.budget
            || self.clock < self.next_packet as u64
            || self.recovery_until > config.deadline + config.refractory_ticks
            || !self.paid_cost.is_finite()
            || self.paid_cost < 0.0
            || self.terminated != self.answer.is_some()
            || self.answer.is_some_and(|answer| answer > 1)
        {
            return Err("invalid visible task state".into());
        }
        Ok(())
    }
}
