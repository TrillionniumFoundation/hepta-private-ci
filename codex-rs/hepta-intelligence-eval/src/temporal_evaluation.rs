//! Label-isolated training, prediction binding and cluster OPE composition.
//!
//! This pure, fixed-horizon baseline fits on earlier independent principals,
//! episodes and windows, then evaluates an exactly joined held-out cohort.
//! No runtime writer, artifact selector, model provider or acceptance role is
//! constructed. Supplied lineage and observed outcomes still need authenticated
//! provenance. Synthetic timestamps do not establish future-calendar efficacy.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ClusterAssignment;
use crate::ClusterConfidenceError;
use crate::ClusterConfidencePlan;
use crate::ClusterOpeEstimate;
use crate::HeldOutTarget;
use crate::OpePlan;
use crate::OpeRow;
use crate::OutcomeTrainingSample;
use crate::TemporalFoldError;
use crate::TemporalFoldPlan;
use crate::estimate_cluster_intervals;
use crate::fit_temporal_fold;
use crate::push_id;

const MAX_EVALUATION_ROWS: usize = 16_384;
const MAX_ACTION_CELLS: usize = 262_144;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TemporalEvaluationPlan {
    pub plan_digest: Digest32,
    pub evaluation_id: StableId,
    pub objective_digest: Digest32,
    pub fold: TemporalFoldPlan,
    pub ope: OpePlan,
    pub confidence: ClusterConfidencePlan,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TemporalEvaluationReceipt {
    pub evaluation_id: StableId,
    pub plan_digest: Digest32,
    pub model_digest: Digest32,
    pub predictions_digest: Digest32,
    pub estimate: ClusterOpeEstimate,
    pub evidence_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TemporalEvaluationError {
    InvalidTimeline,
    MissingObjective,
    PlanDigestMismatch,
    ResourceLimit,
    Arithmetic,
    CohortMismatch,
    ActionMismatch,
    OutcomeBeforeDecision,
    DependentClusterSplit,
    Fold(TemporalFoldError),
    Confidence(ClusterConfidenceError),
}

impl fmt::Display for TemporalEvaluationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for TemporalEvaluationError {}

impl From<TemporalFoldError> for TemporalEvaluationError {
    fn from(error: TemporalFoldError) -> Self {
        Self::Fold(error)
    }
}

impl From<ClusterConfidenceError> for TemporalEvaluationError {
    fn from(error: ClusterConfidenceError) -> Self {
        Self::Confidence(error)
    }
}

impl TemporalEvaluationPlan {
    /// Compute the canonical digest for this complete evaluation plan.
    ///
    /// The digest excludes `plan_digest` itself. It binds every semantic field
    /// of each independently identified fold, OPE and confidence subplan.
    pub fn canonical_digest(&self) -> Result<Digest32, TemporalEvaluationError> {
        let mut bytes = b"hepta.ope.temporal-evaluation-plan.v1".to_vec();
        push_id(&mut bytes, &self.evaluation_id);
        bytes.extend_from_slice(self.objective_digest.as_array());

        bytes.extend_from_slice(self.fold.plan_digest.as_array());
        push_id(&mut bytes, &self.fold.fold_id);
        bytes.extend_from_slice(&self.fold.training_watermark.to_be_bytes());
        bytes.extend_from_slice(&self.fold.evaluation_start.to_be_bytes());
        push_usize(&mut bytes, self.fold.minimum_per_action)?;

        bytes.extend_from_slice(self.ope.plan_digest.as_array());
        bytes.extend_from_slice(&self.ope.outcome_watermark.to_be_bytes());
        push_usize(&mut bytes, self.ope.minimum_rows)?;
        bytes.extend_from_slice(&self.ope.minimum_ess.raw().to_be_bytes());
        bytes.extend_from_slice(&self.ope.maximum_weight.raw().to_be_bytes());

        bytes.extend_from_slice(self.confidence.plan_digest.as_array());
        bytes.extend_from_slice(self.confidence.assumptions_digest.as_array());
        bytes.extend_from_slice(&self.confidence.family_alpha_ppm.to_be_bytes());
        bytes.extend_from_slice(&self.confidence.simultaneous_comparisons.to_be_bytes());
        push_usize(&mut bytes, self.confidence.minimum_clusters)?;

        Ok(Digest32::of_bytes(&bytes))
    }
}

/// Compose the actual fitted model with the supported, observed OPE cohort.
///
/// `observations` supplies outcomes and action propensities. Its prediction
/// values and outcome-model evidence are intentionally ignored: both are
/// rebuilt from label-free targets and TRAINING outcomes. All input arrays
/// remain unchanged. Target, observation and cluster joins must be bijections.
pub fn evaluate_temporal_holdout(
    plan: &TemporalEvaluationPlan,
    training: &[OutcomeTrainingSample],
    targets: &[HeldOutTarget],
    observations: &[OpeRow],
    assignments: &[ClusterAssignment],
) -> Result<TemporalEvaluationReceipt, TemporalEvaluationError> {
    if plan.objective_digest.is_zero() {
        return Err(TemporalEvaluationError::MissingObjective);
    }
    if plan.plan_digest.is_zero() || plan.plan_digest != plan.canonical_digest()? {
        return Err(TemporalEvaluationError::PlanDigestMismatch);
    }
    if plan.ope.outcome_watermark < plan.fold.evaluation_start {
        return Err(TemporalEvaluationError::InvalidTimeline);
    }
    if targets.len() > MAX_EVALUATION_ROWS {
        return Err(TemporalEvaluationError::ResourceLimit);
    }
    if targets.len() != observations.len() || targets.len() != assignments.len() {
        return Err(TemporalEvaluationError::CohortMismatch);
    }
    let mut cells = 0_usize;
    for target in targets {
        cells = cells
            .checked_add(target.actions.len())
            .filter(|count| *count <= MAX_ACTION_CELLS)
            .ok_or(TemporalEvaluationError::ResourceLimit)?;
    }
    let fitted = fit_temporal_fold(&plan.fold, training, targets)?;
    let targets_by_id: BTreeMap<_, _> = targets
        .iter()
        .map(|target| (&target.decision_id, target))
        .collect();
    let predictions: BTreeMap<_, _> = fitted
        .predictions
        .iter()
        .map(|prediction| (&prediction.decision_id, &prediction.outcomes))
        .collect();
    let mut clusters = BTreeMap::new();
    for assignment in assignments {
        if clusters
            .insert(&assignment.decision_id, &assignment.cluster_id)
            .is_some()
        {
            return Err(TemporalEvaluationError::CohortMismatch);
        }
    }
    let mut principal_clusters = BTreeMap::new();
    let mut episode_clusters = BTreeMap::new();
    let mut seen = BTreeSet::new();
    let mut bound_rows = Vec::with_capacity(observations.len());
    for observation in observations {
        if !seen.insert(&observation.decision_id) {
            return Err(TemporalEvaluationError::CohortMismatch);
        }
        let target = targets_by_id
            .get(&observation.decision_id)
            .ok_or(TemporalEvaluationError::CohortMismatch)?;
        let cluster = clusters
            .get(&observation.decision_id)
            .ok_or(TemporalEvaluationError::CohortMismatch)?;
        bind_cluster(&mut principal_clusters, &target.principal_lineage, cluster)?;
        bind_cluster(&mut episode_clusters, &target.episode_lineage, cluster)?;
        if observation.outcome_observed_at < target.decision_at {
            return Err(TemporalEvaluationError::OutcomeBeforeDecision);
        }
        let outputs = predictions
            .get(&observation.decision_id)
            .ok_or(TemporalEvaluationError::CohortMismatch)?;
        if observation.actions.len() != outputs.len() {
            return Err(TemporalEvaluationError::ActionMismatch);
        }
        let prediction_map: BTreeMap<_, _> = outputs.iter().cloned().collect();
        let mut action_ids = BTreeSet::new();
        for action in &observation.actions {
            if !action_ids.insert(&action.action_id)
                || !prediction_map.contains_key(&action.action_id)
            {
                return Err(TemporalEvaluationError::ActionMismatch);
            }
        }
        let mut row = observation.clone();
        row.outcome_model_evidence = fitted.model_digest;
        for action in &mut row.actions {
            action.predicted_outcome = *prediction_map
                .get(&action.action_id)
                .ok_or(TemporalEvaluationError::ActionMismatch)?;
        }
        bound_rows.push(row);
    }
    let estimate =
        estimate_cluster_intervals(&plan.ope, &plan.confidence, &bound_rows, assignments)?;
    let mut bytes = b"hepta.ope.temporal-holdout-pipeline.v2".to_vec();
    push_id(&mut bytes, &plan.evaluation_id);
    bytes.extend_from_slice(plan.plan_digest.as_array());
    bytes.extend_from_slice(plan.objective_digest.as_array());
    bytes.extend_from_slice(fitted.model_digest.as_array());
    bytes.extend_from_slice(fitted.predictions_digest.as_array());
    bytes.extend_from_slice(estimate.evidence_digest.as_array());
    Ok(TemporalEvaluationReceipt {
        evaluation_id: plan.evaluation_id.clone(),
        plan_digest: plan.plan_digest,
        model_digest: fitted.model_digest,
        predictions_digest: fitted.predictions_digest,
        estimate,
        evidence_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn push_usize(bytes: &mut Vec<u8>, value: usize) -> Result<(), TemporalEvaluationError> {
    let value = u64::try_from(value).map_err(|_| TemporalEvaluationError::Arithmetic)?;
    bytes.extend_from_slice(&value.to_be_bytes());
    Ok(())
}

fn bind_cluster<'a>(
    bindings: &mut BTreeMap<&'a StableId, &'a StableId>,
    lineage: &'a StableId,
    cluster: &'a StableId,
) -> Result<(), TemporalEvaluationError> {
    if bindings
        .insert(lineage, cluster)
        .is_some_and(|previous| previous != cluster)
    {
        return Err(TemporalEvaluationError::DependentClusterSplit);
    }
    Ok(())
}

#[cfg(test)]
#[path = "temporal_evaluation_tests.rs"]
mod tests;
