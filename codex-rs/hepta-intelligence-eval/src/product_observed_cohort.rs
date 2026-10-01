//! Commitments to the actual released observations, not external owner heads.
//! The provider supplies snapshot membership; sealing it does not grant new
//! dataset-owner authority or establish empirical truth of supplied outcomes.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CrossFoldPlanReceiptV1;
use crate::EvaluationClaimScopeV1;
use crate::LongitudinalTimeEvidenceV1;
use crate::OpeRow;
use crate::ProductEvaluationError;
use crate::TemporalComparisonInputsV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductWindowSnapshotBindingV1 {
    pub window_id: StableId,
    pub snapshot_id: StableId,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductObservedCohortV1 {
    pub window_id: StableId,
    pub snapshot_id: StableId,
    pub first_decision_at: u64,
    pub last_decision_at: u64,
    pub first_outcome_at: u64,
    pub last_outcome_at: u64,
    pub observation_count: u64,
    /// Domain-separated commitment to actual joined inputs, not an owner head.
    pub observed_source_cut: Digest32,
}

/// Check counts before comparison sorting, fitting or commitment buffers.
pub(crate) fn preflight(inputs: &TemporalComparisonInputsV1) -> Result<(), ProductEvaluationError> {
    if inputs.snapshot_ids.is_empty()
        || inputs.future_window_ids.is_empty()
        || inputs.targets.len() > 16_384
        || inputs.training.len() > 100_000
        || inputs.assignments.len() != inputs.targets.len()
        || inputs.candidate_observations.len() != inputs.targets.len()
        || inputs.baseline_observations.len() != inputs.targets.len()
        || inputs.snapshot_ids.len() > 1024
        || inputs.future_window_ids.len() > 32
        || inputs.window_snapshots.len() > 32
    {
        return Err(ProductEvaluationError::Binding("released input resources"));
    }
    if !bounded_cells(
        inputs.targets.iter().map(|target| target.actions.len()),
        262_144,
    ) || !bounded_cells(
        inputs
            .candidate_observations
            .iter()
            .chain(&inputs.baseline_observations)
            .map(|row| row.actions.len()),
        524_288,
    ) {
        return Err(ProductEvaluationError::Binding("released input resources"));
    }
    Ok(())
}

fn bounded_cells(mut counts: impl Iterator<Item = usize>, maximum: usize) -> bool {
    counts
        .try_fold(0usize, |total, count| {
            if count > 128 {
                None
            } else {
                total.checked_add(count).filter(|total| *total <= maximum)
            }
        })
        .is_some()
}

pub(crate) fn derive(
    frozen: &CrossFoldPlanReceiptV1,
    inputs: &TemporalComparisonInputsV1,
) -> Result<Vec<ProductObservedCohortV1>, ProductEvaluationError> {
    if frozen.claim_scope == EvaluationClaimScopeV1::Qualification {
        if !inputs.window_snapshots.is_empty() || inputs.training_snapshot_id.is_some() {
            return Err(ProductEvaluationError::Binding(
                "qualification window mapping",
            ));
        }
        return Ok(Vec::new());
    }
    if !(2..=32).contains(&inputs.window_snapshots.len())
        || inputs.targets.len() > 16_384
        || inputs.candidate_observations.len() != inputs.targets.len()
        || inputs.baseline_observations.len() != inputs.targets.len()
        || inputs
            .candidate_observations
            .iter()
            .chain(&inputs.baseline_observations)
            .try_fold(0usize, |count, row| count.checked_add(row.actions.len()))
            .is_none_or(|count| count > 524_288)
    {
        return Err(ProductEvaluationError::Binding("observed cohort bounds"));
    }
    let training_snapshot = inputs
        .training_snapshot_id
        .as_ref()
        .ok_or(ProductEvaluationError::Binding("training snapshot binding"))?;
    if !inputs.snapshot_ids.contains(training_snapshot)
        || inputs.snapshot_ids.len() != inputs.window_snapshots.len() + 1
    {
        return Err(ProductEvaluationError::Binding("snapshot role coverage"));
    }
    let mut mappings = BTreeMap::new();
    let mut snapshots = BTreeSet::new();
    snapshots.insert(training_snapshot);
    for binding in &inputs.window_snapshots {
        if !inputs.future_window_ids.contains(&binding.window_id)
            || !inputs.snapshot_ids.contains(&binding.snapshot_id)
            || !snapshots.insert(&binding.snapshot_id)
            || mappings
                .insert(&binding.window_id, &binding.snapshot_id)
                .is_some()
        {
            return Err(ProductEvaluationError::Binding("window snapshot mapping"));
        }
    }
    if mappings.len() != inputs.future_window_ids.len() {
        return Err(ProductEvaluationError::Binding("future cohort coverage"));
    }
    let candidate = rows(&inputs.candidate_observations)?;
    let baseline = rows(&inputs.baseline_observations)?;
    let mut clusters = BTreeMap::new();
    for assignment in &inputs.assignments {
        if clusters
            .insert(&assignment.decision_id, &assignment.cluster_id)
            .is_some()
        {
            return Err(ProductEvaluationError::Binding(
                "duplicate observed cluster join",
            ));
        }
    }
    let mut targets: Vec<_> = inputs.targets.iter().collect();
    targets.sort_by(|left, right| left.decision_id.cmp(&right.decision_id));
    let mut groups = BTreeMap::<&StableId, (ProductObservedCohortV1, Vec<u8>)>::new();
    let mut seen = BTreeSet::new();
    for target in targets {
        let snapshot = mappings
            .get(&target.window_id)
            .ok_or(ProductEvaluationError::Binding("actual observation window"))?;
        if !seen.insert(&target.decision_id) {
            return Err(ProductEvaluationError::Binding("observation join"));
        }
        let left = candidate
            .get(&target.decision_id)
            .ok_or(ProductEvaluationError::Binding(
                "candidate observation join",
            ))?;
        let right = baseline
            .get(&target.decision_id)
            .ok_or(ProductEvaluationError::Binding("baseline observation join"))?;
        let (cohort, bytes) = groups.entry(&target.window_id).or_insert_with(|| {
            let mut bytes = b"hepta.intelligence-eval.actual-released-cohort.v1\0".to_vec();
            push_id(&mut bytes, &target.window_id);
            push_id(&mut bytes, snapshot);
            (
                ProductObservedCohortV1 {
                    window_id: target.window_id.clone(),
                    snapshot_id: (*snapshot).clone(),
                    first_decision_at: u64::MAX,
                    last_decision_at: 0,
                    first_outcome_at: u64::MAX,
                    last_outcome_at: 0,
                    observation_count: 0,
                    observed_source_cut: Digest32::ZERO,
                },
                bytes,
            )
        });
        cohort.first_decision_at = cohort.first_decision_at.min(target.decision_at);
        cohort.last_decision_at = cohort.last_decision_at.max(target.decision_at);
        cohort.first_outcome_at = cohort
            .first_outcome_at
            .min(left.outcome_observed_at)
            .min(right.outcome_observed_at);
        cohort.last_outcome_at = cohort
            .last_outcome_at
            .max(left.outcome_observed_at)
            .max(right.outcome_observed_at);
        cohort.observation_count += 1;
        for id in [
            &target.decision_id,
            &target.principal_lineage,
            &target.episode_lineage,
        ] {
            push_id(bytes, id);
        }
        push_id(
            bytes,
            clusters
                .get(&target.decision_id)
                .ok_or(ProductEvaluationError::Binding("observed cluster join"))?,
        );
        bytes.extend_from_slice(&target.decision_at.to_be_bytes());
        for row in [*left, *right] {
            if row.finalized_outcome.is_none() || row.outcome_observed_at < target.decision_at {
                return Err(ProductEvaluationError::Binding(
                    "observed finalized outcome",
                ));
            }
            push_id(bytes, &row.chosen_action);
            bytes.extend_from_slice(&row.outcome_observed_at.to_be_bytes());
            bytes.extend_from_slice(
                &row.finalized_outcome
                    .ok_or(ProductEvaluationError::Binding("outcome"))?
                    .raw()
                    .to_be_bytes(),
            );
            bytes.extend_from_slice(row.outcome_evidence.as_array());
            bytes.push(u8::from(row.complete_candidates));
            bytes.extend_from_slice(&(row.actions.len() as u64).to_be_bytes());
            let mut actions: Vec<_> = row.actions.iter().collect();
            actions.sort_by(|left, right| left.action_id.cmp(&right.action_id));
            for action in actions {
                push_id(bytes, &action.action_id);
                bytes.extend_from_slice(&action.behavior_probability.raw().to_be_bytes());
                bytes.extend_from_slice(&action.evaluation_probability.raw().to_be_bytes());
            }
        }
    }
    if groups.len() != mappings.len() {
        return Err(ProductEvaluationError::Binding(
            "empty claimed future cohort",
        ));
    }
    Ok(groups
        .into_values()
        .map(|(mut cohort, bytes)| {
            cohort.observed_source_cut = Digest32::of_bytes(&bytes);
            cohort
        })
        .collect())
}

fn rows(rows: &[OpeRow]) -> Result<BTreeMap<&StableId, &OpeRow>, ProductEvaluationError> {
    let mut result = BTreeMap::new();
    for row in rows {
        if result.insert(&row.decision_id, row).is_some() {
            return Err(ProductEvaluationError::Binding("duplicate observation"));
        }
    }
    Ok(result)
}

pub(crate) fn validate_timing(
    cohorts: &[ProductObservedCohortV1],
    timing: &LongitudinalTimeEvidenceV1,
) -> Result<(), ProductEvaluationError> {
    if cohorts.len() != timing.windows.len() || cohorts.is_empty() {
        return Err(ProductEvaluationError::Binding(
            "actual future window coverage",
        ));
    }
    for cohort in cohorts {
        let window = timing
            .windows
            .iter()
            .find(|window| window.window_id == cohort.window_id)
            .ok_or(ProductEvaluationError::Binding("actual future window"))?;
        if cohort.snapshot_id != window.snapshot_id
            || cohort.observation_count != window.observation_count
            || cohort.observed_source_cut != window.observed_source_cut
            || cohort.first_decision_at < window.starts_unix_micros
            || cohort.last_decision_at > window.ends_unix_micros
            || cohort.first_outcome_at < window.starts_unix_micros
            || cohort.last_outcome_at > window.ends_unix_micros
        {
            return Err(ProductEvaluationError::Binding(
                "actual observed window binding",
            ));
        }
    }
    Ok(())
}

pub(crate) fn digest(
    cohorts: &[ProductObservedCohortV1],
    training_snapshot_id: Option<&StableId>,
) -> Digest32 {
    let mut bytes = b"hepta.intelligence-eval.observed-cohorts.v1\0".to_vec();
    match training_snapshot_id {
        Some(snapshot) => {
            bytes.push(1);
            push_id(&mut bytes, snapshot);
        }
        None => bytes.push(0),
    }
    bytes.extend_from_slice(&(cohorts.len() as u64).to_be_bytes());
    for cohort in cohorts {
        push_id(&mut bytes, &cohort.window_id);
        push_id(&mut bytes, &cohort.snapshot_id);
        for value in [
            cohort.first_decision_at,
            cohort.last_decision_at,
            cohort.first_outcome_at,
            cohort.last_outcome_at,
            cohort.observation_count,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        bytes.extend_from_slice(cohort.observed_source_cut.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    bytes.extend_from_slice(&(id.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(id.as_str().as_bytes());
}
