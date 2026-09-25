//! A deliberately narrow local Cell baseline trained from the actual ledger.
//!
//! This constant-state terminal-value profile is not Laya, a general Bellman
//! solver, causal policy improvement, or deployment selection. Targets and
//! action labels are derived from authenticated current owner events, never
//! supplied by the trainer under arbitrary nonzero evidence digests.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;

use codex_hepta_learning_ledger::AuthenticatedOutcomeTerminality;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::ProductionLedgerError;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::StrictLearnedOperatorError;
use crate::TabularOperatorArtifactV1;
use crate::TabularOperatorPlanV1;
use crate::TabularOperatorSampleV1;
use crate::learned_strict::fit_tabular_operator_strict_v2;

const MAX_SOURCE_RECORDS: usize = 4096;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TerminalCellProfileV1 {
    pub artifact_id: StableId,
    pub producer_id: StableId,
    pub generation: Generation,
    pub sensor_id: StableId,
    pub objective_digest: Digest32,
    pub run_snapshot_digest: Digest32,
    pub unit_profile_digest: Digest32,
    pub action_ids: Vec<StableId>,
    pub minimum_samples_per_action: usize,
}

#[derive(Clone, Debug)]
pub struct FrozenTerminalCellV1 {
    plan: TabularOperatorPlanV1,
    dataset: DatasetSnapshotReceiptV3,
    profile: TerminalCellProfileV1,
    trust_distribution_digest: Digest32,
}

impl FrozenTerminalCellV1 {
    pub fn dataset(&self) -> &DatasetSnapshotReceiptV3 {
        &self.dataset
    }
    pub fn sample_count(&self) -> usize {
        self.plan.samples.len()
    }
}

#[derive(Debug)]
pub enum TerminalCellError {
    Ledger(ProductionLedgerError),
    Unsupported(&'static str),
    Fit(StrictLearnedOperatorError),
}
impl fmt::Display for TerminalCellError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl Error for TerminalCellError {}
impl From<ProductionLedgerError> for TerminalCellError {
    fn from(value: ProductionLedgerError) -> Self {
        Self::Ledger(value)
    }
}

pub fn freeze_terminal_cell_from_owner_v1(
    owner: &LedgerWriter,
    dataset: &DatasetSnapshotReceiptV3,
    profile: TerminalCellProfileV1,
    now: u64,
) -> Result<FrozenTerminalCellV1, TerminalCellError> {
    let plan = materialize_terminal_cell_plan(owner, dataset, profile.clone(), now)?;
    Ok(FrozenTerminalCellV1 {
        plan,
        dataset: dataset.clone(),
        trust_distribution_digest: owner.trust_distribution_digest(),
        profile,
    })
}

/// Fit only after deriving the exact same rows from the current authoritative
/// owner a second time. The opaque frozen value is deliberately not a promise
/// that a previously materialized target remains current: corrections,
/// withdrawals, owner replacement, or any in-memory content substitution must
/// be observed before fitting.
pub fn fit_terminal_cell_from_owner_v1(
    owner: &LedgerWriter,
    frozen: FrozenTerminalCellV1,
    now: u64,
) -> Result<TabularOperatorArtifactV1, TerminalCellError> {
    if owner.trust_distribution_digest() != frozen.trust_distribution_digest {
        return Err(TerminalCellError::Unsupported(
            "learning trust changed before fit",
        ));
    }
    let current = materialize_terminal_cell_plan(owner, &frozen.dataset, frozen.profile, now)?;
    require_exact_owner_materialization(&frozen.plan, &current)?;
    fit_tabular_operator_strict_v2(current).map_err(TerminalCellError::Fit)
}

fn require_exact_owner_materialization(
    frozen: &TabularOperatorPlanV1,
    current: &TabularOperatorPlanV1,
) -> Result<(), TerminalCellError> {
    if frozen != current {
        return Err(TerminalCellError::Unsupported(
            "owner materialization changed before fit",
        ));
    }
    Ok(())
}

fn materialize_terminal_cell_plan(
    owner: &LedgerWriter,
    dataset: &DatasetSnapshotReceiptV3,
    mut profile: TerminalCellProfileV1,
    now: u64,
) -> Result<TabularOperatorPlanV1, TerminalCellError> {
    owner.revalidate_dataset_snapshot(dataset, now)?;
    if dataset.snapshot.objective_digest != profile.objective_digest
        || profile.objective_digest.is_zero()
        || profile.run_snapshot_digest.is_zero()
        || profile.unit_profile_digest.is_zero()
        || profile.minimum_samples_per_action == 0
        || profile.minimum_samples_per_action > MAX_SOURCE_RECORDS
        || profile.action_ids.is_empty()
        || profile.action_ids.len() > 128
        || dataset.snapshot.source_record_digests.len() > MAX_SOURCE_RECORDS
    {
        return Err(TerminalCellError::Unsupported("profile/dataset bounds"));
    }
    profile.action_ids.sort();
    if profile.action_ids.windows(2).any(|pair| pair[0] == pair[1]) {
        return Err(TerminalCellError::Unsupported("duplicate action"));
    }
    let frozen: BTreeSet<_> = dataset
        .snapshot
        .source_record_digests
        .iter()
        .copied()
        .collect();
    let mut found = BTreeSet::new();
    let mut decisions = BTreeMap::new();
    let mut outcomes = BTreeMap::new();
    for record in owner.read_dataset_records(dataset, now)? {
        if !frozen.contains(&record.event_digest) {
            continue;
        }
        found.insert(record.event_digest);
        match &record.event {
            LedgerEvent::AuthenticatedDecisionV2(value) => {
                let mut actions = value.candidate_ids.clone();
                actions.sort();
                if value.objective_digest != profile.objective_digest
                    || value.run_snapshot_digest != profile.run_snapshot_digest
                    || actions != profile.action_ids
                {
                    return Err(TerminalCellError::Unsupported(
                        "heterogeneous state/objective/action set",
                    ));
                }
                if decisions
                    .insert(value.episode_id.clone(), value.clone())
                    .is_some()
                {
                    return Err(TerminalCellError::Unsupported("duplicate episode decision"));
                }
            }
            LedgerEvent::AuthenticatedOutcomeV2(value) => {
                if value.terminality != AuthenticatedOutcomeTerminality::Terminal
                    || value.value.is_none()
                    || value.unit_profile_digest != profile.unit_profile_digest
                    || value.finalized_at.is_none()
                {
                    return Err(TerminalCellError::Unsupported(
                        "nonterminal or different-unit target",
                    ));
                }
                if outcomes
                    .insert(
                        value.episode_id.clone(),
                        (value.clone(), record.event_digest),
                    )
                    .is_some()
                {
                    return Err(TerminalCellError::Unsupported(
                        "multiple active outcome heads",
                    ));
                }
            }
            // The frozen owner provenance may include additional causal facts.
            // They stay bound by the exact dataset but do not invent targets.
            _ => {}
        }
    }
    if found != frozen || decisions.is_empty() || decisions.len() != outcomes.len() {
        return Err(TerminalCellError::Unsupported("incomplete owner evidence"));
    }
    let mut samples = Vec::with_capacity(outcomes.len());
    for (episode, (outcome, evidence_digest)) in outcomes {
        let decision = decisions
            .get(&episode)
            .ok_or(TerminalCellError::Unsupported("orphan outcome"))?;
        samples.push(TabularOperatorSampleV1 {
            sample_id: outcome.record_id,
            sensor_id: profile.sensor_id.clone(),
            action_id: decision.selected_candidate_id.clone(),
            target: outcome
                .value
                .ok_or(TerminalCellError::Unsupported("missing target"))?,
            evidence_digest,
        });
    }
    let mut bytes = b"hepta.terminal-cell.profile.v1\0".to_vec();
    bytes.extend_from_slice(profile.run_snapshot_digest.as_array());
    bytes.extend_from_slice(profile.unit_profile_digest.as_array());
    bytes.extend_from_slice(&(profile.minimum_samples_per_action as u64).to_be_bytes());
    for id in std::iter::once(&profile.sensor_id).chain(profile.action_ids.iter()) {
        bytes.extend_from_slice(&(id.as_str().len() as u64).to_be_bytes());
        bytes.extend_from_slice(id.as_str().as_bytes());
    }
    let profile_digest = Digest32::of_bytes(&bytes);
    Ok(TabularOperatorPlanV1 {
        artifact_id: profile.artifact_id,
        producer_id: profile.producer_id,
        generation: profile.generation,
        objective_digest: profile.objective_digest,
        dataset_digest: dataset.snapshot.dataset_digest,
        sensor_core_digest: profile.run_snapshot_digest,
        training_profile_digest: profile_digest,
        minimum_samples_per_cell: profile.minimum_samples_per_action,
        sensor_ids: vec![profile.sensor_id],
        action_ids: profile.action_ids,
        samples,
    })
}

#[cfg(test)]
#[path = "owner_terminal_tests.rs"]
mod tests;
