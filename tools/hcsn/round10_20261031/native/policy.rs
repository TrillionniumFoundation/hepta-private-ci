//! Policy inputs are public task state only. Payload descriptors never enter here.
use crate::contract::Action;
use crate::contract::Config;
use crate::contract::State;
use serde::Deserialize;
use serde::Serialize;
use std::collections::BTreeMap;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Policy {
    QTable { entries: BTreeMap<String, [f64; 3]> },
    FixedThreshold { confidence: f64 },
    OneRead,
}

impl Policy {
    pub fn validate(&self) -> Result<(), String> {
        match self {
            Self::QTable { entries } => {
                if entries.len() > 100_000
                    || entries.iter().any(|(key, row)| key.len() > 160 || row.iter().any(|v| !v.is_finite()))
                {
                    return Err("Q table envelope".into());
                }
            }
            Self::FixedThreshold { confidence } => {
                if !(*confidence >= 0.5 && *confidence <= 1.0) {
                    return Err("confidence threshold envelope".into());
                }
            }
            Self::OneRead => (),
        }
        Ok(())
    }

    pub fn decision(&self, task: &Config, state: &State) -> Result<Action, String> {
        state.validate(task)?;
        let legal = task.legal(state);
        if !legal[Action::Stop.index()] {
            return Err("terminal task".into());
        }
        match self {
            Self::QTable { entries } => {
                let key = state.key();
                let row = entries.get(&key).ok_or_else(|| format!("Q table lacks visible state {key}"))?;
                let best = [Action::Read, Action::Wait, Action::Stop].iter()
                    .filter(|action| legal[action.index()])
                    .map(|action| row[action.index()])
                    .fold(f64::NEG_INFINITY, f64::max);
                [Action::Stop, Action::Wait, Action::Read].into_iter()
                    .find(|action| legal[action.index()] && row[action.index()] >= best - 1e-12)
                    .ok_or_else(|| "Q table has no legal action".into())
            }
            Self::FixedThreshold { confidence } => {
                let probability = task.posterior(state);
                if probability.max(1.0 - probability) >= *confidence {
                    Ok(Action::Stop)
                } else if legal[Action::Read.index()] {
                    Ok(Action::Read)
                } else if legal[Action::Wait.index()]
                    && state.budget_left > 0
                    && task.packets.get(state.next_packet)
                        .is_some_and(|packet| state.recovery_until.max(packet.arrival) < task.deadline)
                {
                    Ok(Action::Wait)
                } else {
                    Ok(Action::Stop)
                }
            }
            Self::OneRead => {
                let Some(packet) = task.packets.get(state.next_packet) else {
                    return Ok(Action::Stop);
                };
                let read_at = state.clock.max(state.recovery_until).max(packet.arrival);
                if state.budget_left == 0 || read_at >= task.deadline {
                    return Ok(Action::Stop);
                }
                let p = task.posterior(state);
                let q = packet.reliability;
                let current = p.max(1.0 - p);
                let success_quality = (p * q).max((1.0 - p) * (1.0 - q))
                    + (p * (1.0 - q)).max((1.0 - p) * q);
                let failure = packet.failure_probability;
                let expected = (1.0 - failure) * success_quality + failure * current
                    - task.read_cost
                    - failure * task.failure_cost
                    - (read_at - state.clock) as f64 * task.latency_cost;
                if expected <= current {
                    Ok(Action::Stop)
                } else if legal[Action::Read.index()] {
                    Ok(Action::Read)
                } else {
                    Ok(Action::Wait)
                }
            }
        }
    }
}
