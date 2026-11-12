//! Raw temporal declarations from the immutable evaluation deployment.
//! Original canonical-digest, support and evidence validation remains in the
//! original runner; none of these data structures is a sealed evaluation.

use codex_hepta_intelligence_eval::{ClusterConfidencePlan, OpePlan, TemporalEvaluationPlan,
    TemporalFoldPlan};
use codex_hepta_types::{Digest32, FixedQ32, StableId};
use serde::{Deserialize, Serialize};
use crate::AgentdError;
use super::deployment_error;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalTemporalFoldData {
    pub plan_digest: [u8; 32],
    pub fold_id: String,
    pub training_watermark: u64,
    pub evaluation_start: u64,
    pub minimum_per_action: usize,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalOpeData {
    pub plan_digest: [u8; 32],
    pub outcome_watermark: u64,
    pub minimum_rows: usize,
    pub minimum_ess_q32: i64,
    pub maximum_weight_q32: i64,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalConfidenceData {
    pub plan_digest: [u8; 32],
    pub assumptions_digest: [u8; 32],
    pub family_alpha_ppm: u32,
    pub simultaneous_comparisons: u32,
    pub minimum_clusters: usize,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalTemporalPlanData {
    pub plan_digest: [u8; 32],
    pub evaluation_id: String,
    pub objective_digest: [u8; 32],
    pub fold: OriginalTemporalFoldData,
    pub ope: OriginalOpeData,
    pub confidence: OriginalConfidenceData,
}
impl OriginalTemporalPlanData {
    pub(super) fn original(&self) -> Result<TemporalEvaluationPlan, AgentdError> {
        Ok(TemporalEvaluationPlan {
            plan_digest: Digest32::from_array(self.plan_digest),
            evaluation_id: StableId::new(&self.evaluation_id).map_err(deployment_error)?,
            objective_digest: Digest32::from_array(self.objective_digest),
            fold: TemporalFoldPlan {
                plan_digest: Digest32::from_array(self.fold.plan_digest),
                fold_id: StableId::new(&self.fold.fold_id).map_err(deployment_error)?,
                training_watermark: self.fold.training_watermark,
                evaluation_start: self.fold.evaluation_start,
                minimum_per_action: self.fold.minimum_per_action,
            },
            ope: OpePlan {
                plan_digest: Digest32::from_array(self.ope.plan_digest),
                outcome_watermark: self.ope.outcome_watermark,
                minimum_rows: self.ope.minimum_rows,
                minimum_ess: FixedQ32::from_raw(self.ope.minimum_ess_q32),
                maximum_weight: FixedQ32::from_raw(self.ope.maximum_weight_q32),
            },
            confidence: ClusterConfidencePlan {
                plan_digest: Digest32::from_array(self.confidence.plan_digest),
                assumptions_digest: Digest32::from_array(self.confidence.assumptions_digest),
                family_alpha_ppm: self.confidence.family_alpha_ppm,
                simultaneous_comparisons: self.confidence.simultaneous_comparisons,
                minimum_clusters: self.confidence.minimum_clusters,
            },
        })
    }
}
