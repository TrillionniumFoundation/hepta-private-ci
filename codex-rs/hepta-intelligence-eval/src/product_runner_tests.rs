use super::*;

use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::CrossFoldPartitionV1;
use crate::CrossFoldPlanV1;
use crate::EvaluationDirectionV1;
use crate::HoldoutUseDispositionV1;
use crate::MetricContractV1;
use crate::OpeAction;
use crate::OpePlan;
use crate::ClusterConfidencePlan;
use crate::TemporalFoldPlan;
use crate::freeze_cross_fold_plan;

static NEXT_FILE: AtomicU64 = AtomicU64::new(0);

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

#[derive(Default)]
struct MemoryAnchorStore {
    binding: Option<Digest32>,
    anchor: Option<HoldoutAnchorV1>,
    fail_next_commit: bool,
}

impl HoldoutAnchorStoreV1 for MemoryAnchorStore {
    fn initialize(
        &mut self,
        binding: Digest32,
        initial: HoldoutAnchorV1,
    ) -> Result<(), HoldoutAnchorStoreError> {
        if self.binding.is_some() || self.anchor.is_some() {
            return Err(HoldoutAnchorStoreError::Conflict);
        }
        self.binding = Some(binding);
        self.anchor = Some(initial);
        Ok(())
    }

    fn load(&mut self, binding: Digest32) -> Result<HoldoutAnchorV1, HoldoutAnchorStoreError> {
        if self.binding != Some(binding) {
            return Err(if self.binding.is_none() {
                HoldoutAnchorStoreError::Missing
            } else {
                HoldoutAnchorStoreError::Conflict
            });
        }
        self.anchor.ok_or(HoldoutAnchorStoreError::Missing)
    }

    fn compare_and_swap(
        &mut self,
        binding: Digest32,
        expected: HoldoutAnchorV1,
        next: HoldoutAnchorV1,
    ) -> Result<(), HoldoutAnchorStoreError> {
        if self.fail_next_commit {
            self.fail_next_commit = false;
            return Err(HoldoutAnchorStoreError::Indeterminate);
        }
        if self.binding != Some(binding) || self.anchor != Some(expected) {
            return Err(HoldoutAnchorStoreError::Conflict);
        }
        self.anchor = Some(next);
        Ok(())
    }
}

struct Fixture {
    frozen: CrossFoldPlanReceiptV1,
    temporal: TemporalEvaluationPlan,
    training: Vec<OutcomeTrainingSample>,
    targets: Vec<HeldOutTarget>,
    observations: Vec<OpeRow>,
    assignments: Vec<ClusterAssignment>,
}

fn fixture() -> Fixture {
    let objective = digest("objective");
    let holdout = digest("authenticated-final-holdout-manifest");
    let frozen = freeze_cross_fold_plan(CrossFoldPlanV1 {
        plan_id: id("product-plan"),
        claim_scope: EvaluationClaimScopeV1::Qualification,
        candidate_id: id("candidate"),
        baseline_id: id("baseline"),
        objective_digest: objective,
        dataset_digest: digest("dataset"),
        estimand_digest: digest("estimand"),
        metric_contracts: vec![MetricContractV1 {
            metric_id: id("task-success"),
            direction: EvaluationDirectionV1::Maximize,
            safety_floor: None,
        }],
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 1,
        folds: vec![
            CrossFoldPartitionV1 {
                fold_id: id("fold-a"),
                training_principals: vec![id("train-principal-a")],
                training_episodes: vec![id("train-episode-a")],
                training_windows: vec![id("past-window-a")],
                holdout_principals: vec![id("holdout-principal-a")],
                holdout_episodes: vec![id("holdout-episode-a")],
                holdout_windows: vec![id("future-window")],
                model_digest: digest("fold-a-model"),
                predictions_digest: digest("fold-a-predictions"),
            },
            CrossFoldPartitionV1 {
                fold_id: id("fold-b"),
                training_principals: vec![id("train-principal-b")],
                training_episodes: vec![id("train-episode-b")],
                training_windows: vec![id("past-window-b")],
                holdout_principals: vec![id("holdout-principal-b")],
                holdout_episodes: vec![id("holdout-episode-b")],
                holdout_windows: vec![id("other-window")],
                model_digest: digest("fold-b-model"),
                predictions_digest: digest("fold-b-predictions"),
            },
        ],
        final_holdout_window_id: id("future-window"),
        final_holdout_digest: holdout,
    })
    .unwrap();

    let mut temporal = TemporalEvaluationPlan {
        plan_digest: Digest32::ZERO,
        evaluation_id: id("product-evaluation"),
        objective_digest: objective,
        fold: TemporalFoldPlan {
            plan_digest: digest("temporal-fold-plan"),
            fold_id: id("temporal-fold"),
            training_watermark: 10,
            evaluation_start: 20,
            minimum_per_action: 2,
        },
        ope: OpePlan {
            plan_digest: digest("ope-plan"),
            outcome_watermark: 100,
            minimum_rows: 2,
            minimum_ess: FixedQ32::ONE,
            maximum_weight: FixedQ32::from_raw(2 << 32),
        },
        confidence: ClusterConfidencePlan {
            plan_digest: digest("confidence-plan"),
            assumptions_digest: digest("independent-clusters"),
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            minimum_clusters: 2,
        },
    };
    temporal.plan_digest = temporal.canonical_digest().unwrap();

    let mut training = Vec::new();
    for action in ["a", "b"] {
        for (index, outcome) in [FixedQ32::ZERO, FixedQ32::ONE].into_iter().enumerate() {
            training.push(OutcomeTrainingSample {
                decision_id: id(&format!("training-{action}-{index}")),
                principal_lineage: id("training-principal"),
                episode_lineage: id("training-episode"),
                window_id: id("past-window"),
                action_id: id(action),
                outcome,
                observed_at: 5,
                evidence_digest: digest("training-outcome"),
            });
        }
    }

    let mut targets = Vec::new();
    let mut observations = Vec::new();
    let mut assignments = Vec::new();
    for index in 0..128 {
        let decision_id = id(&format!("decision-{index}"));
        targets.push(HeldOutTarget {
            decision_id: decision_id.clone(),
            principal_lineage: id(&format!("principal-{index}")),
            episode_lineage: id(&format!("episode-{index}")),
            window_id: id("future-window"),
            decision_at: 20,
            actions: vec![id("a"), id("b")],
        });
        observations.push(OpeRow {
            decision_id: decision_id.clone(),
            chosen_action: id("a"),
            complete_candidates: true,
            actions: [("a", 3), ("b", 1)]
                .into_iter()
                .map(|(action, quarters)| OpeAction {
                    action_id: id(action),
                    behavior_probability: ProbabilityQ32::from_raw(quarters << 30).unwrap(),
                    evaluation_probability: ProbabilityQ32::from_raw(1 << 31).unwrap(),
                    predicted_outcome: FixedQ32::ZERO,
                })
                .collect(),
            finalized_outcome: Some(FixedQ32::from_raw(1 << 31)),
            outcome_observed_at: 50,
            outcome_evidence: digest("evaluation-outcome"),
            outcome_model_evidence: digest("ignored-caller-model"),
        });
        assignments.push(ClusterAssignment {
            decision_id,
            cluster_id: id(&format!("cluster-{index}")),
        });
    }

    Fixture {
        frozen,
        temporal,
        training,
        targets,
        observations,
        assignments,
    }
}

fn new_file() -> (PathBuf, std::fs::File) {
    let serial = NEXT_FILE.fetch_add(1, Ordering::Relaxed);
    let path = std::env::temp_dir().join(format!(
        "hepta-learning-eval-product-{}-{serial}.journal",
        std::process::id()
    ));
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(&path)
        .unwrap();
    (path, file)
}

fn run(
    runner: &mut ProductEvaluationRunnerV1,
    anchors: &mut MemoryAnchorStore,
    fixture: &Fixture,
) -> Result<ProductTemporalEvaluationReceiptV1, ProductEvaluationError> {
    runner.evaluate_temporal_candidate(
        anchors,
        &fixture.frozen,
        fixture.frozen.final_holdout_digest,
        &fixture.temporal,
        &fixture.training,
        &fixture.targets,
        &fixture.observations,
        &fixture.assignments,
    )
}

#[test]
fn product_runner_commits_anchor_and_exact_retry_is_idempotent() {
    let fixture = fixture();
    let (path, file) = new_file();
    let binding = digest("product-holdout-owner");
    let mut anchors = MemoryAnchorStore::default();
    let mut runner = ProductEvaluationRunnerV1::create(file, binding, &mut anchors).unwrap();

    let first = run(&mut runner, &mut anchors, &fixture).unwrap();
    assert_eq!(first.holdout.disposition, HoldoutUseDispositionV1::Recorded);
    assert_eq!(anchors.load(binding).unwrap(), runner.anchor());
    assert_eq!(runner.anchor().sequence, 1);
    assert_eq!(first.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(first.evaluation.authority, AuthorityPosture::DENY_ALL);

    let retry = run(&mut runner, &mut anchors, &fixture).unwrap();
    assert_eq!(
        retry.holdout.disposition,
        HoldoutUseDispositionV1::IdempotentReplay
    );
    assert_eq!(retry.execution_digest, first.execution_digest);
    assert_eq!(runner.anchor().sequence, 1);

    drop(runner);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn indeterminate_anchor_commit_poison_requires_recovery() {
    let fixture = fixture();
    let (path, file) = new_file();
    let binding = digest("product-holdout-owner-recovery");
    let mut anchors = MemoryAnchorStore::default();
    let mut runner = ProductEvaluationRunnerV1::create(file, binding, &mut anchors).unwrap();
    anchors.fail_next_commit = true;

    assert_eq!(
        run(&mut runner, &mut anchors, &fixture),
        Err(ProductEvaluationError::Anchor(
            HoldoutAnchorStoreError::Indeterminate
        ))
    );
    assert_eq!(runner.anchor().sequence, 1);
    assert_eq!(anchors.load(binding).unwrap().sequence, 0);
    assert_eq!(
        run(&mut runner, &mut anchors, &fixture),
        Err(ProductEvaluationError::Poisoned)
    );

    drop(runner);
    let file = OpenOptions::new().read(true).write(true).open(&path).unwrap();
    let mut recovered = ProductEvaluationRunnerV1::recover(file, binding, &mut anchors).unwrap();
    assert_eq!(anchors.load(binding).unwrap(), recovered.anchor());
    assert_eq!(recovered.anchor().sequence, 1);
    let receipt = run(&mut recovered, &mut anchors, &fixture).unwrap();
    assert_eq!(
        receipt.holdout.disposition,
        HoldoutUseDispositionV1::IdempotentReplay
    );

    drop(recovered);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn product_binding_drift_rejects_before_holdout_is_burned() {
    let fixture = fixture();
    let (path, file) = new_file();
    let binding = digest("product-holdout-owner-binding");
    let mut anchors = MemoryAnchorStore::default();
    let mut runner = ProductEvaluationRunnerV1::create(file, binding, &mut anchors).unwrap();

    assert_eq!(
        runner.evaluate_temporal_candidate(
            &mut anchors,
            &fixture.frozen,
            digest("wrong-holdout"),
            &fixture.temporal,
            &fixture.training,
            &fixture.targets,
            &fixture.observations,
            &fixture.assignments,
        ),
        Err(ProductEvaluationError::Binding("final holdout digest"))
    );
    assert_eq!(runner.anchor().sequence, 0);

    let mut multiplicity = fixture.temporal.clone();
    multiplicity.confidence.simultaneous_comparisons = 2;
    assert_eq!(
        runner.evaluate_temporal_candidate(
            &mut anchors,
            &fixture.frozen,
            fixture.frozen.final_holdout_digest,
            &multiplicity,
            &fixture.training,
            &fixture.targets,
            &fixture.observations,
            &fixture.assignments,
        ),
        Err(ProductEvaluationError::Binding("multiplicity"))
    );
    assert_eq!(runner.anchor().sequence, 0);

    drop(runner);
    std::fs::remove_file(path).unwrap();
}
