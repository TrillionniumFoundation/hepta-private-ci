//! Actual A -> independent fixture Outcome -> HQ24T002 -> E/D -> native Trainer.
//! Candidate is refused by the unchanged B comparison contract. A separate
//! zero-gradient fit produces original TrainingNoUpdate, never a fake B result.

use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::time::Instant;

use codex_hepta_intelligence_eval::*;
use codex_hepta_learning_artifacts::*;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::fixture;
use super::support;
use crate::CellComparisonContractV1;
use crate::CellCostCoverageV1;
use crate::CellEvaluationErrorV1;
use crate::CellEvaluationJournalsV1;
use crate::CellEvaluationRegistrationV1;
use crate::CellParameterCapacityV1;
use crate::CellQ24TrainingOutcomeV1;
use crate::CellSelectiveUpdateV1;
use crate::CellTrainingBudgetV1;
use crate::CellTrainingObservationV1;
use crate::LoadedCellQ24ModelV1;
use crate::freeze_cell_learning_evaluation_plan_v1;

#[path = "cell_q24_task_training_fixture_tests.rs"]
mod original;
use original::TrainingFixture;

type Journal = CellGenerationJournalV2<FileAnchorWitnessStore>;

fn digest(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}
fn id(label: &str) -> StableId {
    StableId::new(label).expect("bounded component identity")
}

/// Actual native inference and original journal admission/commit/readback.
/// The B experiment has no external action or CURRENT publication authority.
fn run_probe(
    fixture: &TrainingFixture,
    name: &str,
    model: Arc<LoadedCellQ24ModelV1>,
    bundle: &CellCompatibilityBundleV1,
) -> anyhow::Result<(Journal, Vec<u8>)> {
    let definition = support::definition(&model, bundle)?;
    let source = fixture.task.publication.input();
    let published_source = fixture.task.session.retirement.source();
    assert_eq!(&published_source.observation, &source.observation);
    assert_eq!(published_source.objective_digest, source.objective_digest);
    let mut config = support::configuration(
        &model,
        bundle,
        &definition,
        published_source,
        /*generation*/ 1,
    )?;
    config.initial.scope.cell_id = name.to_owned();
    config.initial.scope.run_id = format!("comparison-{name}");
    // Both arms perform this exact public probe. Model identity is separately
    // pinned by each original manifest; this is no feature-use grant.
    config.task_digest = Digest32::of_parts(&[
        b"hepta.component.q24-comparison-probe.v1\0",
        source.objective_digest.as_array(),
        &source.observation,
    ])
    .into_array();
    let clock_origin = Instant::now();
    let clock: Arc<dyn Fn() -> u64 + Send + Sync> = Arc::new(move || {
        10 + u64::try_from(clock_origin.elapsed().as_micros()).expect("bounded probe clock")
    });
    let worker = model.shared_worker(bundle, config.manifest.clone(), Arc::clone(&clock))?;
    let mut journal = CellGenerationJournalV2::open(
        fixture::file(fixture.task.root.path(), &format!("{name}.journal"))?,
        fixture::witness(
            fixture.task.root.path(),
            &format!("{name}.witness"),
            source.objective_digest,
        )?,
        config.clone(),
        /*max_records*/ 64,
    )?;
    let admitted = clock();
    let request = CellGenerationRequestV2 {
        operation_id: format!("{name}-probe"),
        task_digest: config.task_digest,
        source_frontier: config.source_frontier,
        predecessor: journal.snapshot()?.clone(),
        input: source.observation.clone(),
        admitted_at_micros: admitted,
        deadline_micros: admitted + 60_000_000,
    };
    assert!(journal.admit(request.clone(), admitted)?.is_none());
    let proposal = worker.execute(&config.manifest, &request, &AtomicBool::new(/*val*/ false))?;
    assert_eq!(proposal.disposition, CellGenerationDispositionV2::Stopped);
    let receipt = journal.commit(proposal, clock())?;
    assert_eq!(journal.lookup(&request)?, Some(receipt));
    let chunk = journal
        .pending_output()?
        .cloned()
        .expect("actual computed output");
    let output = chunk.bytes.clone();
    assert!(output.starts_with(b"HQ24O001"));
    journal.acknowledge(
        chunk,
        Digest32::of_bytes(&output).into_array(),
        CellTaskCostV2::new(journal.task_cost()?.identity())?,
    )?;
    journal.drain()?;
    assert!(journal.is_drained()?);
    Ok((journal, output))
}

fn temporal(name: &str, objective: Digest32) -> anyhow::Result<TemporalEvaluationPlan> {
    let mut plan = TemporalEvaluationPlan {
        plan_digest: Digest32::ZERO,
        evaluation_id: id(name),
        objective_digest: objective,
        fold: TemporalFoldPlan {
            plan_digest: digest("component-frozen-temporal-fold"),
            fold_id: id(name),
            training_watermark: 10,
            evaluation_start: 20,
            minimum_per_action: 2,
        },
        ope: OpePlan {
            plan_digest: digest("component-frozen-ope"),
            outcome_watermark: 100,
            minimum_rows: 2,
            minimum_ess: FixedQ32::ONE,
            maximum_weight: FixedQ32::from_raw(4_i64 << 32),
        },
        confidence: ClusterConfidencePlan {
            plan_digest: digest("component-frozen-confidence"),
            assumptions_digest: digest("component-independent-holdout-plan"),
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            minimum_clusters: 2,
        },
    };
    plan.plan_digest = plan.canonical_digest()?;
    Ok(plan)
}

fn incomplete_registration(
    fixture: &TrainingFixture,
    candidate: &crate::CellQ24TrainedCandidateV1,
    candidate_journal: &Journal,
    baseline_journal: &Journal,
) -> anyhow::Result<CellEvaluationRegistrationV1> {
    let receipt = fixture
        .training
        .receipts
        .last()
        .expect("actual Generator receipt");
    let metrics = &candidate.metrics;
    // Exact bytes in this fixture have 4 base + 4 encoder + 20 head coefficients.
    // A single selected head row has 2 trainable coefficients.
    let parameter_count = ["base", "encoder", "heads"].into_iter().try_fold(
        0_u64,
        |sum, name| -> anyhow::Result<_> {
            let bytes = std::fs::read(fixture.task.root.path().join(name))?;
            anyhow::ensure!(
                bytes.starts_with(b"HQ24M001") && bytes.len() >= 12,
                "original component matrix"
            );
            Ok(sum + ((bytes.len() - 12) / 8) as u64)
        },
    )?;
    assert_eq!(parameter_count, 28);
    let observation =
        |participant_id, structure, receipt_digest, steps| CellTrainingObservationV1 {
            participant_id,
            capacity: CellParameterCapacityV1 {
                total_parameters: parameter_count,
                trainable_parameters: 2,
                maximum_active_parameters: parameter_count,
            },
            cumulative: CellTrainingBudgetV1 {
                // Known candidate incremental work is not cumulative baseline history.
                // Zero fields deliberately mean an incomplete contract here, never a
                // measured zero or an attested history accepted by B.
                examples_seen: steps,
                optimizer_steps: steps,
                parameter_updates: steps * 2,
                compute_units: 0,
                compute_unit_contract: [0; 32],
            },
            selective_update: CellSelectiveUpdateV1 {
                policy_digest: metrics.update_rule.into_array(),
                eligibility_digest: fixture.dataset.head_digest.into_array(),
                schedule_digest: metrics.optimizer_rule.into_array(),
                maximum_parameters_per_step: 2,
            },
            structure_before: structure,
            structure_after: structure,
            training_receipt_digest: receipt_digest,
        };
    let objective = fixture.training.request.envelope.objective_digest;
    Ok(CellEvaluationRegistrationV1 {
        product: CrossFoldPlanV1 {
            plan_id: id("original-a-candidate-comparison"),
            claim_scope: EvaluationClaimScopeV1::Qualification,
            candidate_id: candidate.bundle.artifact_id.clone(),
            baseline_id: fixture.task.bundle.artifact_id.clone(),
            objective_digest: objective,
            dataset_digest: fixture.dataset.head_digest,
            estimand_digest: digest("component-q24-comparison-estimand"),
            metric_contracts: vec![MetricContractV1 {
                metric_id: id("task-success"),
                direction: EvaluationDirectionV1::Maximize,
                safety_floor: Some(FixedQ32::ZERO),
            }],
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            folds: Vec::new(),
            final_holdout_window_id: id("component-unreleased-holdout"),
            final_holdout_digest: digest("component-unreleased-holdout"),
        },
        metric_roles: vec![MetricRoleContractV2 {
            metric_id: id("task-success"),
            role: MetricRoleV2::PrimarySuperiority {
                minimum_improvement: FixedQ32::ZERO,
            },
        }],
        metric_sources: vec![ProductMetricSourceContractV1 {
            metric_id: id("task-success"),
            source: ProductMetricSourceV1::DoublyRobust,
        }],
        comparison: CellComparisonContractV1 {
            candidate: observation(
                candidate.bundle.artifact_id.clone(),
                candidate_journal.manifest().evolution.structure,
                Digest32::of_bytes(&learning_iteration_receipt_signing_bytes_v1(receipt)?)
                    .into_array(),
                metrics.optimizer_steps,
            ),
            fixed_expert: observation(
                fixture.task.bundle.artifact_id.clone(),
                baseline_journal.manifest().evolution.structure,
                [0; 32],
                /*steps*/ 0,
            ),
            cost_coverage: CellCostCoverageV1::wall_and_cpu(
                digest("required-original-wall-cpu").into_array(),
            ),
        },
    })
}

#[tokio::test]
async fn actual_a_hq2_trainer_cannot_promote_incomplete_incremental_comparison_to_b()
-> anyhow::Result<()> {
    let mut f = TrainingFixture::complete(
        "actual-a-candidate-comparison",
        FixedQ32::from_raw(2_i64 << 32),
    )
    .await?;
    let completed = f.stage.readback(&f.dataset).await?;
    let cap = f.original_readback().await?;
    assert_eq!(
        cap.readback(&f.training, &completed.receipt).await?,
        completed.attestation
    );
    let CellQ24TrainingOutcomeV1::Candidate(candidate) = completed.outcome else {
        anyhow::bail!("actual two-step fit must change these quantized fixture weights");
    };
    assert_eq!(candidate.metrics.optimizer_steps, 2);
    let candidate_model = f.stage.readback(&f.dataset).await?;
    let CellQ24TrainingOutcomeV1::Candidate(actual) = candidate_model.outcome else {
        anyhow::bail!("original native candidate readback changed");
    };
    let (candidate_journal, candidate_output) =
        run_probe(&f, "candidate", Arc::new(actual.model), &candidate.bundle)?;
    let (baseline_journal, baseline_output) =
        run_probe(&f, "baseline", Arc::clone(&f.task.baseline), &f.task.bundle)?;
    assert_ne!(candidate_output, baseline_output);
    for journal in [&candidate_journal, &baseline_journal] {
        let summary = journal.task_cost()?.summary()?;
        assert_eq!(summary.exclusive_entries, 1);
        assert_eq!(summary.wall_work_micros.unknown_entries, 0);
        assert_eq!(summary.cpu_micros.unknown_entries, 1);
        assert_eq!(summary.missing_stages.len(), 11);
        assert!(!summary.missing_stages.contains(&CellCostStageV2::Inference));
    }
    let holdout_path = f.task.root.path().join("unreleased-b-holdout");
    let holdout = LockedFileFinalHoldoutCasStoreV1::create(
        fixture::file(f.task.root.path(), "unreleased-b-holdout")?,
        digest("unreleased-b-holdout"),
    )?;
    let before = std::fs::read(&holdout_path)?;
    let original = f.owner_bytes()?;
    let request = incomplete_registration(&f, &candidate, &candidate_journal, &baseline_journal)?;
    let rejected = freeze_cell_learning_evaluation_plan_v1(
        request,
        CellEvaluationJournalsV1 {
            candidate: &candidate_journal,
            fixed_expert: &baseline_journal,
        },
        &temporal(
            "candidate-probe",
            f.training.request.envelope.objective_digest,
        )?,
        &temporal(
            "baseline-probe",
            f.training.request.envelope.objective_digest,
        )?,
        f.training.request.evaluation_profile,
    );
    assert!(matches!(
        rejected,
        Err(CellEvaluationErrorV1::Binding(
            "matched capacity, cumulative budget or selective updates"
        ))
    ));
    assert_eq!(std::fs::read(holdout_path)?, before);
    assert_eq!(f.owner_bytes()?, original);
    assert_eq!(
        LearningIterationCoordinatorV1::from_snapshot(f.training.clone())?.next_stage(),
        Some(LearningIterationStageV1::Evaluation)
    );
    assert!(f.training.receipts.iter().all(|receipt| !matches!(
        receipt.observation,
        LearningIterationObservationV1::Evaluation { .. }
    )));
    drop(holdout);
    f.task.session.stop().await
}

#[tokio::test]
async fn actual_a_hq2_zero_gradient_retains_parent_with_original_training_no_update()
-> anyhow::Result<()> {
    // Explicit business fixture label is 1. The identity base/encoder and first
    // drive row happen to predict 1 for this input; the independent Observer
    // signs its fixture label before the original Trainer is created.
    let mut f =
        TrainingFixture::complete("actual-a-natural-training-no-update", FixedQ32::ONE).await?;
    let original = f.owner_bytes()?;
    let completed = f.stage.readback(&f.dataset).await?;
    let CellQ24TrainingOutcomeV1::NoUpdate {
        retained_bundle,
        metrics,
    } = &completed.outcome
    else {
        anyhow::bail!("actual zero-gradient SGD must retain the original quantized bytes");
    };
    assert_eq!(*retained_bundle, f.task.bundle.digest()?);
    assert_eq!(metrics.optimizer_steps, 2);
    assert_eq!(metrics.squared_error_before_q48, 0);
    assert_eq!(metrics.squared_error_after_q48, 0);
    assert!(matches!(&completed.receipt.observation,
        LearningIterationObservationV1::TrainingNoUpdateV2(value)
            if value.reason == LearningTrainingNoUpdateReasonV2::QuantizedWeightsUnchanged
                && value.retained_bundle == *retained_bundle && value.steps == 2));
    let cap = f.original_readback().await?;
    assert_eq!(
        cap.readback(&f.training, &completed.receipt).await?,
        completed.attestation
    );
    let replay = f
        .stage
        .execute_training(&f.dataset, Arc::new(AtomicBool::new(/*val*/ false)))
        .await?;
    assert_eq!(replay.receipt, completed.receipt);
    assert_eq!(replay.attestation, completed.attestation);
    assert_eq!(f.owner_bytes()?, original);
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(f.training.clone())?;
    assert_eq!(
        coordinator.next_stage(),
        Some(LearningIterationStageV1::Selection)
    );
    assert_eq!(coordinator.next_task_bundle(), Some(&f.task.bundle));
    let decision =
        crate::cell_q24_publication_driver::validation::Decision::new(f.training.clone())?;
    assert!(!decision.adopts());
    decision.require_root_publication()?;
    // Pure decision validation is no Root enrollment, selection, FinalUse or C.
    assert_eq!(f.training.receipts.len(), 3);
    assert_eq!(f.owner_bytes()?, original);
    f.task.session.stop().await
}
