//! Task-scoped, immutable cost observations; persistence remains with the Cell owner.
//!
//! Exclusive entries describe disjoint charges under one frozen metering/source
//! contract. Inclusive call envelopes are retained separately, never added again.
//! These bindings do not authenticate meters, prove coverage, or grant authority.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;

use serde::Deserialize;
use serde::Serialize;

const MAX_ENTRIES: usize = 4_096;
const MAX_ENVELOPE_MEMBERS: usize = 256;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CellTaskCostIdentityV2 {
    pub task_digest: [u8; 32],
    /// Pins the implementation, inputs and metering/allocation convention.
    pub source_digest: [u8; 32],
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CellCostStageV2 {
    Encoder,
    Routing,
    Inference,
    Training,
    Planning,
    Critic,
    Codec,
    Queue,
    Persistence,
    Recovery,
    Communication,
    Evaluation,
    ModelAcquisition,
    Migration,
}

const STAGES: [CellCostStageV2; 14] = [
    CellCostStageV2::Encoder,
    CellCostStageV2::Routing,
    CellCostStageV2::Inference,
    CellCostStageV2::Training,
    CellCostStageV2::Planning,
    CellCostStageV2::Critic,
    CellCostStageV2::Codec,
    CellCostStageV2::Queue,
    CellCostStageV2::Persistence,
    CellCostStageV2::Recovery,
    CellCostStageV2::Communication,
    CellCostStageV2::Evaluation,
    CellCostStageV2::ModelAcquisition,
    CellCostStageV2::Migration,
];

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CellCostOutcomeV2 {
    Succeeded,
    Failed,
    Cancelled,
    Rejected,
    Unknown,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum CellCostAccountingV2 {
    Exclusive,
    /// Sorted, unique IDs of earlier exclusive charges. No nested envelopes.
    /// Overhead must have its own exclusive entry; an envelope is not a discount.
    InclusiveEnvelope {
        exclusive_event_ids: Vec<[u8; 32]>,
    },
}

/// None means unmeasured, including unavailable physical energy counters.
/// Some(0) requires an observed zero or a verified no-work stage. No defaults
/// convert missing observations into zero. Shared work must be allocated once.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CellCostMetricsV2 {
    /// Duration of exclusive work, or elapsed duration of an inclusive envelope.
    pub wall_micros: Option<u64>,
    pub cpu_micros: Option<u64>,
    pub energy_microjoules: Option<u64>,
    pub storage_read_bytes: Option<u64>,
    pub storage_write_bytes: Option<u64>,
    /// Integral of retained storage over time; not a sum of occupancy snapshots.
    pub storage_byte_micros: Option<u64>,
    /// Each transfer is charged once, not at both sending and receiving ends.
    pub communication_bytes: Option<u64>,
}

impl CellCostMetricsV2 {
    fn values(&self) -> [Option<u64>; 7] {
        [
            self.wall_micros,
            self.cpu_micros,
            self.energy_microjoules,
            self.storage_read_bytes,
            self.storage_write_bytes,
            self.storage_byte_micros,
            self.communication_bytes,
        ]
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CellCostEntryV2 {
    /// Stable identity for one immutable observation, including failed work.
    pub event_id: [u8; 32],
    pub identity: CellTaskCostIdentityV2,
    pub stage: CellCostStageV2,
    pub outcome: CellCostOutcomeV2,
    pub accounting: CellCostAccountingV2,
    pub metrics: CellCostMetricsV2,
}

/// Append-only value embedded in the existing owner's transaction/checkpoint.
/// Decode is not admission: validate before adopting a deserialized value.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CellTaskCostV2 {
    schema_version: u32,
    identity: CellTaskCostIdentityV2,
    entries: Vec<CellCostEntryV2>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellCostRecordV2 {
    Inserted,
    Replayed,
}

/// The observed subtotal is a lower bound while any entry or stage is unknown.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize)]
pub struct CellCostTotalV2 {
    pub known_sum: u64,
    pub unknown_entries: u32,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CellTaskCostSummaryV2 {
    /// Additive work duration; parallel work makes this unlike end-to-end latency.
    pub wall_work_micros: CellCostTotalV2,
    pub cpu_micros: CellCostTotalV2,
    pub energy_microjoules: CellCostTotalV2,
    pub storage_read_bytes: CellCostTotalV2,
    pub storage_write_bytes: CellCostTotalV2,
    pub storage_byte_micros: CellCostTotalV2,
    pub communication_bytes: CellCostTotalV2,
    pub missing_stages: Vec<CellCostStageV2>,
    pub exclusive_entries: usize,
    pub inclusive_envelopes: usize,
    /// Failed, cancelled and rejected exclusive observations are all charged.
    pub unsuccessful_entries: usize,
    pub unknown_outcome_entries: usize,
}

impl CellTaskCostSummaryV2 {
    /// Complete only relative to the recorded stage coverage and meter claims.
    /// An envelope never fills an unknown exclusive measurement.
    pub fn complete_metrics(&self) -> Option<CellCostMetricsV2> {
        let totals = [
            self.wall_work_micros,
            self.cpu_micros,
            self.energy_microjoules,
            self.storage_read_bytes,
            self.storage_write_bytes,
            self.storage_byte_micros,
            self.communication_bytes,
        ];
        if !self.missing_stages.is_empty() || totals.iter().any(|total| total.unknown_entries != 0)
        {
            return None;
        }
        let [
            wall_micros,
            cpu_micros,
            energy_microjoules,
            storage_read_bytes,
            storage_write_bytes,
            storage_byte_micros,
            communication_bytes,
        ] = totals.map(|total| Some(total.known_sum));
        Some(CellCostMetricsV2 {
            wall_micros,
            cpu_micros,
            energy_microjoules,
            storage_read_bytes,
            storage_write_bytes,
            storage_byte_micros,
            communication_bytes,
        })
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellTaskCostErrorV2 {
    InvalidIdentity,
    InvalidVersion,
    SourceMismatch,
    EventConflict,
    DuplicateEvent,
    CapacityExceeded,
    InvalidEnvelope,
    ArithmeticOverflow,
}

impl fmt::Display for CellTaskCostErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for CellTaskCostErrorV2 {}

impl CellTaskCostV2 {
    pub fn new(identity: CellTaskCostIdentityV2) -> Result<Self, CellTaskCostErrorV2> {
        let value = Self {
            schema_version: 2,
            identity,
            entries: Vec::new(),
        };
        value.validate()?;
        Ok(value)
    }

    pub fn identity(&self) -> CellTaskCostIdentityV2 {
        self.identity
    }

    pub fn entries(&self) -> &[CellCostEntryV2] {
        &self.entries
    }

    pub fn validate(&self) -> Result<(), CellTaskCostErrorV2> {
        self.validated_totals().map(|_| ())
    }

    /// Replays do not charge twice, including at capacity. Conflicting reuse,
    /// overflow and invalid envelopes leave the entire value unchanged.
    pub fn record(
        &mut self,
        entry: CellCostEntryV2,
    ) -> Result<CellCostRecordV2, CellTaskCostErrorV2> {
        let mut totals = self.validated_totals()?;
        if let Some(existing) = self
            .entries
            .iter()
            .find(|old| old.event_id == entry.event_id)
        {
            return if existing == &entry {
                Ok(CellCostRecordV2::Replayed)
            } else {
                Err(CellTaskCostErrorV2::EventConflict)
            };
        }
        if self.entries.len() == MAX_ENTRIES {
            return Err(CellTaskCostErrorV2::CapacityExceeded);
        }
        let earlier = self.entries.iter().map(|old| (old.event_id, old)).collect();
        validate_entry(self.identity, &entry, &earlier)?;
        if matches!(entry.accounting, CellCostAccountingV2::Exclusive) {
            add_metrics(&mut totals, entry.metrics)?;
        }
        self.entries.push(entry);
        Ok(CellCostRecordV2::Inserted)
    }

    pub fn summary(&self) -> Result<CellTaskCostSummaryV2, CellTaskCostErrorV2> {
        let [
            wall_work_micros,
            cpu_micros,
            energy_microjoules,
            storage_read_bytes,
            storage_write_bytes,
            storage_byte_micros,
            communication_bytes,
        ] = self.validated_totals()?;
        let mut stages = BTreeSet::new();
        let mut exclusive_entries = 0;
        let mut unsuccessful_entries = 0;
        let mut unknown_outcome_entries = 0;
        for entry in &self.entries {
            if !matches!(entry.accounting, CellCostAccountingV2::Exclusive) {
                continue;
            }
            stages.insert(entry.stage);
            exclusive_entries += 1;
            match entry.outcome {
                CellCostOutcomeV2::Succeeded => {}
                CellCostOutcomeV2::Failed
                | CellCostOutcomeV2::Cancelled
                | CellCostOutcomeV2::Rejected => unsuccessful_entries += 1,
                CellCostOutcomeV2::Unknown => unknown_outcome_entries += 1,
            }
        }
        Ok(CellTaskCostSummaryV2 {
            wall_work_micros,
            cpu_micros,
            energy_microjoules,
            storage_read_bytes,
            storage_write_bytes,
            storage_byte_micros,
            communication_bytes,
            missing_stages: STAGES
                .into_iter()
                .filter(|stage| !stages.contains(stage))
                .collect(),
            exclusive_entries,
            inclusive_envelopes: self.entries.len() - exclusive_entries,
            unsuccessful_entries,
            unknown_outcome_entries,
        })
    }

    fn validated_totals(&self) -> Result<[CellCostTotalV2; 7], CellTaskCostErrorV2> {
        if self.schema_version != 2 {
            return Err(CellTaskCostErrorV2::InvalidVersion);
        }
        if self.identity.task_digest == [0; 32] || self.identity.source_digest == [0; 32] {
            return Err(CellTaskCostErrorV2::InvalidIdentity);
        }
        if self.entries.len() > MAX_ENTRIES {
            return Err(CellTaskCostErrorV2::CapacityExceeded);
        }
        let mut earlier = BTreeMap::new();
        let mut totals = [CellCostTotalV2::default(); 7];
        for entry in &self.entries {
            if earlier.contains_key(&entry.event_id) {
                return Err(CellTaskCostErrorV2::DuplicateEvent);
            }
            validate_entry(self.identity, entry, &earlier)?;
            if matches!(entry.accounting, CellCostAccountingV2::Exclusive) {
                add_metrics(&mut totals, entry.metrics)?;
            }
            earlier.insert(entry.event_id, entry);
        }
        Ok(totals)
    }
}

fn add_metrics(
    totals: &mut [CellCostTotalV2; 7],
    metrics: CellCostMetricsV2,
) -> Result<(), CellTaskCostErrorV2> {
    for (total, value) in totals.iter_mut().zip(metrics.values()) {
        if let Some(value) = value {
            total.known_sum = total
                .known_sum
                .checked_add(value)
                .ok_or(CellTaskCostErrorV2::ArithmeticOverflow)?;
        } else {
            total.unknown_entries = total
                .unknown_entries
                .checked_add(1)
                .ok_or(CellTaskCostErrorV2::ArithmeticOverflow)?;
        }
    }
    Ok(())
}

fn validate_entry(
    identity: CellTaskCostIdentityV2,
    entry: &CellCostEntryV2,
    earlier: &BTreeMap<[u8; 32], &CellCostEntryV2>,
) -> Result<(), CellTaskCostErrorV2> {
    if entry.event_id == [0; 32] {
        return Err(CellTaskCostErrorV2::InvalidIdentity);
    }
    if entry.identity != identity {
        return Err(CellTaskCostErrorV2::SourceMismatch);
    }
    if let CellCostAccountingV2::InclusiveEnvelope {
        exclusive_event_ids,
    } = &entry.accounting
    {
        if exclusive_event_ids.is_empty()
            || exclusive_event_ids.len() > MAX_ENVELOPE_MEMBERS
            || exclusive_event_ids.windows(2).any(|ids| ids[0] >= ids[1])
        {
            return Err(CellTaskCostErrorV2::InvalidEnvelope);
        }
        let mut parts = [CellCostTotalV2::default(); 7];
        for event_id in exclusive_event_ids {
            let child = earlier
                .get(event_id)
                .ok_or(CellTaskCostErrorV2::InvalidEnvelope)?;
            if !matches!(child.accounting, CellCostAccountingV2::Exclusive) {
                return Err(CellTaskCostErrorV2::InvalidEnvelope);
            }
            // Parallel work may exceed the envelope's elapsed time in aggregate.
            if let (Some(outer), Some(inner)) =
                (entry.metrics.wall_micros, child.metrics.wall_micros)
                && inner > outer
            {
                return Err(CellTaskCostErrorV2::InvalidEnvelope);
            }
            add_metrics(&mut parts, child.metrics)?;
        }
        // Non-time resources are additive. Unknown leaves stay unknown; known
        // residuals must be explicit overhead entries, never silently discarded.
        for (part, outer) in parts.into_iter().zip(entry.metrics.values()).skip(1) {
            if let Some(outer) = outer
                && (part.known_sum > outer
                    || (part.unknown_entries == 0 && part.known_sum != outer))
            {
                return Err(CellTaskCostErrorV2::InvalidEnvelope);
            }
        }
    }
    Ok(())
}

#[cfg(test)]
#[path = "cell_task_cost_tests.rs"]
mod tests;
