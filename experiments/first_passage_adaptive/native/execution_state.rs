//! Bounded research-task execution state. This is not a new production owner.
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct FptParameters {
    drift: f64,
    weights: [f64; 2],
    sigma: f64,
    barrier: f64,
    reset_gap: f64,
    refractory: f64,
    interaction: f64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct FptCheckpoint {
    profile: String,
    parameters: FptParameters,
    model_digest: String,
    level: f64,
    time: f64,
    refractory_remaining: f64,
    event_count: u64,
    #[serde(rename = "seed")]
    _seed: u64,
    #[serde(rename = "random_counter")]
    _random_counter: u64,
}

pub fn validate_checkpoint(
    raw: &str,
    expected: Digest32,
    state: &ExecutionState,
) -> Result<String, String> {
    let fpt: FptCheckpoint = serde_json::from_str(raw).map_err(|error| error.to_string())?;
    let p = &fpt.parameters;
    let micros = |seconds: f64| -> Result<u64, String> {
        if !seconds.is_finite() || !(0.0..=86_400.0).contains(&seconds) {
            return Err("physical clock outside profile".into());
        }
        Ok((seconds * 1_000_000.0).round() as u64)
    };
    let parameters = [
        p.drift,
        p.weights[0],
        p.weights[1],
        p.sigma,
        p.barrier,
        p.reset_gap,
        p.refractory,
        p.interaction,
        fpt.level,
    ];
    let model = fpt
        .model_digest
        .parse::<Digest32>()
        .map_err(|error| error.to_string())?;
    if fpt.profile != "hepta-first-passage-cell-v1"
        || parameters.iter().any(|value| !value.is_finite())
        || p.sigma <= 0.0
        || p.reset_gap <= 0.0
        || p.refractory < 1e-6
        || model.is_zero()
        || micros(fpt.time)? != state.clock_us
        || micros(fpt.refractory_remaining)?
            .abs_diff(state.refractory_until_us.saturating_sub(state.clock_us))
            > 1
        || micros(p.refractory)? != state.refractory_period_us
        || fpt.event_count != state.events
        || (fpt.refractory_remaining > 0.0 && fpt.level != p.barrier + p.reset_gap)
        || Digest32::of_bytes(raw.as_bytes()) != expected
    {
        return Err("full FPT checkpoint digest/clock/phase/parameter domain mismatch".into());
    }
    Ok(fpt.model_digest)
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct ExecutionState {
    pub clock_us: u64,
    pub refractory_until_us: u64,
    pub refractory_period_us: u64,
    pub events: u64,
    pub read_units_spent: u64,
    pub read_units_budget: u64,
    pub terminal: Option<Terminal>,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
pub enum Terminal {
    Stopped,
    Cancelled,
    BudgetExhausted,
    Deadline,
    ReadFailed,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(tag = "kind", deny_unknown_fields)]
pub enum Command {
    Read {
        relative_path: String,
        query: String,
    },
    Wait,
    Stop,
    Cancel,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct EventWindow {
    pub end_us: u64,
    pub hit_times_us: Vec<u64>,
}

impl ExecutionState {
    pub fn advance(&self, window: &EventWindow, deadline_us: u64) -> Result<Self, String> {
        if self.refractory_period_us == 0
            || self.read_units_spent > self.read_units_budget
            || window.hit_times_us.len() > 128
            || window.end_us < self.clock_us
            || window.end_us > deadline_us
        {
            return Err("invalid event clock, resource state or window bounds".into());
        }
        if self.terminal.is_some()
            && (window.end_us != self.clock_us || !window.hit_times_us.is_empty())
        {
            return Err("terminal state cannot acquire later events".into());
        }
        let mut next = self.clone();
        let mut last = self.clock_us;
        for &hit in &window.hit_times_us {
            if hit < last || hit < next.refractory_until_us || hit > window.end_us {
                return Err("event order or refractory contract violated".into());
            }
            next.events = next.events.checked_add(1).ok_or("event count overflow")?;
            next.refractory_until_us = hit
                .checked_add(next.refractory_period_us)
                .ok_or("refractory clock overflow")?;
            last = hit;
        }
        next.clock_us = window.end_us;
        Ok(next)
    }

    pub fn admit(&mut self, command: &Command, deadline_us: u64) -> Result<(), String> {
        if self.terminal.is_some() {
            return Err("terminal task cannot be executed again".into());
        }
        match command {
            Command::Cancel => self.terminal = Some(Terminal::Cancelled),
            Command::Stop => self.terminal = Some(Terminal::Stopped),
            Command::Wait => {}
            Command::Read { .. } => {
                if self.clock_us >= deadline_us {
                    self.terminal = Some(Terminal::Deadline);
                } else if self.read_units_spent >= self.read_units_budget {
                    self.terminal = Some(Terminal::BudgetExhausted);
                } else if self.clock_us < self.refractory_until_us {
                    return Err("read refused during refractory holding".into());
                } else {
                    // Reserve one physical read attempt before touching its source.
                    self.read_units_spent = self
                        .read_units_spent
                        .checked_add(1)
                        .ok_or("read budget overflow")?;
                }
            }
        }
        Ok(())
    }
}
