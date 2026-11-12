//! Original bounded registration data. The immutable protocol is pinned before
//! Training; realized participants and the candidate receipt come only from the
//! actual Root Training cut. Conversion alone creates no frozen evaluation.

use std::io;

use codex_hepta_intelligence_eval::*;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::CellEvaluationRegistrationV1;

#[path = "authority_host_q24_evaluation_protocol_comparison.rs"]
mod comparison;
#[path = "authority_host_q24_evaluation_protocol_temporal.rs"]
mod temporal;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalBProtocolData {
    schema: u8,
    purpose: String,
    plan_id: String,
    original_estimand: [u8; 32],
    unit_profile: [u8; 32],
    benchmark_input: [u8; 32],
    family_alpha_ppm: u32,
    simultaneous_comparisons: u32,
    metrics: Vec<MetricData>,
    folds: Vec<FoldData>,
    final_holdout_window: String,
    final_holdout_manifest: [u8; 32],
    candidate_temporal: temporal::TemporalData,
    baseline_temporal: temporal::TemporalData,
    comparison: comparison::ComparisonData,
    retention_receipts: Vec<[u8; 32]>,
    unlearning_receipt: [u8; 32],
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct MetricData {
    id: String,
    direction: Direction,
    safety_floor_q32: Option<i64>,
    role: Role,
    source: Source,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum Direction {
    Maximize,
    Minimize,
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum Role {
    PrimarySuperiority { minimum_improvement_q32: i64 },
    NonInferiority { maximum_regression_q32: i64 },
    AbsoluteConstraint,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum Source {
    Ips,
    Snips,
    DoublyRobust,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct FoldData {
    id: String,
    training_principals: Vec<String>,
    training_episodes: Vec<String>,
    training_windows: Vec<String>,
    holdout_principals: Vec<String>,
    holdout_episodes: Vec<String>,
    holdout_windows: Vec<String>,
    original_model: [u8; 32],
    original_predictions: [u8; 32],
}

impl OriginalBProtocolData {
    pub(super) fn decode(bytes: &[u8], expected: Digest32) -> io::Result<Self> {
        if bytes.is_empty() || bytes.len() > 65_536 {
            return Err(io::Error::other("bounded original B protocol required"));
        }
        let value: Self = serde_json::from_slice(bytes).map_err(io::Error::other)?;
        if serde_json::to_vec(&value).map_err(io::Error::other)? != bytes
            || expected.is_zero()
            || expected != Digest32::of_parts(&[b"hepta.root.independent-b.protocol.v1\0", bytes])
            || value.schema != 1
            || value.purpose != "runtime.learning.independent-b-qualification.v1"
            || !(2..=32).contains(&value.folds.len())
            || !(1..=64).contains(&value.metrics.len())
            || value.retention_receipts.is_empty()
            || value.retention_receipts.len() > 64
            || value.retention_receipts.contains(&[0; 32])
            || value.unlearning_receipt == [0; 32]
            || value.unit_profile == [0; 32]
            || value.benchmark_input == [0; 32]
        {
            return Err(io::Error::other(
                "original B protocol pin or bounded fields differ",
            ));
        }
        Ok(value)
    }

    pub(super) fn benchmark_input(&self) -> Digest32 {
        Digest32::from_array(self.benchmark_input)
    }

    pub(super) fn unit_profile(&self) -> Digest32 {
        Digest32::from_array(self.unit_profile)
    }

    pub(super) fn plans(
        &self,
        training: &LearningIterationSnapshotV1,
        work: &crate::cell_composed_q24::OriginalQ24TrainingWorkObservedV1,
    ) -> io::Result<(
        CellEvaluationRegistrationV1,
        TemporalEvaluationPlan,
        TemporalEvaluationPlan,
    )> {
        self.comparison.require_original_training_work(work)?;
        let coordinator = LearningIterationCoordinatorV1::from_snapshot(training.clone())
            .map_err(io::Error::other)?;
        if coordinator.next_stage() != Some(LearningIterationStageV1::Evaluation) {
            return Err(io::Error::other(
                "B requires the exact original Training cut",
            ));
        }
        let candidate = coordinator
            .candidate()
            .ok_or_else(|| io::Error::other("original trained candidate is absent"))?;
        let baseline = &training.request.selected_bundle;
        let lineage = candidate
            .training_lineage
            .as_ref()
            .ok_or_else(|| io::Error::other("original Training lineage is absent"))?;
        let original = training
            .receipts
            .last()
            .ok_or_else(|| io::Error::other("original Training receipt is absent"))?;
        let comparison = self.comparison.realize(
            candidate.artifact_id.clone(),
            baseline.artifact_id.clone(),
            Digest32::of_bytes(
                &learning_iteration_receipt_signing_bytes_v1(original).map_err(io::Error::other)?,
            ),
        );
        let mut metric_contracts = Vec::with_capacity(self.metrics.len());
        let mut metric_roles = Vec::with_capacity(self.metrics.len());
        let mut metric_sources = Vec::with_capacity(self.metrics.len());
        for metric in &self.metrics {
            let metric_id = id(&metric.id)?;
            metric_contracts.push(MetricContractV1 {
                metric_id: metric_id.clone(),
                direction: match metric.direction {
                    Direction::Maximize => EvaluationDirectionV1::Maximize,
                    Direction::Minimize => EvaluationDirectionV1::Minimize,
                },
                safety_floor: metric.safety_floor_q32.map(FixedQ32::from_raw),
            });
            metric_roles.push(MetricRoleContractV2 {
                metric_id: metric_id.clone(),
                role: match metric.role {
                    Role::PrimarySuperiority {
                        minimum_improvement_q32,
                    } => MetricRoleV2::PrimarySuperiority {
                        minimum_improvement: FixedQ32::from_raw(minimum_improvement_q32),
                    },
                    Role::NonInferiority {
                        maximum_regression_q32,
                    } => MetricRoleV2::NonInferiority {
                        maximum_regression: FixedQ32::from_raw(maximum_regression_q32),
                    },
                    Role::AbsoluteConstraint => MetricRoleV2::AbsoluteConstraint,
                },
            });
            metric_sources.push(ProductMetricSourceContractV1 {
                metric_id,
                source: match metric.source {
                    Source::Ips => ProductMetricSourceV1::Ips,
                    Source::Snips => ProductMetricSourceV1::Snips,
                    Source::DoublyRobust => ProductMetricSourceV1::DoublyRobust,
                },
            });
        }
        let product = CrossFoldPlanV1 {
            plan_id: id(&self.plan_id)?,
            claim_scope: EvaluationClaimScopeV1::Qualification,
            candidate_id: candidate.artifact_id.clone(),
            baseline_id: baseline.artifact_id.clone(),
            objective_digest: training.request.envelope.objective_digest,
            dataset_digest: lineage.dataset,
            estimand_digest: Digest32::from_array(self.original_estimand),
            metric_contracts,
            family_alpha_ppm: self.family_alpha_ppm,
            simultaneous_comparisons: self.simultaneous_comparisons,
            folds: self
                .folds
                .iter()
                .map(FoldData::convert)
                .collect::<io::Result<_>>()?,
            final_holdout_window_id: id(&self.final_holdout_window)?,
            final_holdout_digest: Digest32::from_array(self.final_holdout_manifest),
        };
        Ok((
            CellEvaluationRegistrationV1 {
                product,
                metric_roles,
                metric_sources,
                comparison,
            },
            self.candidate_temporal.convert(
                training.request.envelope.objective_digest,
                self.family_alpha_ppm,
                self.simultaneous_comparisons,
            )?,
            self.baseline_temporal.convert(
                training.request.envelope.objective_digest,
                self.family_alpha_ppm,
                self.simultaneous_comparisons,
            )?,
        ))
    }

    pub(super) fn qualification_context(
        &self,
        authorities: &super::admission::OriginalBAuthorities,
    ) -> ProductQualificationContextV1 {
        ProductQualificationContextV1 {
            generator: authorities.generator.principal.clone(),
            evaluator: authorities.evaluator.principal.clone(),
            retention_receipt_digests: self
                .retention_receipts
                .iter()
                .copied()
                .map(Digest32::from_array)
                .collect(),
            unlearning_receipt_digest: Digest32::from_array(self.unlearning_receipt),
        }
    }
}

impl FoldData {
    fn convert(&self) -> io::Result<CrossFoldPartitionV1> {
        Ok(CrossFoldPartitionV1 {
            fold_id: id(&self.id)?,
            training_principals: ids(&self.training_principals)?,
            training_episodes: ids(&self.training_episodes)?,
            training_windows: ids(&self.training_windows)?,
            holdout_principals: ids(&self.holdout_principals)?,
            holdout_episodes: ids(&self.holdout_episodes)?,
            holdout_windows: ids(&self.holdout_windows)?,
            model_digest: Digest32::from_array(self.original_model),
            predictions_digest: Digest32::from_array(self.original_predictions),
        })
    }
}

fn id(value: &str) -> io::Result<StableId> {
    if value.len() > 128 {
        return Err(io::Error::other(
            "bounded original B protocol identity required",
        ));
    }
    StableId::new(value).map_err(io::Error::other)
}

fn ids(values: &[String]) -> io::Result<Vec<StableId>> {
    if values.is_empty() || values.len() > 2_048 {
        return Err(io::Error::other(
            "bounded original B protocol lineage required",
        ));
    }
    values.iter().map(|value| id(value)).collect()
}
