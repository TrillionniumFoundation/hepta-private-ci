//! Original preregistration declarations. Freezing remains an original Cell
//! and Product operation over actual drained journals and supplied temporal
//! inputs. No private plan or qualification receipt is deserialized here.

use codex_hepta_intelligence_eval::{
    CrossFoldPartitionV1, CrossFoldPlanV1, EvaluationClaimScopeV1, EvaluationDirectionV1,
    MetricContractV1, MetricRoleContractV2, MetricRoleV2, ProductMetricSourceContractV1,
    ProductMetricSourceV1, ProductQualificationContextV1,
};
use codex_hepta_types::{Digest32, FixedQ32, StableId};
use serde::{Deserialize, Serialize};
use crate::{AgentdError, CellEvaluationRegistrationV1};
use super::{deployment_error, deployment_refused};
use super::comparison_data::OriginalComparisonData;
use super::learning_data::{PrincipalData, required_option};

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum OriginalClaimScopeData { Qualification, SystemLongitudinal }
#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum OriginalDirectionData { Maximize, Minimize }
#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum OriginalMetricRoleData {
    PrimarySuperiority { minimum_improvement_q32: i64 },
    NonInferiority { maximum_regression_q32: i64 },
    AbsoluteConstraint,
}
#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum OriginalMetricSourceData { Ips, Snips, DoublyRobust }
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalMetricData {
    pub metric_id: String,
    pub direction: OriginalDirectionData,
    #[serde(deserialize_with = "required_option")]
    pub safety_floor_q32: Option<i64>,
    pub role: OriginalMetricRoleData,
    pub source: OriginalMetricSourceData,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalFoldData {
    pub fold_id: String,
    pub training_principals: Vec<String>,
    pub training_episodes: Vec<String>,
    pub training_windows: Vec<String>,
    pub holdout_principals: Vec<String>,
    pub holdout_episodes: Vec<String>,
    pub holdout_windows: Vec<String>,
    pub model_digest: [u8; 32],
    pub predictions_digest: [u8; 32],
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalEvaluationRegistrationData {
    pub plan_id: String,
    pub claim_scope: OriginalClaimScopeData,
    pub candidate_id: String,
    pub baseline_id: String,
    pub objective_digest: [u8; 32],
    pub dataset_digest: [u8; 32],
    pub estimand_digest: [u8; 32],
    pub metrics: Vec<OriginalMetricData>,
    pub family_alpha_ppm: u32,
    pub simultaneous_comparisons: u32,
    pub folds: Vec<OriginalFoldData>,
    pub final_holdout_window_id: String,
    pub final_holdout_digest: [u8; 32],
    pub comparison: OriginalComparisonData,
}
impl OriginalEvaluationRegistrationData {
    pub(super) fn original(&self) -> Result<CellEvaluationRegistrationV1, AgentdError> {
        // This loader has no original longitudinal timing owner. Refuse that
        // mode explicitly instead of manufacturing elapsed-window evidence.
        if !matches!(self.claim_scope, OriginalClaimScopeData::Qualification) {
            return Err(deployment_refused("original longitudinal timing owner is not supplied"));
        }
        let mut contracts = Vec::with_capacity(self.metrics.len());
        let mut roles = Vec::with_capacity(self.metrics.len());
        let mut sources = Vec::with_capacity(self.metrics.len());
        for metric in &self.metrics {
            let id = StableId::new(&metric.metric_id).map_err(deployment_error)?;
            contracts.push(MetricContractV1 {
                metric_id: id.clone(),
                direction: match metric.direction {
                    OriginalDirectionData::Maximize => EvaluationDirectionV1::Maximize,
                    OriginalDirectionData::Minimize => EvaluationDirectionV1::Minimize,
                },
                safety_floor: metric.safety_floor_q32.map(FixedQ32::from_raw),
            });
            roles.push(MetricRoleContractV2 {
                metric_id: id.clone(),
                role: match metric.role {
                    OriginalMetricRoleData::PrimarySuperiority { minimum_improvement_q32 } =>
                        MetricRoleV2::PrimarySuperiority {
                            minimum_improvement: FixedQ32::from_raw(minimum_improvement_q32),
                        },
                    OriginalMetricRoleData::NonInferiority { maximum_regression_q32 } =>
                        MetricRoleV2::NonInferiority {
                            maximum_regression: FixedQ32::from_raw(maximum_regression_q32),
                        },
                    OriginalMetricRoleData::AbsoluteConstraint => MetricRoleV2::AbsoluteConstraint,
                },
            });
            sources.push(ProductMetricSourceContractV1 {
                metric_id: id,
                source: match metric.source {
                    OriginalMetricSourceData::Ips => ProductMetricSourceV1::Ips,
                    OriginalMetricSourceData::Snips => ProductMetricSourceV1::Snips,
                    OriginalMetricSourceData::DoublyRobust => ProductMetricSourceV1::DoublyRobust,
                },
            });
        }
        let folds = self.folds.iter().map(|fold| Ok(CrossFoldPartitionV1 {
            fold_id: StableId::new(&fold.fold_id).map_err(deployment_error)?,
            training_principals: original_ids(&fold.training_principals)?,
            training_episodes: original_ids(&fold.training_episodes)?,
            training_windows: original_ids(&fold.training_windows)?,
            holdout_principals: original_ids(&fold.holdout_principals)?,
            holdout_episodes: original_ids(&fold.holdout_episodes)?,
            holdout_windows: original_ids(&fold.holdout_windows)?,
            model_digest: Digest32::from_array(fold.model_digest),
            predictions_digest: Digest32::from_array(fold.predictions_digest),
        })).collect::<Result<Vec<_>, AgentdError>>()?;
        Ok(CellEvaluationRegistrationV1 {
            product: CrossFoldPlanV1 {
                plan_id: StableId::new(&self.plan_id).map_err(deployment_error)?,
                claim_scope: EvaluationClaimScopeV1::Qualification,
                candidate_id: StableId::new(&self.candidate_id).map_err(deployment_error)?,
                baseline_id: StableId::new(&self.baseline_id).map_err(deployment_error)?,
                objective_digest: Digest32::from_array(self.objective_digest),
                dataset_digest: Digest32::from_array(self.dataset_digest),
                estimand_digest: Digest32::from_array(self.estimand_digest),
                metric_contracts: contracts, family_alpha_ppm: self.family_alpha_ppm,
                simultaneous_comparisons: self.simultaneous_comparisons, folds,
                final_holdout_window_id: StableId::new(&self.final_holdout_window_id)
                    .map_err(deployment_error)?,
                final_holdout_digest: Digest32::from_array(self.final_holdout_digest),
            },
            metric_roles: roles, metric_sources: sources,
            comparison: self.comparison.original()?,
        })
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalQualificationContextData {
    pub generator: PrincipalData,
    pub evaluator: PrincipalData,
    pub retention_receipt_digests: Vec<[u8; 32]>,
    pub unlearning_receipt_digest: [u8; 32],
}
impl OriginalQualificationContextData {
    pub(super) fn original(&self) -> Result<ProductQualificationContextV1, AgentdError> {
        Ok(ProductQualificationContextV1 {
            generator: self.generator.original()?,
            evaluator: self.evaluator.original()?,
            retention_receipt_digests: self.retention_receipt_digests.iter()
                .copied().map(Digest32::from_array).collect(),
            unlearning_receipt_digest: Digest32::from_array(self.unlearning_receipt_digest),
        })
    }
}
fn original_ids(data: &[String]) -> Result<Vec<StableId>, AgentdError> {
    data.iter().map(|value| StableId::new(value).map_err(deployment_error)).collect()
}
