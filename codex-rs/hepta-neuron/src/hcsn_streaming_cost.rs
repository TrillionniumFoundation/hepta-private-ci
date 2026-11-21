//! Validate the concrete streaming backend's complete, settled cost journal.

use codex_hepta_types::Digest32;
use serde::Deserialize;

use crate::HcsnRecoveryErrorV2;
use crate::hcsn_streaming::Controller;

#[derive(Clone, Debug, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
struct Budget {
    wall_seconds: f64,
    training_examples: u64,
    encoder_events: u64,
    forward_examples: u64,
    backward_examples: u64,
    development_queries: u64,
    proposals: u64,
}

#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
struct Charge {
    training_examples: u64,
    encoder_events: u64,
    forward_examples: u64,
    backward_examples: u64,
    development_queries: u64,
    proposals: u64,
}

enum Record {
    Reserve(ReserveRecord),
    Settle(SettleRecord),
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum RecordKind {
    Reserve,
    Settle,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ReserveRecord {
    #[serde(rename = "kind")]
    _kind: RecordKind,
    identity: String,
    budget: Budget,
    previous: String,
    operation: usize,
    name: String,
    charge: Charge,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SettleRecord {
    #[serde(rename = "kind")]
    _kind: RecordKind,
    identity: String,
    budget: Budget,
    previous: String,
    operation: usize,
    name: String,
    status: String,
    error: Option<String>,
    cumulative_wall_seconds: f64,
}

impl Record {
    fn decode(canonical: &str) -> Result<Self, serde_json::Error> {
        #[derive(Deserialize)]
        struct Header {
            kind: RecordKind,
        }

        // Internally tagged enums buffer through Serde's Content. With
        // serde_json/arbitrary_precision, buffered JSON floats become private
        // Number maps that Content cannot deserialize as f64. Dispatch only on
        // the tag, then decode the same original bytes into the strict schema.
        // This also preserves duplicate/unknown-field and numeric-type rejection.
        match serde_json::from_str::<Header>(canonical)?.kind {
            RecordKind::Reserve => serde_json::from_str(canonical).map(Self::Reserve),
            RecordKind::Settle => serde_json::from_str(canonical).map(Self::Settle),
        }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Item {
    canonical: String,
    hash: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Journal {
    identity: String,
    records: Vec<Item>,
}

/// Includes unsuccessful and discarded work; never subtracts recovery retries.
#[derive(Clone, Debug, PartialEq)]
pub struct HcsnStreamingCostV1 {
    pub elapsed_micros: u64,
    pub failed_operations: u64,
    pub charged_training_examples: u64,
    pub charged_encoder_events: u64,
    pub charged_proposals: u64,
    pub journal_tail: Digest32,
}

pub(crate) fn validate_cost(
    bytes: &[u8],
    identity: Digest32,
    controller: &Controller,
    batch: u64,
) -> Result<HcsnStreamingCostV1, HcsnRecoveryErrorV2> {
    let invalid = HcsnRecoveryErrorV2::Backend;
    let journal: Journal = serde_json::from_slice(bytes).map_err(|_| invalid)?;
    if journal.identity != identity.to_string() {
        return Err(invalid);
    }
    let mut tail = Digest32::ZERO;
    let mut budget = None;
    let mut pending: Option<(usize, String, Charge)> = None;
    let (mut observations, mut examples, mut solves) = (0_u64, 0_u64, 0_u64);
    let mut wall = 0.0;
    let mut cost = HcsnStreamingCostV1 {
        elapsed_micros: 0,
        failed_operations: 0,
        charged_training_examples: 0,
        charged_encoder_events: 0,
        charged_proposals: 0,
        journal_tail: tail,
    };
    for (index, item) in journal.records.iter().enumerate() {
        if Digest32::of_bytes(item.canonical.as_bytes()).to_string() != item.hash {
            return Err(invalid);
        }
        let record = Record::decode(&item.canonical).map_err(|_| invalid)?;
        let (request, limits, previous) = match &record {
            Record::Reserve(ReserveRecord {
                identity,
                budget,
                previous,
                ..
            })
            | Record::Settle(SettleRecord {
                identity,
                budget,
                previous,
                ..
            }) => (identity, budget, previous),
        };
        if request != &journal.identity
            || previous != &tail.to_string()
            || !limits.wall_seconds.is_finite()
            || limits.wall_seconds <= 0.0
            || [
                limits.training_examples,
                limits.encoder_events,
                limits.forward_examples,
                limits.backward_examples,
                limits.development_queries,
                limits.proposals,
            ]
            .contains(&0)
            || budget.as_ref().is_some_and(|value| value != limits)
        {
            return Err(invalid);
        }
        budget = Some(limits.clone());
        match record {
            Record::Reserve(ReserveRecord {
                operation,
                name,
                charge,
                ..
            }) => {
                let expected = match name.as_str() {
                    "stream_observation" if [0, batch].contains(&charge.training_examples) => {
                        Charge {
                            training_examples: charge.training_examples,
                            encoder_events: batch,
                            forward_examples: batch,
                            ..Charge::default()
                        }
                    }
                    "closed_form_readout" => Charge {
                        proposals: 1,
                        ..Charge::default()
                    },
                    "checkpoint" => Charge::default(),
                    _ => return Err(invalid),
                };
                if pending.is_some() || operation != index || charge != expected {
                    return Err(invalid);
                }
                cost.charged_training_examples = cost
                    .charged_training_examples
                    .checked_add(charge.training_examples)
                    .ok_or(invalid)?;
                cost.charged_encoder_events = cost
                    .charged_encoder_events
                    .checked_add(charge.encoder_events)
                    .ok_or(invalid)?;
                cost.charged_proposals = cost
                    .charged_proposals
                    .checked_add(charge.proposals)
                    .ok_or(invalid)?;
                pending = Some((operation, name, charge));
            }
            Record::Settle(SettleRecord {
                operation,
                name,
                status,
                error,
                cumulative_wall_seconds,
                ..
            }) => {
                let (expected_operation, expected_name, charge) = pending.take().ok_or(invalid)?;
                if operation != expected_operation
                    || name != expected_name
                    || !cumulative_wall_seconds.is_finite()
                    || cumulative_wall_seconds < wall
                {
                    return Err(invalid);
                }
                match status.as_str() {
                    "completed" if error.is_none() => match name.as_str() {
                        "stream_observation" => {
                            observations = observations.checked_add(1).ok_or(invalid)?;
                            examples = examples
                                .checked_add(charge.training_examples)
                                .ok_or(invalid)?;
                        }
                        "closed_form_readout" => solves = solves.checked_add(1).ok_or(invalid)?,
                        "checkpoint" => (),
                        _ => return Err(invalid),
                    },
                    "failed" if error.is_some() => cost.failed_operations += 1,
                    _ => return Err(invalid),
                }
                wall = cumulative_wall_seconds;
            }
        }
        tail = item.hash.parse().map_err(|_| invalid)?;
    }
    if pending.is_some()
        || observations
            != controller
                .observations
                .checked_add(controller.discarded_observations)
                .ok_or(invalid)?
        || examples
            != controller
                .examples
                .checked_add(controller.discarded_examples)
                .ok_or(invalid)?
        || solves
            != controller
                .solves
                .checked_add(controller.discarded_solves)
                .ok_or(invalid)?
        || wall * 1_000_000.0 >= u64::MAX as f64
    {
        return Err(invalid);
    }
    cost.elapsed_micros = (wall * 1_000_000.0).ceil() as u64;
    cost.journal_tail = tail;
    Ok(cost)
}

#[cfg(test)]
#[path = "hcsn_streaming_cost_tests.rs"]
mod tests;
