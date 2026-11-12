//! Preregistered protocol over real earlier business observations and actual
//! label-free forecasts. Future cohort identities/times are plan DATA, never
//! claims that the final business observations have already happened.
#![cfg(test)]

use std::fs::File;
use std::path::Path;
use std::time::Instant;

use codex_hepta_intelligence_eval::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use serde::Serialize;

use super::business;
use super::data::*;
use super::fixed::ArmData;
use super::fixed::FixedControlData;

pub(super) struct OriginalProtocol {
    pub(super) bytes: Vec<u8>,
    pub(super) digest: Digest32,
    pub(super) training_watermark: u64,
    pub(super) evaluation_start: u64,
    pub(super) outcome_watermark: u64,
}

pub(super) fn prepare(
    objective: [u8; 32],
    unit: [u8; 32],
    input: &[u8],
    training: &[TrainingRow],
    cohort: &[CohortRow],
    control: FixedControlData,
    directory: &Path,
    end: Instant,
) -> anyhow::Result<OriginalProtocol> {
    let watermark = training
        .iter()
        .map(|row| row.observed_at_seconds)
        .max()
        .ok_or_else(|| anyhow::anyhow!("actual independent earlier observations required"))?;
    let start = watermark
        .checked_add(1)
        .ok_or_else(|| anyhow::anyhow!("original window overflow"))?;
    let now = business::now()?;
    let remaining = end
        .checked_duration_since(Instant::now())
        .ok_or_else(|| anyhow::anyhow!("original B protocol end elapsed"))?
        .as_secs();
    anyhow::ensure!(
        remaining >= 10 && watermark <= now,
        "original B observation window absent"
    );
    let outcome_watermark = now
        .checked_add(remaining)
        .ok_or_else(|| anyhow::anyhow!("original cutoff overflow"))?;
    let temporal = TemporalData::new(objective, watermark, start, outcome_watermark)?;
    let first = forecast(
        "ordinary-b-calibration-fold",
        "ordinary-b-calibration-window",
        &(0..16)
            .map(|index| CohortRow {
                decision: format!("ordinary-b-calibration-{index}"),
                principal: format!("ordinary-b-calibration-principal-{index}"),
                episode: format!("ordinary-b-calibration-episode-{index}"),
                window: "ordinary-b-calibration-window".into(),
                cluster: format!("ordinary-b-calibration-cluster-{index}"),
            })
            .collect::<Vec<_>>(),
        training,
        &temporal,
        directory,
    )?;
    let final_fold = forecast(
        "ordinary-b-final-fold",
        FINAL_WINDOW,
        cohort,
        training,
        &temporal,
        directory,
    )?;
    let training_bytes = serde_json::to_vec(training)?;
    business::write_once(
        &directory.join("original-retained-training.data"),
        &training_bytes,
    )?;
    let retained = directory.join("original-retained-training.data");
    anyhow::ensure!(
        std::fs::read(&retained)? == training_bytes && std::fs::read(&retained)? == training_bytes,
        "actual independent training retention readback"
    );
    let retention = serde_json::to_vec(&(
        "original-b-single-object-retention-v1",
        Digest32::of_bytes(&training_bytes).into_array(),
        training_bytes.len(),
        business::now()?,
    ))?;
    business::write_once(
        &directory.join("original-retention-observation.data"),
        &retention,
    )?;
    // This evidence is narrowly the removal of this original, independently
    // owned calibration object. It claims no model-wide forgetting result.
    let removable = directory.join("original-unlearning-object.data");
    let removed_bytes = b"original-independent-b-calibration-object-to-remove-v1";
    business::write_once(&removable, removed_bytes)?;
    anyhow::ensure!(
        std::fs::read(&removable)? == removed_bytes,
        "actual removal predecessor"
    );
    std::fs::remove_file(&removable)?;
    File::open(directory)?.sync_all()?;
    for _ in 0..2 {
        match std::fs::symlink_metadata(&removable) {
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            _ => anyhow::bail!("original independent calibration object was not removed"),
        }
    }
    let unlearning = serde_json::to_vec(&(
        "original-b-single-object-removal-v1",
        Digest32::of_bytes(removed_bytes).into_array(),
        business::now()?,
    ))?;
    business::write_once(
        &directory.join("original-removal-observation.data"),
        &unlearning,
    )?;
    let meter = crate::cell_composed_q24::original_q24_benchmark_meter_contract().into_array();
    let protocol = ProtocolData {
        schema: 1,
        purpose: "runtime.learning.independent-b-qualification.v1",
        plan_id: "ordinary-independent-b-original-evaluate",
        original_estimand: Digest32::of_parts(&[
            b"original-independent-b-contract-satisfaction-estimand-v1\0",
            &unit,
        ])
        .into_array(),
        unit_profile: unit,
        benchmark_input: Digest32::of_bytes(input).into_array(),
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 1,
        metrics: vec![MetricData {
            id: "ordinary-original-business-ips",
            direction: "maximize",
            safety_floor_q32: Some(0),
            role: MetricRole::PrimarySuperiority {
                minimum_improvement_q32: 0,
            },
            source: "ips",
        }],
        folds: vec![first, final_fold],
        final_holdout_window: FINAL_WINDOW,
        final_holdout_manifest: cohort_digest(objective, unit, cohort)?.into_array(),
        candidate_temporal: temporal.clone(),
        baseline_temporal: temporal,
        comparison: ComparisonData {
            candidate: control.arm.clone(),
            fixed_expert: control.arm,
            fixed_training_receipt: control.receipt,
            metering_contract: meter,
            required_metrics: vec!["wall", "cpu"],
        },
        retention_receipts: vec![Digest32::of_bytes(&retention).into_array()],
        unlearning_receipt: Digest32::of_bytes(&unlearning).into_array(),
    };
    let bytes = serde_json::to_vec(&protocol)?;
    anyhow::ensure!(
        bytes.len() <= 65_536 && Instant::now() < end,
        "original protocol bound/end"
    );
    let digest = Digest32::of_parts(&[b"hepta.root.independent-b.protocol.v1\0", &bytes]);
    business::write_once(
        &directory.join("original-preregistered-protocol.json"),
        &bytes,
    )?;
    Ok(OriginalProtocol {
        bytes,
        digest,
        training_watermark: watermark,
        evaluation_start: start,
        outcome_watermark,
    })
}

fn forecast(
    id: &str,
    window: &str,
    cohort: &[CohortRow],
    training: &[TrainingRow],
    temporal: &TemporalData,
    directory: &Path,
) -> anyhow::Result<FoldData> {
    let samples = training
        .iter()
        .map(|row| {
            Ok(OutcomeTrainingSample {
                decision_id: StableId::new(&row.decision_id)?,
                principal_lineage: StableId::new(&row.principal_lineage)?,
                episode_lineage: StableId::new(&row.episode_lineage)?,
                window_id: StableId::new(&row.window_id)?,
                action_id: StableId::new(&row.action_id)?,
                outcome: FixedQ32::from_raw(row.outcome_q32),
                observed_at: row.observed_at_seconds,
                evidence_digest: Digest32::from_array(row.original_evidence),
            })
        })
        .collect::<anyhow::Result<Vec<_>>>()?;
    let targets = cohort
        .iter()
        .map(|row| {
            Ok(HeldOutTarget {
                decision_id: StableId::new(&row.decision)?,
                principal_lineage: StableId::new(&row.principal)?,
                episode_lineage: StableId::new(&row.episode)?,
                window_id: StableId::new(window)?,
                decision_at: temporal.evaluation_start,
                actions: ACTIONS
                    .into_iter()
                    .map(StableId::new)
                    .collect::<Result<_, _>>()?,
            })
        })
        .collect::<anyhow::Result<Vec<_>>>()?;
    let plan = TemporalFoldPlan {
        plan_digest: Digest32::of_parts(&[
            b"original-label-free-forecast-v1\0",
            id.as_bytes(),
            &temporal.training_watermark.to_le_bytes(),
            &temporal.evaluation_start.to_le_bytes(),
        ]),
        fold_id: StableId::new(id)?,
        training_watermark: temporal.training_watermark,
        evaluation_start: temporal.evaluation_start,
        minimum_per_action: 8,
    };
    let fitted = fit_temporal_fold(&plan, &samples, &targets)?;
    anyhow::ensure!(
        !fitted.authority.grants_any(),
        "forecast data must grant no authority"
    );
    let predictions: Vec<_> = fitted
        .predictions
        .iter()
        .map(|row| {
            (
                row.decision_id.as_str(),
                row.outcomes
                    .iter()
                    .map(|(action, outcome)| (action.as_str(), outcome.raw()))
                    .collect::<Vec<_>>(),
            )
        })
        .collect();
    let bytes = serde_json::to_vec(&(
        "actual-earlier-training-label-free-forecast-v1",
        plan.plan_digest.into_array(),
        fitted.model_digest.into_array(),
        fitted.predictions_digest.into_array(),
        predictions,
    ))?;
    business::write_once(&directory.join(format!("{id}.forecast")), &bytes)?;
    Ok(FoldData {
        id: id.into(),
        training_principals: training
            .iter()
            .map(|row| row.principal_lineage.clone())
            .collect(),
        training_episodes: training
            .iter()
            .map(|row| row.episode_lineage.clone())
            .collect(),
        training_windows: vec![TRAIN_WINDOW.into()],
        holdout_principals: cohort.iter().map(|row| row.principal.clone()).collect(),
        holdout_episodes: cohort.iter().map(|row| row.episode.clone()).collect(),
        holdout_windows: vec![window.into()],
        original_model: fitted.model_digest.into_array(),
        original_predictions: fitted.predictions_digest.into_array(),
    })
}

#[derive(Serialize)]
struct ProtocolData {
    schema: u8,
    purpose: &'static str,
    plan_id: &'static str,
    original_estimand: [u8; 32],
    unit_profile: [u8; 32],
    benchmark_input: [u8; 32],
    family_alpha_ppm: u32,
    simultaneous_comparisons: u32,
    metrics: Vec<MetricData>,
    folds: Vec<FoldData>,
    final_holdout_window: &'static str,
    final_holdout_manifest: [u8; 32],
    candidate_temporal: TemporalData,
    baseline_temporal: TemporalData,
    comparison: ComparisonData,
    retention_receipts: Vec<[u8; 32]>,
    unlearning_receipt: [u8; 32],
}
#[derive(Serialize)]
struct MetricData {
    id: &'static str,
    direction: &'static str,
    safety_floor_q32: Option<i64>,
    role: MetricRole,
    source: &'static str,
}
#[derive(Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum MetricRole {
    PrimarySuperiority { minimum_improvement_q32: i64 },
}
#[derive(Serialize)]
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
#[derive(Serialize)]
struct ComparisonData {
    candidate: ArmData,
    fixed_expert: ArmData,
    fixed_training_receipt: [u8; 32],
    metering_contract: [u8; 32],
    required_metrics: Vec<&'static str>,
}
#[derive(Clone, Serialize)]
struct TemporalData {
    plan_digest: [u8; 32],
    evaluation_id: &'static str,
    fold_id: &'static str,
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
    fn new(
        objective: [u8; 32],
        training_watermark: u64,
        evaluation_start: u64,
        outcome_watermark: u64,
    ) -> anyhow::Result<Self> {
        let mut plan = TemporalEvaluationPlan {
            plan_digest: Digest32::ZERO,
            evaluation_id: StableId::new("ordinary-b-original-temporal-comparison")?,
            objective_digest: Digest32::from_array(objective),
            fold: TemporalFoldPlan {
                plan_digest: Digest32::of_bytes(b"original-b-tabular-training-means-only-v1"),
                fold_id: StableId::new("ordinary-b-final-fold")?,
                training_watermark,
                evaluation_start,
                minimum_per_action: 8,
            },
            ope: OpePlan {
                plan_digest: Digest32::of_bytes(b"original-b-fair-binary-behavior-ips-v1"),
                outcome_watermark,
                minimum_rows: ROWS,
                minimum_ess: FixedQ32::from_raw(64 * ONE),
                maximum_weight: FixedQ32::from_raw(2 * ONE),
            },
            confidence: ClusterConfidencePlan {
                plan_digest: Digest32::of_bytes(b"original-b-independent-request-clusters-v1"),
                assumptions_digest: Digest32::of_bytes(
                    concat!(
                        "original-b-independent-episode-files;",
                        "fair-independent-behavior-bits;binary-contract-unit-v1"
                    )
                    .as_bytes(),
                ),
                family_alpha_ppm: 50_000,
                simultaneous_comparisons: 1,
                minimum_clusters: 32,
            },
        };
        plan.plan_digest = plan.canonical_digest()?;
        Ok(Self {
            plan_digest: plan.plan_digest.into_array(),
            evaluation_id: "ordinary-b-original-temporal-comparison",
            fold_id: "ordinary-b-final-fold",
            fold_plan: plan.fold.plan_digest.into_array(),
            training_watermark,
            evaluation_start,
            minimum_per_action: 8,
            ope_plan: plan.ope.plan_digest.into_array(),
            outcome_watermark,
            minimum_rows: ROWS,
            minimum_ess_q32: 64 * ONE,
            maximum_weight_q32: 2 * ONE,
            confidence_plan: plan.confidence.plan_digest.into_array(),
            confidence_assumptions: plan.confidence.assumptions_digest.into_array(),
            minimum_clusters: 32,
        })
    }
}
