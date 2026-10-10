//! Training-only tabular outcome models for explicitly separated temporal folds.
//!
//! This is one fold primitive, not a full K-fold orchestrator or an efficacy gate.
//! Held-out targets deliberately contain no outcome labels. Identity and window
//! lineage are caller-supplied and still require independent authentication.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::push_id;

const MAX_ROWS: usize = 100_000;
const MAX_ACTIONS: usize = 128;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TemporalFoldPlan {
    pub plan_digest: Digest32,
    pub fold_id: StableId,
    pub training_watermark: u64,
    pub evaluation_start: u64,
    pub minimum_per_action: usize,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OutcomeTrainingSample {
    pub decision_id: StableId,
    pub principal_lineage: StableId,
    pub episode_lineage: StableId,
    pub window_id: StableId,
    pub action_id: StableId,
    pub outcome: FixedQ32,
    pub observed_at: u64,
    pub evidence_digest: Digest32,
}

/// Features and provenance only: validation labels cannot enter model fitting.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HeldOutTarget {
    pub decision_id: StableId,
    pub principal_lineage: StableId,
    pub episode_lineage: StableId,
    pub window_id: StableId,
    pub decision_at: u64,
    pub actions: Vec<StableId>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HeldOutPrediction {
    pub decision_id: StableId,
    pub outcomes: Vec<(StableId, FixedQ32)>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TemporalFoldReceipt {
    pub model_digest: Digest32,
    pub predictions_digest: Digest32,
    pub predictions: Vec<HeldOutPrediction>,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TemporalFoldError {
    InvalidPlan,
    RowLimit,
    EmptyDataset,
    DuplicateDecision,
    MissingEvidence,
    InvalidOutcome,
    FutureLeakage,
    PrincipalLeakage,
    EpisodeLeakage,
    WindowLeakage,
    ActionLimit,
    DuplicateAction,
    UnsupportedAction,
    Arithmetic,
}

impl fmt::Display for TemporalFoldError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for TemporalFoldError {}

/// Fit an empirical mean per action using training outcomes only.
///
/// The explicit earlier-time training population must be disjoint from held-out
/// principals, episodes, windows and decisions. Unsupported actions fail closed.
/// Inputs are borrowed and never mutated. No artifact is selected or persisted.
pub fn fit_temporal_fold(
    plan: &TemporalFoldPlan,
    training: &[OutcomeTrainingSample],
    targets: &[HeldOutTarget],
) -> Result<TemporalFoldReceipt, TemporalFoldError> {
    if plan.plan_digest.is_zero()
        || plan.minimum_per_action == 0
        || plan.minimum_per_action > MAX_ROWS
        || plan.training_watermark >= plan.evaluation_start
    {
        return Err(TemporalFoldError::InvalidPlan);
    }
    if training.len() > MAX_ROWS || targets.len() > MAX_ROWS {
        return Err(TemporalFoldError::RowLimit);
    }
    if training.is_empty() || targets.is_empty() {
        return Err(TemporalFoldError::EmptyDataset);
    }
    let mut ordered: Vec<_> = training.iter().collect();
    ordered.sort_by(|left, right| left.decision_id.cmp(&right.decision_id));
    let mut decisions = BTreeSet::new();
    let mut principals = BTreeSet::new();
    let mut episodes = BTreeSet::new();
    let mut windows = BTreeSet::new();
    let mut means: BTreeMap<StableId, (i128, usize)> = BTreeMap::new();
    let mut model_bytes = b"hepta.ope.temporal-fold.model.v1".to_vec();
    model_bytes.extend_from_slice(plan.plan_digest.as_array());
    push_id(&mut model_bytes, &plan.fold_id);
    model_bytes.extend_from_slice(&plan.training_watermark.to_be_bytes());
    model_bytes.extend_from_slice(&plan.evaluation_start.to_be_bytes());
    model_bytes.extend_from_slice(
        &u64::try_from(plan.minimum_per_action)
            .map_err(|_| TemporalFoldError::Arithmetic)?
            .to_be_bytes(),
    );
    for sample in ordered {
        if !decisions.insert(&sample.decision_id) {
            return Err(TemporalFoldError::DuplicateDecision);
        }
        if sample.evidence_digest.is_zero() {
            return Err(TemporalFoldError::MissingEvidence);
        }
        if !(FixedQ32::ZERO..=FixedQ32::ONE).contains(&sample.outcome) {
            return Err(TemporalFoldError::InvalidOutcome);
        }
        if sample.observed_at > plan.training_watermark {
            return Err(TemporalFoldError::FutureLeakage);
        }
        principals.insert(&sample.principal_lineage);
        episodes.insert(&sample.episode_lineage);
        windows.insert(&sample.window_id);
        let entry = means.entry(sample.action_id.clone()).or_default();
        entry.0 += i128::from(sample.outcome.raw());
        entry.1 += 1;
        if means.len() > MAX_ACTIONS {
            return Err(TemporalFoldError::ActionLimit);
        }
        let mut bytes = b"hepta.ope.temporal-fold.sample.v1".to_vec();
        for id in [
            &sample.decision_id,
            &sample.principal_lineage,
            &sample.episode_lineage,
            &sample.window_id,
            &sample.action_id,
        ] {
            push_id(&mut bytes, id);
        }
        bytes.extend_from_slice(&sample.outcome.raw().to_be_bytes());
        bytes.extend_from_slice(&sample.observed_at.to_be_bytes());
        bytes.extend_from_slice(sample.evidence_digest.as_array());
        model_bytes.extend_from_slice(Digest32::of_bytes(&bytes).as_array());
    }
    let model_digest = Digest32::of_bytes(&model_bytes);
    let mut ordered_targets: Vec<_> = targets.iter().collect();
    ordered_targets.sort_by(|left, right| left.decision_id.cmp(&right.decision_id));
    let mut prediction_bytes = b"hepta.ope.temporal-fold.predictions.v1".to_vec();
    prediction_bytes.extend_from_slice(model_digest.as_array());
    let mut predictions = Vec::with_capacity(targets.len());
    for target in ordered_targets {
        if !decisions.insert(&target.decision_id) {
            return Err(TemporalFoldError::DuplicateDecision);
        }
        if principals.contains(&target.principal_lineage) {
            return Err(TemporalFoldError::PrincipalLeakage);
        }
        if episodes.contains(&target.episode_lineage) {
            return Err(TemporalFoldError::EpisodeLeakage);
        }
        if windows.contains(&target.window_id) {
            return Err(TemporalFoldError::WindowLeakage);
        }
        if target.decision_at < plan.evaluation_start {
            return Err(TemporalFoldError::FutureLeakage);
        }
        if target.actions.is_empty() || target.actions.len() > MAX_ACTIONS {
            return Err(TemporalFoldError::ActionLimit);
        }
        let mut actions: Vec<_> = target.actions.iter().collect();
        actions.sort();
        let mut seen = BTreeSet::new();
        let mut outcomes = Vec::with_capacity(actions.len());
        let mut bytes = b"hepta.ope.temporal-fold.target.v1".to_vec();
        for id in [
            &target.decision_id,
            &target.principal_lineage,
            &target.episode_lineage,
            &target.window_id,
        ] {
            push_id(&mut bytes, id);
        }
        bytes.extend_from_slice(&target.decision_at.to_be_bytes());
        for action in actions {
            if !seen.insert(action) {
                return Err(TemporalFoldError::DuplicateAction);
            }
            let (sum, count) = means
                .get(action)
                .ok_or(TemporalFoldError::UnsupportedAction)?;
            if *count < plan.minimum_per_action {
                return Err(TemporalFoldError::UnsupportedAction);
            }
            let count = i128::try_from(*count).map_err(|_| TemporalFoldError::Arithmetic)?;
            let quotient = sum / count;
            let twice_remainder = (sum % count) * 2;
            let rounded = quotient
                + i128::from(
                    twice_remainder > count || (twice_remainder == count && quotient % 2 != 0),
                );
            let prediction = FixedQ32::from_raw(
                i64::try_from(rounded).map_err(|_| TemporalFoldError::Arithmetic)?,
            );
            push_id(&mut bytes, action);
            bytes.extend_from_slice(&prediction.raw().to_be_bytes());
            outcomes.push((action.clone(), prediction));
        }
        prediction_bytes.extend_from_slice(Digest32::of_bytes(&bytes).as_array());
        predictions.push(HeldOutPrediction {
            decision_id: target.decision_id.clone(),
            outcomes,
        });
    }
    Ok(TemporalFoldReceipt {
        model_digest,
        predictions_digest: Digest32::of_bytes(&prediction_bytes),
        predictions,
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[cfg(test)]
#[path = "temporal_fold_tests.rs"]
mod tests;
