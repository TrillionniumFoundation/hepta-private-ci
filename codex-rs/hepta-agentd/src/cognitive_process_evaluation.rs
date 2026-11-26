//! Bounded process input mapping. Raw fields are not verified capabilities.

use super::cognitive_process_evidence::*;
use super::cognitive_process_wire::*;
use serde::Deserialize;
use serde::Serialize;

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct EvaluationIntervalV1Raw {
    pub lower: Fixed,
    pub upper: Fixed,
}

impl From<EvaluationIntervalV1Raw> for codex_hepta_intelligence_eval::EvaluationIntervalV1 {
    fn from(raw: EvaluationIntervalV1Raw) -> Self {
        Self {
            lower: raw.lower.into(),
            upper: raw.upper.into(),
        }
    }
}

impl From<codex_hepta_intelligence_eval::EvaluationIntervalV1> for EvaluationIntervalV1Raw {
    fn from(raw: codex_hepta_intelligence_eval::EvaluationIntervalV1) -> Self {
        Self {
            lower: raw.lower.into(),
            upper: raw.upper.into(),
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct MetricGateV1Raw {
    pub metric_id: Id,
    pub direction: EvaluationDirectionV1Raw,
    pub candidate: EvaluationIntervalV1Raw,
    pub baseline: EvaluationIntervalV1Raw,
    pub safety_floor: Option<Fixed>,
    pub support_digest: Digest,
}

impl From<MetricGateV1Raw> for codex_hepta_intelligence_eval::MetricGateV1 {
    fn from(raw: MetricGateV1Raw) -> Self {
        Self {
            metric_id: raw.metric_id.into(),
            direction: raw.direction.into(),
            candidate: raw.candidate.into(),
            baseline: raw.baseline.into(),
            safety_floor: raw.safety_floor.map(std::convert::Into::into),
            support_digest: raw.support_digest.into(),
        }
    }
}

impl From<codex_hepta_intelligence_eval::MetricGateV1> for MetricGateV1Raw {
    fn from(raw: codex_hepta_intelligence_eval::MetricGateV1) -> Self {
        Self {
            metric_id: raw.metric_id.into(),
            direction: raw.direction.into(),
            candidate: raw.candidate.into(),
            baseline: raw.baseline.into(),
            safety_floor: raw.safety_floor.map(std::convert::Into::into),
            support_digest: raw.support_digest.into(),
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct MetricContractV1Raw {
    pub metric_id: Id,
    pub direction: EvaluationDirectionV1Raw,
    pub safety_floor: Option<Fixed>,
}

impl From<MetricContractV1Raw> for codex_hepta_intelligence_eval::MetricContractV1 {
    fn from(raw: MetricContractV1Raw) -> Self {
        Self {
            metric_id: raw.metric_id.into(),
            direction: raw.direction.into(),
            safety_floor: raw.safety_floor.map(std::convert::Into::into),
        }
    }
}

impl From<codex_hepta_intelligence_eval::MetricContractV1> for MetricContractV1Raw {
    fn from(raw: codex_hepta_intelligence_eval::MetricContractV1) -> Self {
        Self {
            metric_id: raw.metric_id.into(),
            direction: raw.direction.into(),
            safety_floor: raw.safety_floor.map(std::convert::Into::into),
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct CrossFoldPartitionV1Raw {
    pub fold_id: Id,
    pub training_principals: Vec<Id>,
    pub training_episodes: Vec<Id>,
    pub training_windows: Vec<Id>,
    pub holdout_principals: Vec<Id>,
    pub holdout_episodes: Vec<Id>,
    pub holdout_windows: Vec<Id>,
    pub model_digest: Digest,
    pub predictions_digest: Digest,
}

impl From<CrossFoldPartitionV1Raw> for codex_hepta_intelligence_eval::CrossFoldPartitionV1 {
    fn from(raw: CrossFoldPartitionV1Raw) -> Self {
        Self {
            fold_id: raw.fold_id.into(),
            training_principals: raw
                .training_principals
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            training_episodes: raw
                .training_episodes
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            training_windows: raw
                .training_windows
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            holdout_principals: raw
                .holdout_principals
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            holdout_episodes: raw
                .holdout_episodes
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            holdout_windows: raw
                .holdout_windows
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            model_digest: raw.model_digest.into(),
            predictions_digest: raw.predictions_digest.into(),
        }
    }
}

impl From<codex_hepta_intelligence_eval::CrossFoldPartitionV1> for CrossFoldPartitionV1Raw {
    fn from(raw: codex_hepta_intelligence_eval::CrossFoldPartitionV1) -> Self {
        Self {
            fold_id: raw.fold_id.into(),
            training_principals: raw
                .training_principals
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            training_episodes: raw
                .training_episodes
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            training_windows: raw
                .training_windows
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            holdout_principals: raw
                .holdout_principals
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            holdout_episodes: raw
                .holdout_episodes
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            holdout_windows: raw
                .holdout_windows
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            model_digest: raw.model_digest.into(),
            predictions_digest: raw.predictions_digest.into(),
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct CrossFoldPlanV1Raw {
    pub plan_id: Id,
    pub claim_scope: EvaluationClaimScopeV1Raw,
    pub candidate_id: Id,
    pub baseline_id: Id,
    pub objective_digest: Digest,
    pub dataset_digest: Digest,
    pub estimand_digest: Digest,
    pub metric_contracts: Vec<MetricContractV1Raw>,
    pub family_alpha_ppm: u32,
    pub simultaneous_comparisons: u32,
    pub folds: Vec<CrossFoldPartitionV1Raw>,
    pub final_holdout_window_id: Id,
    pub final_holdout_digest: Digest,
}

impl From<CrossFoldPlanV1Raw> for codex_hepta_intelligence_eval::CrossFoldPlanV1 {
    fn from(raw: CrossFoldPlanV1Raw) -> Self {
        Self {
            plan_id: raw.plan_id.into(),
            claim_scope: raw.claim_scope.into(),
            candidate_id: raw.candidate_id.into(),
            baseline_id: raw.baseline_id.into(),
            objective_digest: raw.objective_digest.into(),
            dataset_digest: raw.dataset_digest.into(),
            estimand_digest: raw.estimand_digest.into(),
            metric_contracts: raw
                .metric_contracts
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            family_alpha_ppm: raw.family_alpha_ppm,
            simultaneous_comparisons: raw.simultaneous_comparisons,
            folds: raw
                .folds
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            final_holdout_window_id: raw.final_holdout_window_id.into(),
            final_holdout_digest: raw.final_holdout_digest.into(),
        }
    }
}

impl From<codex_hepta_intelligence_eval::CrossFoldPlanV1> for CrossFoldPlanV1Raw {
    fn from(raw: codex_hepta_intelligence_eval::CrossFoldPlanV1) -> Self {
        Self {
            plan_id: raw.plan_id.into(),
            claim_scope: raw.claim_scope.into(),
            candidate_id: raw.candidate_id.into(),
            baseline_id: raw.baseline_id.into(),
            objective_digest: raw.objective_digest.into(),
            dataset_digest: raw.dataset_digest.into(),
            estimand_digest: raw.estimand_digest.into(),
            metric_contracts: raw
                .metric_contracts
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            family_alpha_ppm: raw.family_alpha_ppm,
            simultaneous_comparisons: raw.simultaneous_comparisons,
            folds: raw
                .folds
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            final_holdout_window_id: raw.final_holdout_window_id.into(),
            final_holdout_digest: raw.final_holdout_digest.into(),
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct IndependentEvaluationBundleV1Raw {
    pub evaluation_id: Id,
    pub candidate_id: Id,
    pub baseline_id: Id,
    pub claim_scope: EvaluationClaimScopeV1Raw,
    pub generator: AuthenticatedPrincipalV1Raw,
    pub evaluator: AuthenticatedPrincipalV1Raw,
    pub objective_digest: Digest,
    pub dataset_digest: Digest,
    pub estimand_digest: Digest,
    pub estimate_receipt_digest: Digest,
    pub support_audit_digest: Digest,
    pub confidence_receipt_digest: Digest,
    pub retention_receipt_digests: Vec<Digest>,
    pub unlearning_receipt_digest: Digest,
    pub snapshot_ids: Vec<Id>,
    pub future_window_ids: Vec<Id>,
    pub family_alpha_ppm: u32,
    pub simultaneous_comparisons: u32,
    pub metrics: Vec<MetricGateV1Raw>,
}

impl From<codex_hepta_intelligence_eval::IndependentEvaluationBundleV1>
    for IndependentEvaluationBundleV1Raw
{
    fn from(raw: codex_hepta_intelligence_eval::IndependentEvaluationBundleV1) -> Self {
        Self {
            evaluation_id: raw.evaluation_id.into(),
            candidate_id: raw.candidate_id.into(),
            baseline_id: raw.baseline_id.into(),
            claim_scope: raw.claim_scope.into(),
            generator: raw.generator.into(),
            evaluator: raw.evaluator.into(),
            objective_digest: raw.objective_digest.into(),
            dataset_digest: raw.dataset_digest.into(),
            estimand_digest: raw.estimand_digest.into(),
            estimate_receipt_digest: raw.estimate_receipt_digest.into(),
            support_audit_digest: raw.support_audit_digest.into(),
            confidence_receipt_digest: raw.confidence_receipt_digest.into(),
            retention_receipt_digests: raw
                .retention_receipt_digests
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            unlearning_receipt_digest: raw.unlearning_receipt_digest.into(),
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
            family_alpha_ppm: raw.family_alpha_ppm,
            simultaneous_comparisons: raw.simultaneous_comparisons,
            metrics: raw
                .metrics
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct MetricRoleContractV2Raw {
    pub metric_id: Id,
    pub role: MetricRoleV2Raw,
}

impl From<MetricRoleContractV2Raw> for codex_hepta_intelligence_eval::MetricRoleContractV2 {
    fn from(raw: MetricRoleContractV2Raw) -> Self {
        Self {
            metric_id: raw.metric_id.into(),
            role: raw.role.into(),
        }
    }
}

impl From<codex_hepta_intelligence_eval::MetricRoleContractV2> for MetricRoleContractV2Raw {
    fn from(raw: codex_hepta_intelligence_eval::MetricRoleContractV2) -> Self {
        Self {
            metric_id: raw.metric_id.into(),
            role: raw.role.into(),
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ObservedFutureWindowV1Raw {
    pub window_id: Id,
    pub snapshot_id: Id,
    pub starts_unix_micros: u64,
    pub ends_unix_micros: u64,
    pub observation_count: u64,
    pub observed_source_cut: Digest,
}

impl From<ObservedFutureWindowV1Raw> for codex_hepta_intelligence_eval::ObservedFutureWindowV1 {
    fn from(raw: ObservedFutureWindowV1Raw) -> Self {
        Self {
            window_id: raw.window_id.into(),
            snapshot_id: raw.snapshot_id.into(),
            starts_unix_micros: raw.starts_unix_micros,
            ends_unix_micros: raw.ends_unix_micros,
            observation_count: raw.observation_count,
            observed_source_cut: raw.observed_source_cut.into(),
        }
    }
}

impl From<codex_hepta_intelligence_eval::ObservedFutureWindowV1> for ObservedFutureWindowV1Raw {
    fn from(raw: codex_hepta_intelligence_eval::ObservedFutureWindowV1) -> Self {
        Self {
            window_id: raw.window_id.into(),
            snapshot_id: raw.snapshot_id.into(),
            starts_unix_micros: raw.starts_unix_micros,
            ends_unix_micros: raw.ends_unix_micros,
            observation_count: raw.observation_count,
            observed_source_cut: raw.observed_source_cut.into(),
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct LongitudinalTimeEvidenceV1Raw {
    pub frozen_unix_micros: u64,
    pub windows: Vec<ObservedFutureWindowV1Raw>,
    pub observer: SignedLearningEvidenceV1Raw,
}

impl From<LongitudinalTimeEvidenceV1Raw>
    for codex_hepta_intelligence_eval::LongitudinalTimeEvidenceV1
{
    fn from(raw: LongitudinalTimeEvidenceV1Raw) -> Self {
        Self {
            frozen_unix_micros: raw.frozen_unix_micros,
            windows: raw
                .windows
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            observer: raw.observer.into(),
        }
    }
}

impl From<codex_hepta_intelligence_eval::LongitudinalTimeEvidenceV1>
    for LongitudinalTimeEvidenceV1Raw
{
    fn from(raw: codex_hepta_intelligence_eval::LongitudinalTimeEvidenceV1) -> Self {
        Self {
            frozen_unix_micros: raw.frozen_unix_micros,
            windows: raw
                .windows
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            observer: raw.observer.into(),
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct SignedEvaluationEvidenceV1Raw {
    pub generator_plan: SignedLearningEvidenceV1Raw,
    pub evaluator_bundle: SignedLearningEvidenceV1Raw,
}

impl From<SignedEvaluationEvidenceV1Raw>
    for codex_hepta_intelligence_eval::SignedEvaluationEvidenceV1
{
    fn from(raw: SignedEvaluationEvidenceV1Raw) -> Self {
        Self {
            generator_plan: raw.generator_plan.into(),
            evaluator_bundle: raw.evaluator_bundle.into(),
        }
    }
}

impl From<codex_hepta_intelligence_eval::SignedEvaluationEvidenceV1>
    for SignedEvaluationEvidenceV1Raw
{
    fn from(raw: codex_hepta_intelligence_eval::SignedEvaluationEvidenceV1) -> Self {
        Self {
            generator_plan: raw.generator_plan.into(),
            evaluator_bundle: raw.evaluator_bundle.into(),
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct SelfEvolutionSelectionPolicyV1Raw {
    pub no_change_baseline_id: Id,
    pub no_change_baseline_digest: Digest,
    pub minimum_dataset_records: u32,
    pub minimum_future_window_micros: u64,
}

impl From<SelfEvolutionSelectionPolicyV1Raw>
    for codex_hepta_intelligence_eval::SelfEvolutionSelectionPolicyV1
{
    fn from(raw: SelfEvolutionSelectionPolicyV1Raw) -> Self {
        Self {
            no_change_baseline_id: raw.no_change_baseline_id.into(),
            no_change_baseline_digest: raw.no_change_baseline_digest.into(),
            minimum_dataset_records: raw.minimum_dataset_records,
            minimum_future_window_micros: raw.minimum_future_window_micros,
        }
    }
}

impl From<codex_hepta_intelligence_eval::SelfEvolutionSelectionPolicyV1>
    for SelfEvolutionSelectionPolicyV1Raw
{
    fn from(raw: codex_hepta_intelligence_eval::SelfEvolutionSelectionPolicyV1) -> Self {
        Self {
            no_change_baseline_id: raw.no_change_baseline_id.into(),
            no_change_baseline_digest: raw.no_change_baseline_digest.into(),
            minimum_dataset_records: raw.minimum_dataset_records,
            minimum_future_window_micros: raw.minimum_future_window_micros,
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct SelfEvolutionSelectionRequestV1Raw {
    pub selection_id: Id,
    pub predecessor_id: Id,
    pub predecessor_generation: GenerationWire,
    pub predecessor_artifact_digest: Digest,
    pub candidate_id: Id,
    pub candidate_generation: GenerationWire,
    pub candidate_artifact_digest: Digest,
}

impl From<SelfEvolutionSelectionRequestV1Raw>
    for codex_hepta_intelligence_eval::SelfEvolutionSelectionRequestV1
{
    fn from(raw: SelfEvolutionSelectionRequestV1Raw) -> Self {
        Self {
            selection_id: raw.selection_id.into(),
            predecessor_id: raw.predecessor_id.into(),
            predecessor_generation: raw.predecessor_generation.into(),
            predecessor_artifact_digest: raw.predecessor_artifact_digest.into(),
            candidate_id: raw.candidate_id.into(),
            candidate_generation: raw.candidate_generation.into(),
            candidate_artifact_digest: raw.candidate_artifact_digest.into(),
        }
    }
}

impl From<codex_hepta_intelligence_eval::SelfEvolutionSelectionRequestV1>
    for SelfEvolutionSelectionRequestV1Raw
{
    fn from(raw: codex_hepta_intelligence_eval::SelfEvolutionSelectionRequestV1) -> Self {
        Self {
            selection_id: raw.selection_id.into(),
            predecessor_id: raw.predecessor_id.into(),
            predecessor_generation: raw.predecessor_generation.into(),
            predecessor_artifact_digest: raw.predecessor_artifact_digest.into(),
            candidate_id: raw.candidate_id.into(),
            candidate_generation: raw.candidate_generation.into(),
            candidate_artifact_digest: raw.candidate_artifact_digest.into(),
        }
    }
}
