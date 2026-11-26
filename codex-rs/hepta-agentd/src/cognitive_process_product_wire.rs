//! Plain process inputs for original product evaluation; no sealed receipts.

use super::cognitive_process_evidence::AuthenticatedPrincipalV1Raw;
use super::cognitive_process_wire::*;
use serde::Deserialize;
use serde::Serialize;

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct TemporalEvaluationPlanRaw {
    pub plan_digest: Digest,
    pub evaluation_id: Id,
    pub objective_digest: Digest,
    pub fold: TemporalFoldPlanRaw,
    pub ope: OpePlanRaw,
    pub confidence: ClusterConfidencePlanRaw,
}

impl From<TemporalEvaluationPlanRaw> for codex_hepta_intelligence_eval::TemporalEvaluationPlan {
    fn from(raw: TemporalEvaluationPlanRaw) -> Self {
        Self {
            plan_digest: raw.plan_digest.into(),
            evaluation_id: raw.evaluation_id.into(),
            objective_digest: raw.objective_digest.into(),
            fold: raw.fold.into(),
            ope: raw.ope.into(),
            confidence: raw.confidence.into(),
        }
    }
}

impl From<codex_hepta_intelligence_eval::TemporalEvaluationPlan> for TemporalEvaluationPlanRaw {
    fn from(raw: codex_hepta_intelligence_eval::TemporalEvaluationPlan) -> Self {
        Self {
            plan_digest: raw.plan_digest.into(),
            evaluation_id: raw.evaluation_id.into(),
            objective_digest: raw.objective_digest.into(),
            fold: raw.fold.into(),
            ope: raw.ope.into(),
            confidence: raw.confidence.into(),
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct TemporalFoldPlanRaw {
    pub plan_digest: Digest,
    pub fold_id: Id,
    pub training_watermark: u64,
    pub evaluation_start: u64,
    pub minimum_per_action: usize,
}

impl From<TemporalFoldPlanRaw> for codex_hepta_intelligence_eval::TemporalFoldPlan {
    fn from(raw: TemporalFoldPlanRaw) -> Self {
        Self {
            plan_digest: raw.plan_digest.into(),
            fold_id: raw.fold_id.into(),
            training_watermark: raw.training_watermark,
            evaluation_start: raw.evaluation_start,
            minimum_per_action: raw.minimum_per_action,
        }
    }
}

impl From<codex_hepta_intelligence_eval::TemporalFoldPlan> for TemporalFoldPlanRaw {
    fn from(raw: codex_hepta_intelligence_eval::TemporalFoldPlan) -> Self {
        Self {
            plan_digest: raw.plan_digest.into(),
            fold_id: raw.fold_id.into(),
            training_watermark: raw.training_watermark,
            evaluation_start: raw.evaluation_start,
            minimum_per_action: raw.minimum_per_action,
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OutcomeTrainingSampleRaw {
    pub decision_id: Id,
    pub principal_lineage: Id,
    pub episode_lineage: Id,
    pub window_id: Id,
    pub action_id: Id,
    pub outcome: Fixed,
    pub observed_at: u64,
    pub evidence_digest: Digest,
}

impl From<OutcomeTrainingSampleRaw> for codex_hepta_intelligence_eval::OutcomeTrainingSample {
    fn from(raw: OutcomeTrainingSampleRaw) -> Self {
        Self {
            decision_id: raw.decision_id.into(),
            principal_lineage: raw.principal_lineage.into(),
            episode_lineage: raw.episode_lineage.into(),
            window_id: raw.window_id.into(),
            action_id: raw.action_id.into(),
            outcome: raw.outcome.into(),
            observed_at: raw.observed_at,
            evidence_digest: raw.evidence_digest.into(),
        }
    }
}

impl From<codex_hepta_intelligence_eval::OutcomeTrainingSample> for OutcomeTrainingSampleRaw {
    fn from(raw: codex_hepta_intelligence_eval::OutcomeTrainingSample) -> Self {
        Self {
            decision_id: raw.decision_id.into(),
            principal_lineage: raw.principal_lineage.into(),
            episode_lineage: raw.episode_lineage.into(),
            window_id: raw.window_id.into(),
            action_id: raw.action_id.into(),
            outcome: raw.outcome.into(),
            observed_at: raw.observed_at,
            evidence_digest: raw.evidence_digest.into(),
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct HeldOutTargetRaw {
    pub decision_id: Id,
    pub principal_lineage: Id,
    pub episode_lineage: Id,
    pub window_id: Id,
    pub decision_at: u64,
    pub actions: Vec<Id>,
}

impl From<HeldOutTargetRaw> for codex_hepta_intelligence_eval::HeldOutTarget {
    fn from(raw: HeldOutTargetRaw) -> Self {
        Self {
            decision_id: raw.decision_id.into(),
            principal_lineage: raw.principal_lineage.into(),
            episode_lineage: raw.episode_lineage.into(),
            window_id: raw.window_id.into(),
            decision_at: raw.decision_at,
            actions: raw
                .actions
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
        }
    }
}

impl From<codex_hepta_intelligence_eval::HeldOutTarget> for HeldOutTargetRaw {
    fn from(raw: codex_hepta_intelligence_eval::HeldOutTarget) -> Self {
        Self {
            decision_id: raw.decision_id.into(),
            principal_lineage: raw.principal_lineage.into(),
            episode_lineage: raw.episode_lineage.into(),
            window_id: raw.window_id.into(),
            decision_at: raw.decision_at,
            actions: raw
                .actions
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OpeActionRaw {
    pub action_id: Id,
    pub behavior_probability: Probability,
    pub evaluation_probability: Probability,
    pub predicted_outcome: Fixed,
}

impl From<OpeActionRaw> for codex_hepta_intelligence_eval::OpeAction {
    fn from(raw: OpeActionRaw) -> Self {
        Self {
            action_id: raw.action_id.into(),
            behavior_probability: raw.behavior_probability.into(),
            evaluation_probability: raw.evaluation_probability.into(),
            predicted_outcome: raw.predicted_outcome.into(),
        }
    }
}

impl From<codex_hepta_intelligence_eval::OpeAction> for OpeActionRaw {
    fn from(raw: codex_hepta_intelligence_eval::OpeAction) -> Self {
        Self {
            action_id: raw.action_id.into(),
            behavior_probability: raw.behavior_probability.into(),
            evaluation_probability: raw.evaluation_probability.into(),
            predicted_outcome: raw.predicted_outcome.into(),
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OpeRowRaw {
    pub decision_id: Id,
    pub chosen_action: Id,
    pub complete_candidates: bool,
    pub actions: Vec<OpeActionRaw>,
    pub finalized_outcome: Option<Fixed>,
    pub outcome_observed_at: u64,
    pub outcome_evidence: Digest,
    pub outcome_model_evidence: Digest,
}

impl From<OpeRowRaw> for codex_hepta_intelligence_eval::OpeRow {
    fn from(raw: OpeRowRaw) -> Self {
        Self {
            decision_id: raw.decision_id.into(),
            chosen_action: raw.chosen_action.into(),
            complete_candidates: raw.complete_candidates,
            actions: raw
                .actions
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            finalized_outcome: raw.finalized_outcome.map(std::convert::Into::into),
            outcome_observed_at: raw.outcome_observed_at,
            outcome_evidence: raw.outcome_evidence.into(),
            outcome_model_evidence: raw.outcome_model_evidence.into(),
        }
    }
}

impl From<codex_hepta_intelligence_eval::OpeRow> for OpeRowRaw {
    fn from(raw: codex_hepta_intelligence_eval::OpeRow) -> Self {
        Self {
            decision_id: raw.decision_id.into(),
            chosen_action: raw.chosen_action.into(),
            complete_candidates: raw.complete_candidates,
            actions: raw
                .actions
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            finalized_outcome: raw.finalized_outcome.map(std::convert::Into::into),
            outcome_observed_at: raw.outcome_observed_at,
            outcome_evidence: raw.outcome_evidence.into(),
            outcome_model_evidence: raw.outcome_model_evidence.into(),
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OpePlanRaw {
    pub plan_digest: Digest,
    pub outcome_watermark: u64,
    pub minimum_rows: usize,
    pub minimum_ess: Fixed,
    pub maximum_weight: Fixed,
}

impl From<OpePlanRaw> for codex_hepta_intelligence_eval::OpePlan {
    fn from(raw: OpePlanRaw) -> Self {
        Self {
            plan_digest: raw.plan_digest.into(),
            outcome_watermark: raw.outcome_watermark,
            minimum_rows: raw.minimum_rows,
            minimum_ess: raw.minimum_ess.into(),
            maximum_weight: raw.maximum_weight.into(),
        }
    }
}

impl From<codex_hepta_intelligence_eval::OpePlan> for OpePlanRaw {
    fn from(raw: codex_hepta_intelligence_eval::OpePlan) -> Self {
        Self {
            plan_digest: raw.plan_digest.into(),
            outcome_watermark: raw.outcome_watermark,
            minimum_rows: raw.minimum_rows,
            minimum_ess: raw.minimum_ess.into(),
            maximum_weight: raw.maximum_weight.into(),
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ClusterAssignmentRaw {
    pub decision_id: Id,
    pub cluster_id: Id,
}

impl From<ClusterAssignmentRaw> for codex_hepta_intelligence_eval::ClusterAssignment {
    fn from(raw: ClusterAssignmentRaw) -> Self {
        Self {
            decision_id: raw.decision_id.into(),
            cluster_id: raw.cluster_id.into(),
        }
    }
}

impl From<codex_hepta_intelligence_eval::ClusterAssignment> for ClusterAssignmentRaw {
    fn from(raw: codex_hepta_intelligence_eval::ClusterAssignment) -> Self {
        Self {
            decision_id: raw.decision_id.into(),
            cluster_id: raw.cluster_id.into(),
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ClusterConfidencePlanRaw {
    pub plan_digest: Digest,
    pub assumptions_digest: Digest,
    pub family_alpha_ppm: u32,
    pub simultaneous_comparisons: u32,
    pub minimum_clusters: usize,
}

impl From<ClusterConfidencePlanRaw> for codex_hepta_intelligence_eval::ClusterConfidencePlan {
    fn from(raw: ClusterConfidencePlanRaw) -> Self {
        Self {
            plan_digest: raw.plan_digest.into(),
            assumptions_digest: raw.assumptions_digest.into(),
            family_alpha_ppm: raw.family_alpha_ppm,
            simultaneous_comparisons: raw.simultaneous_comparisons,
            minimum_clusters: raw.minimum_clusters,
        }
    }
}

impl From<codex_hepta_intelligence_eval::ClusterConfidencePlan> for ClusterConfidencePlanRaw {
    fn from(raw: codex_hepta_intelligence_eval::ClusterConfidencePlan) -> Self {
        Self {
            plan_digest: raw.plan_digest.into(),
            assumptions_digest: raw.assumptions_digest.into(),
            family_alpha_ppm: raw.family_alpha_ppm,
            simultaneous_comparisons: raw.simultaneous_comparisons,
            minimum_clusters: raw.minimum_clusters,
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ProductMetricSourceContractV1Raw {
    pub metric_id: Id,
    pub source: ProductMetricSourceV1Raw,
}

impl From<ProductMetricSourceContractV1Raw>
    for codex_hepta_intelligence_eval::ProductMetricSourceContractV1
{
    fn from(raw: ProductMetricSourceContractV1Raw) -> Self {
        Self {
            metric_id: raw.metric_id.into(),
            source: raw.source.into(),
        }
    }
}

impl From<codex_hepta_intelligence_eval::ProductMetricSourceContractV1>
    for ProductMetricSourceContractV1Raw
{
    fn from(raw: codex_hepta_intelligence_eval::ProductMetricSourceContractV1) -> Self {
        Self {
            metric_id: raw.metric_id.into(),
            source: raw.source.into(),
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct TemporalComparisonInputsV1Raw {
    pub training: Vec<OutcomeTrainingSampleRaw>,
    pub targets: Vec<HeldOutTargetRaw>,
    pub candidate_observations: Vec<OpeRowRaw>,
    pub baseline_observations: Vec<OpeRowRaw>,
    pub assignments: Vec<ClusterAssignmentRaw>,
    pub snapshot_ids: Vec<Id>,
    pub future_window_ids: Vec<Id>,
}

impl From<TemporalComparisonInputsV1Raw>
    for codex_hepta_intelligence_eval::TemporalComparisonInputsV1
{
    fn from(raw: TemporalComparisonInputsV1Raw) -> Self {
        Self {
            training: raw
                .training
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            targets: raw
                .targets
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            candidate_observations: raw
                .candidate_observations
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            baseline_observations: raw
                .baseline_observations
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            assignments: raw
                .assignments
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            snapshot_ids: raw
                .snapshot_ids
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            future_window_ids: raw
                .future_window_ids
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
        }
    }
}

impl From<codex_hepta_intelligence_eval::TemporalComparisonInputsV1>
    for TemporalComparisonInputsV1Raw
{
    fn from(raw: codex_hepta_intelligence_eval::TemporalComparisonInputsV1) -> Self {
        Self {
            training: raw
                .training
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            targets: raw
                .targets
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            candidate_observations: raw
                .candidate_observations
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            baseline_observations: raw
                .baseline_observations
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            assignments: raw
                .assignments
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            snapshot_ids: raw
                .snapshot_ids
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            future_window_ids: raw
                .future_window_ids
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ProductQualificationContextV1Raw {
    pub generator: AuthenticatedPrincipalV1Raw,
    pub evaluator: AuthenticatedPrincipalV1Raw,
    pub retention_receipt_digests: Vec<Digest>,
    pub unlearning_receipt_digest: Digest,
}

impl From<ProductQualificationContextV1Raw>
    for codex_hepta_intelligence_eval::ProductQualificationContextV1
{
    fn from(raw: ProductQualificationContextV1Raw) -> Self {
        Self {
            generator: raw.generator.into(),
            evaluator: raw.evaluator.into(),
            retention_receipt_digests: raw
                .retention_receipt_digests
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            unlearning_receipt_digest: raw.unlearning_receipt_digest.into(),
        }
    }
}

impl From<codex_hepta_intelligence_eval::ProductQualificationContextV1>
    for ProductQualificationContextV1Raw
{
    fn from(raw: codex_hepta_intelligence_eval::ProductQualificationContextV1) -> Self {
        Self {
            generator: raw.generator.into(),
            evaluator: raw.evaluator.into(),
            retention_receipt_digests: raw
                .retention_receipt_digests
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            unlearning_receipt_digest: raw.unlearning_receipt_digest.into(),
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct HoldoutWriterFenceV1Raw {
    pub owner_id: Id,
    pub generation: u64,
    pub lease_digest: Digest,
}

impl From<HoldoutWriterFenceV1Raw> for codex_hepta_intelligence_eval::HoldoutWriterFenceV1 {
    fn from(raw: HoldoutWriterFenceV1Raw) -> Self {
        Self {
            owner_id: raw.owner_id.into(),
            generation: raw.generation,
            lease_digest: raw.lease_digest.into(),
        }
    }
}

impl From<codex_hepta_intelligence_eval::HoldoutWriterFenceV1> for HoldoutWriterFenceV1Raw {
    fn from(raw: codex_hepta_intelligence_eval::HoldoutWriterFenceV1) -> Self {
        Self {
            owner_id: raw.owner_id.into(),
            generation: raw.generation,
            lease_digest: raw.lease_digest.into(),
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct FinalHoldoutCasAnchorV1Raw {
    pub fence_generation: u64,
    pub record_count: u64,
    pub state_digest: Digest,
}

impl From<FinalHoldoutCasAnchorV1Raw> for codex_hepta_intelligence_eval::FinalHoldoutCasAnchorV1 {
    fn from(raw: FinalHoldoutCasAnchorV1Raw) -> Self {
        Self {
            fence_generation: raw.fence_generation,
            record_count: raw.record_count,
            state_digest: raw.state_digest.into(),
        }
    }
}

impl From<codex_hepta_intelligence_eval::FinalHoldoutCasAnchorV1> for FinalHoldoutCasAnchorV1Raw {
    fn from(raw: codex_hepta_intelligence_eval::FinalHoldoutCasAnchorV1) -> Self {
        Self {
            fence_generation: raw.fence_generation,
            record_count: raw.record_count,
            state_digest: raw.state_digest.into(),
        }
    }
}
