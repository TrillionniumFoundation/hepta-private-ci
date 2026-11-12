//! Exact temporal thresholds and original subplan pins; no estimator output.

use super::*;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct TemporalData {
    plan_digest: [u8; 32],
    evaluation_id: String,
    fold_id: String,
    fold_plan: [u8; 32],
    training_watermark: u64,
    evaluation_start: u64,
    minimum_per_action: usize,
    ope_plan: [u8; 32],
    outcome_watermark: u64,
    minimum_rows: usize,
    minimum_ess_q32: i64,
    maximum_weight_q32: i64,
    confidence_plan: [u8; 32],
    confidence_assumptions: [u8; 32],
    minimum_clusters: usize,
}

impl TemporalData {
    pub(super) fn convert(
        &self,
        objective_digest: Digest32,
        family_alpha_ppm: u32,
        simultaneous_comparisons: u32,
    ) -> io::Result<TemporalEvaluationPlan> {
        let plan = TemporalEvaluationPlan {
            plan_digest: Digest32::from_array(self.plan_digest),
            evaluation_id: id(&self.evaluation_id)?,
            objective_digest,
            fold: TemporalFoldPlan {
                plan_digest: Digest32::from_array(self.fold_plan),
                fold_id: id(&self.fold_id)?,
                training_watermark: self.training_watermark,
                evaluation_start: self.evaluation_start,
                minimum_per_action: self.minimum_per_action,
            },
            ope: OpePlan {
                plan_digest: Digest32::from_array(self.ope_plan),
                outcome_watermark: self.outcome_watermark,
                minimum_rows: self.minimum_rows,
                minimum_ess: FixedQ32::from_raw(self.minimum_ess_q32),
                maximum_weight: FixedQ32::from_raw(self.maximum_weight_q32),
            },
            confidence: ClusterConfidencePlan {
                plan_digest: Digest32::from_array(self.confidence_plan),
                assumptions_digest: Digest32::from_array(self.confidence_assumptions),
                family_alpha_ppm,
                simultaneous_comparisons,
                minimum_clusters: self.minimum_clusters,
            },
        };
        if plan.plan_digest.is_zero()
            || plan.plan_digest != plan.canonical_digest().map_err(io::Error::other)?
        {
            return Err(io::Error::other("original B temporal plan digest differs"));
        }
        Ok(plan)
    }
}
