//! Preread task owner around the unchanged, real R9 native physics/content owner.
use crate::cell::Cell;
use crate::content;
use crate::contract::Action;
use crate::contract::Config;
use crate::contract::State;
use crate::owner;
use crate::policy::Policy;
use crate::storage;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use std::path::Path;
use std::path::PathBuf;

pub struct Setup {
    pub cell: Cell,
    pub content_model: content::Model,
    pub task: Config,
    pub policy: Policy,
    pub payloads: Vec<content::Request>,
    pub tick_micros: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct Pending {
    index: usize,
    arrival: u64,
    reliability_bits: String,
    failure_probability_bits: String,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Ledger {
    pub sequence: u64,
    pub state_before: String,
    pub state_after: String,
    pub requested: Action,
    pub actual: Action,
    pub observation: Option<char>,
    pub read_attempted: bool,
    pub read_failed: bool,
    pub payload_bytes: Option<u64>,
    pub cost_bits: String,
    pub native_committed: bool,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Checkpoint {
    schema: String,
    binding: String,
    source_digest: String,
    inner_pair: String,
    sequence: u64,
    state: State,
    paid_cost_bits: String,
    log_odds_bits: String,
    deadline: u64,
    pending: Vec<Pending>,
    ledger: Vec<Ledger>,
}

#[derive(Debug, Serialize)]
pub struct Receipt {
    pub sequence: u64,
    pub task_after: String,
    pub state_key_before: String,
    pub state: State,
    pub posterior: f64,
    pub requested: Action,
    pub actual: Action,
    pub read_attempted: bool,
    pub observation: Option<char>,
    pub read_error: Option<String>,
    pub cost: f64,
    pub ledger: Ledger,
    pub inner: Option<owner::Receipt>,
    pub production_activation: bool,
}

pub struct TaskOwner {
    pub state: State,
    pub task: Config,
    pub acknowledged: String,
    inner: owner::Owner,
    inner_pair: String,
    policy: Policy,
    payloads: Vec<content::Request>,
    tick_micros: u64,
    binding: String,
    sequence: u64,
    ledger: Vec<Ledger>,
    root: PathBuf,
    poisoned: bool,
}

fn bits(value: f64) -> String {
    format!("{:016x}", value.to_bits())
}

fn pending(task: &Config, state: &State) -> Vec<Pending> {
    task.packets
        .iter()
        .enumerate()
        .skip(state.next_packet)
        .map(|(index, packet)| Pending {
            index,
            arrival: packet.arrival,
            reliability_bits: bits(packet.reliability),
            failure_probability_bits: bits(packet.failure_probability),
        })
        .collect()
}

impl TaskOwner {
    pub fn open(root: &Path, acknowledged: &str, setup: Setup) -> Result<Self, String> {
        setup.task.validate()?;
        setup.policy.validate()?;
        if !root.is_dir()
            || root.is_symlink()
            || !(1..=8_000_000).contains(&setup.tick_micros)
            || setup.payloads.len() != setup.task.packets.len()
        {
            return Err("task owner configuration envelope".into());
        }
        for request in &setup.payloads {
            if request.path.len() > 4096 || request.sha256.parse::<Digest32>().is_err() {
                return Err("payload descriptor envelope".into());
            }
        }
        let binding = Digest32::of_bytes(&storage::encode(&(
            env!("HEPTA_TASK_NATIVE_SOURCE_DIGEST"),
            &setup.task,
            &setup.policy,
            &setup.payloads,
            setup.tick_micros,
            setup.cell.snapshot(),
            &setup.content_model.digest,
        ))?)
        .to_string();
        let expected = acknowledged
            .parse::<Digest32>()
            .map_err(|error| error.to_string())?;
        if ["task-intent.json", "task-checkpoint.pending"]
            .iter()
            .any(|name| {
                let path = root.join(name);
                path.exists() || path.is_symlink()
            })
        {
            return Err("incomplete task intent/publication; reconciliation required".into());
        }
        let path = root.join("task-checkpoint.json");
        let (state, inner_pair, sequence, ledger) = if expected.is_zero() {
            if path.exists() || path.is_symlink() {
                return Err("task checkpoint requires external acknowledgement".into());
            }
            (
                setup.task.initial(),
                Digest32::ZERO.to_string(),
                0,
                Vec::new(),
            )
        } else {
            let bytes = storage::read(&path, /*limit*/ 262_144)?;
            if Digest32::of_bytes(&bytes) != expected {
                return Err("task acknowledgement mismatch".into());
            }
            let mut checkpoint: Checkpoint =
                serde_json::from_slice(&bytes).map_err(|error| error.to_string())?;
            checkpoint.state.paid_cost = f64::from_bits(
                u64::from_str_radix(&checkpoint.paid_cost_bits, /*radix*/ 16)
                    .map_err(|error| error.to_string())?,
            );
            checkpoint.state.validate(&setup.task)?;
            if checkpoint.schema != "hcsn.preread-native-task.v1"
                || checkpoint.source_digest != env!("HEPTA_TASK_NATIVE_SOURCE_DIGEST")
                || checkpoint.binding != binding
                || checkpoint.deadline != setup.task.deadline
                || checkpoint.log_odds_bits != bits(setup.task.log_odds(&checkpoint.state))
                || checkpoint.pending != pending(&setup.task, &checkpoint.state)
                || checkpoint.sequence != checkpoint.ledger.len() as u64
                || checkpoint.sequence > setup.task.deadline + 1
            {
                return Err("task identity/visible metadata mismatch".into());
            }
            let mut replay = setup.task.initial();
            for (index, entry) in checkpoint.ledger.iter().enumerate() {
                let (next, cost, actual) =
                    setup
                        .task
                        .successor(&replay, entry.requested, entry.observation)?;
                if entry.sequence != index as u64 + 1
                    || entry.state_before != replay.key()
                    || entry.state_after != next.key()
                    || entry.actual != actual
                    || entry.cost_bits != bits(cost)
                    || entry.read_attempted != (actual == Action::Read)
                    || entry.read_failed != (entry.observation == Some('x'))
                    || entry.native_committed != (actual != Action::Stop)
                {
                    return Err("task ledger replay mismatch".into());
                }
                replay = next;
            }
            if replay != checkpoint.state {
                return Err("task state/replayed ledger mismatch".into());
            }
            (
                checkpoint.state,
                checkpoint.inner_pair,
                checkpoint.sequence,
                checkpoint.ledger,
            )
        };
        let inner = owner::Owner::open(root, setup.cell, &inner_pair, Some(setup.content_model))?;
        if inner.cell.sequence != state.clock {
            return Err("task clock/native frontier mismatch".into());
        }
        Ok(Self {
            state,
            task: setup.task,
            acknowledged: acknowledged.to_owned(),
            inner,
            inner_pair,
            policy: setup.policy,
            payloads: setup.payloads,
            tick_micros: setup.tick_micros,
            binding,
            sequence,
            ledger,
            root: root.to_path_buf(),
            poisoned: false,
        })
    }

    pub fn decision(&self) -> Result<Action, String> {
        if self.poisoned {
            return Err("task owner is poisoned".into());
        }
        self.policy.decision(&self.task, &self.state)
    }

    pub fn step(&mut self, acknowledged: &str, forced: Option<Action>) -> Result<Receipt, String> {
        if self.poisoned || acknowledged != self.acknowledged || self.state.terminated {
            return Err("task frontier/poisoned/terminated".into());
        }
        let requested = match forced {
            Some(action) => action,
            None => self.decision()?,
        };
        let actual = if self.task.legal(&self.state)[requested.index()] {
            requested
        } else {
            Action::Stop
        };
        let state_before = self.state.key();
        let intent = storage::encode(&(
            self.sequence + 1,
            acknowledged,
            &state_before,
            requested,
            actual,
        ))?;
        self.poisoned = true;
        storage::create(&self.root.join("task-intent.json"), &intent)?;
        // The complete legality/selection decision and durable intent precede this first payload access.
        let mut observation = None;
        let mut read_error = None;
        let inner_receipt = if actual == Action::Stop {
            None
        } else {
            let read = if actual == Action::Read {
                Some(self.payloads[self.state.next_packet].clone())
            } else {
                None
            };
            let driver = 2.0 * self.task.posterior(&self.state) - 1.0;
            let horizon = (self.task.deadline - self.state.clock).max(1) * self.tick_micros;
            let request = owner::Request {
                sequence: self.inner.cell.sequence + 1,
                pair_before: self.inner_pair.clone(),
                driver,
                duration_micros: self.tick_micros,
                horizon_micros: horizon,
                reset: false,
                content: read,
            };
            let receipt = match self.inner.step(request) {
                Ok(receipt) => receipt,
                Err(error) if actual == Action::Read => {
                    // Decoder failures happen before the inner commit. Charge the same time/budget
                    // with one content-free native commit. A native failure poisons inner and this
                    // fallback fails closed; the original read is never retried.
                    read_error = Some(error);
                    observation = Some('x');
                    self.inner.step(owner::Request {
                        sequence: self.inner.cell.sequence + 1,
                        pair_before: self.inner_pair.clone(),
                        driver,
                        duration_micros: self.tick_micros,
                        horizon_micros: horizon,
                        reset: false,
                        content: None,
                    })?
                }
                Err(error) => return Err(error),
            };
            if actual == Action::Read && observation.is_none() {
                let output = receipt
                    .content
                    .as_ref()
                    .and_then(|state| state.last.as_ref())
                    .ok_or("missing decoded content")?;
                observation = Some(if output.observation == 1 { '1' } else { '0' });
            }
            Some(receipt)
        };
        let (state, cost, checked_actual) =
            self.task.successor(&self.state, requested, observation)?;
        if checked_actual != actual {
            return Err("task guard changed during execution".into());
        }
        let ledger = Ledger {
            sequence: self.sequence + 1,
            state_before: state_before.clone(),
            state_after: state.key(),
            requested,
            actual,
            observation,
            read_attempted: actual == Action::Read,
            read_failed: observation == Some('x'),
            payload_bytes: if actual == Action::Read && read_error.is_none() {
                inner_receipt
                    .as_ref()
                    .and_then(|r| r.content.as_ref())
                    .and_then(|c| c.last.as_ref())
                    .map(|c| c.payload_bytes)
            } else {
                None
            },
            cost_bits: bits(cost),
            native_committed: actual != Action::Stop,
        };
        let inner_pair = inner_receipt
            .as_ref()
            .map_or_else(|| self.inner_pair.clone(), |r| r.pair_after.clone());
        let mut entries = self.ledger.clone();
        entries.push(ledger.clone());
        let checkpoint = Checkpoint {
            schema: "hcsn.preread-native-task.v1".into(),
            binding: self.binding.clone(),
            source_digest: env!("HEPTA_TASK_NATIVE_SOURCE_DIGEST").into(),
            inner_pair: inner_pair.clone(),
            sequence: self.sequence + 1,
            paid_cost_bits: bits(state.paid_cost),
            log_odds_bits: bits(self.task.log_odds(&state)),
            deadline: self.task.deadline,
            pending: pending(&self.task, &state),
            state: state.clone(),
            ledger: entries.clone(),
        };
        let acknowledged = storage::publish(&self.root, &storage::encode(&checkpoint)?)?;
        storage::finish_intent(&self.root)?;
        self.state = state;
        self.inner_pair = inner_pair;
        self.acknowledged = acknowledged;
        self.sequence += 1;
        self.ledger = entries;
        self.poisoned = false;
        Ok(Receipt {
            sequence: self.sequence,
            task_after: self.acknowledged.clone(),
            state_key_before: state_before,
            state: self.state.clone(),
            posterior: self.task.posterior(&self.state),
            requested,
            actual,
            read_attempted: actual == Action::Read,
            observation,
            read_error,
            cost,
            ledger,
            inner: inner_receipt,
            production_activation: false,
        })
    }
}
