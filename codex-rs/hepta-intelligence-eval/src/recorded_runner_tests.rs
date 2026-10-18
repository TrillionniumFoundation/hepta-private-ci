use super::*;
use std::cell::RefCell;
use std::rc::Rc;

use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;

use crate::ClusterAssignment;
use crate::ClusterConfidencePlan;
use crate::CrossFoldPartitionV1;
use crate::CrossFoldPlanV1;
use crate::EvaluationClaimScopeV1;
use crate::EvaluationDirectionV1;
use crate::FinalHoldoutCasRecordV1;
use crate::FinalHoldoutCasStoreError;
use crate::FinalHoldoutJournalV1;
use crate::HeldOutTarget;
use crate::HoldoutWriterFenceV1;
use crate::InMemoryProductEvaluationAttemptJournalV1;
use crate::MetricContractV1;
use crate::MetricRoleContractV2;
use crate::MetricRoleV2;
use crate::OpeAction;
use crate::OpePlan;
use crate::OpeRow;
use crate::OutcomeTrainingSample;
use crate::ProductEvaluationAttemptReceiptV1;
use crate::ProductMetricSourceContractV1;
use crate::ProductMetricSourceV1;
use crate::TemporalFoldPlan;
use crate::freeze_cross_fold_plan;
use crate::freeze_product_evaluation_plan_v1;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid test id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn cross_fold() -> CrossFoldPlanV1 {
    let folds = ["a", "b"]
        .into_iter()
        .map(|suffix| CrossFoldPartitionV1 {
            fold_id: id(&format!("fold-{suffix}")),
            training_principals: vec![id(&format!("train-principal-{suffix}"))],
            training_episodes: vec![id(&format!("train-episode-{suffix}"))],
            training_windows: vec![id(&format!("train-window-{suffix}"))],
            holdout_principals: vec![id(&format!("holdout-principal-{suffix}"))],
            holdout_episodes: vec![id(&format!("holdout-episode-{suffix}"))],
            holdout_windows: vec![id(if suffix == "b" {
                "final-window"
            } else {
                "other-window"
            })],
            model_digest: digest(&format!("model-{suffix}")),
            predictions_digest: digest(&format!("predictions-{suffix}")),
        })
        .collect();
    CrossFoldPlanV1 {
        plan_id: id("recorded-runner-plan"),
        claim_scope: EvaluationClaimScopeV1::Qualification,
        candidate_id: id("candidate"),
        baseline_id: id("baseline"),
        objective_digest: digest("objective"),
        dataset_digest: digest("dataset"),
        estimand_digest: digest("estimand"),
        metric_contracts: vec![MetricContractV1 {
            metric_id: id("utility"),
            direction: EvaluationDirectionV1::Maximize,
            safety_floor: Some(FixedQ32::ZERO),
        }],
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 1,
        folds,
        final_holdout_window_id: id("final-window"),
        final_holdout_digest: digest("final-holdout"),
    }
}

fn temporal(name: &str) -> TemporalEvaluationPlan {
    let mut plan = TemporalEvaluationPlan {
        plan_digest: Digest32::ZERO,
        evaluation_id: id(name),
        objective_digest: digest("objective"),
        fold: TemporalFoldPlan {
            plan_digest: digest(&format!("{name}-fold")),
            fold_id: id(&format!("{name}-fold")),
            training_watermark: 10,
            evaluation_start: 20,
            minimum_per_action: 2,
        },
        ope: OpePlan {
            plan_digest: digest(&format!("{name}-ope")),
            outcome_watermark: 100,
            minimum_rows: 2,
            minimum_ess: FixedQ32::ONE,
            maximum_weight: FixedQ32::from_raw(4_i64 << 32),
        },
        confidence: ClusterConfidencePlan {
            plan_digest: digest(&format!("{name}-confidence")),
            assumptions_digest: digest("independent-clusters"),
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            minimum_clusters: 2,
        },
    };
    plan.plan_digest = plan.canonical_digest().expect("canonical temporal plan");
    plan
}

fn product_plan() -> (
    ProductFrozenEvaluationPlanV1,
    TemporalEvaluationPlan,
    TemporalEvaluationPlan,
) {
    let candidate = temporal("candidate");
    let baseline = temporal("baseline");
    let plan = freeze_product_evaluation_plan_v1(
        cross_fold(),
        vec![MetricRoleContractV2 {
            metric_id: id("utility"),
            role: MetricRoleV2::PrimarySuperiority {
                minimum_improvement: FixedQ32::ZERO,
            },
        }],
        vec![ProductMetricSourceContractV1 {
            metric_id: id("utility"),
            source: ProductMetricSourceV1::DoublyRobust,
        }],
        &candidate,
        &baseline,
    )
    .expect("freeze product plan");
    (plan, candidate, baseline)
}

#[derive(Clone, Default)]
struct MemoryCas(Rc<RefCell<Option<FinalHoldoutCasRecordV1>>>);

impl FinalHoldoutCasStoreV1 for MemoryCas {
    fn load(
        &mut self,
        binding: Digest32,
    ) -> Result<Option<FinalHoldoutCasRecordV1>, FinalHoldoutCasStoreError> {
        let current = self.0.borrow();
        if current
            .as_ref()
            .is_some_and(|record| record.binding != binding)
        {
            return Err(FinalHoldoutCasStoreError::Conflict);
        }
        Ok(current.clone())
    }
    fn compare_and_swap(
        &mut self,
        binding: Digest32,
        expected: Option<Digest32>,
        next: &FinalHoldoutCasRecordV1,
    ) -> Result<(), FinalHoldoutCasStoreError> {
        let mut current = self.0.borrow_mut();
        if next.binding != binding || current.as_ref().map(|record| record.state_digest) != expected
        {
            return Err(FinalHoldoutCasStoreError::Conflict);
        }
        *current = Some(next.clone());
        Ok(())
    }
}

fn owner(store: MemoryCas) -> FencedFinalHoldoutOwnerV1<MemoryCas> {
    FencedFinalHoldoutOwnerV1::initialize(
        store,
        digest("namespace"),
        HoldoutWriterFenceV1 {
            owner_id: id("owner"),
            generation: 1,
            lease_digest: digest("lease"),
        },
    )
    .expect("initialize owner")
}

struct Provider {
    manifest_calls: usize,
    release_calls: usize,
    inputs: Option<TemporalComparisonInputsV1>,
}

impl FinalHoldoutProviderV1 for Provider {
    fn manifest_digest(&mut self) -> Result<Digest32, ProductProviderErrorV1> {
        self.manifest_calls += 1;
        Ok(digest("final-holdout"))
    }
    fn release_after_consumption(
        &mut self,
        _receipt: &FinalHoldoutJournalReceiptV1,
    ) -> Result<TemporalComparisonInputsV1, ProductProviderErrorV1> {
        self.release_calls += 1;
        self.inputs
            .take()
            .ok_or(ProductProviderErrorV1::Unavailable)
    }
}

fn inputs() -> TemporalComparisonInputsV1 {
    let mut training = Vec::new();
    for action in ["a", "b"] {
        for index in 0..2 {
            training.push(OutcomeTrainingSample {
                decision_id: id(&format!("train-{action}-{index}")),
                principal_lineage: id(&format!("train-principal-{action}-{index}")),
                episode_lineage: id(&format!("train-episode-{action}-{index}")),
                window_id: id(&format!("train-window-{action}-{index}")),
                action_id: id(action),
                outcome: if action == "a" {
                    FixedQ32::ONE
                } else {
                    FixedQ32::ZERO
                },
                observed_at: 5,
                evidence_digest: digest("training-evidence"),
            });
        }
    }
    let mut targets = Vec::new();
    let mut candidate_observations = Vec::new();
    let mut baseline_observations = Vec::new();
    let mut assignments = Vec::new();
    for index in 0..128 {
        let decision = id(&format!("decision-{index}"));
        targets.push(HeldOutTarget {
            decision_id: decision.clone(),
            principal_lineage: id(&format!("principal-{index}")),
            episode_lineage: id(&format!("episode-{index}")),
            window_id: id("final-window"),
            decision_at: 20,
            actions: vec![id("a"), id("b")],
        });
        let make = |weights: [u64; 2]| OpeRow {
            decision_id: decision.clone(),
            chosen_action: id("a"),
            complete_candidates: true,
            actions: ["a", "b"]
                .into_iter()
                .zip(weights)
                .map(|(action, weight)| OpeAction {
                    action_id: id(action),
                    behavior_probability: ProbabilityQ32::from_raw(1 << 31).expect("behavior"),
                    evaluation_probability: ProbabilityQ32::from_raw(weight).expect("policy"),
                    predicted_outcome: FixedQ32::ZERO,
                })
                .collect(),
            finalized_outcome: Some(FixedQ32::ONE),
            outcome_observed_at: 50,
            outcome_evidence: digest("observed-outcome"),
            outcome_model_evidence: digest("ignored-model"),
        };
        candidate_observations.push(make([3 << 30, 1 << 30]));
        baseline_observations.push(make([1 << 31, 1 << 31]));
        assignments.push(ClusterAssignment {
            decision_id: decision,
            cluster_id: id(&format!("cluster-{index}")),
        });
    }
    TemporalComparisonInputsV1 {
        training,
        targets,
        candidate_observations,
        baseline_observations,
        assignments,
        snapshot_ids: vec![id("snapshot-1")],
        future_window_ids: vec![id("final-window")],
    }
}

struct IndeterminateJournal;
impl ProductEvaluationAttemptJournalV1 for IndeterminateJournal {
    fn append(
        &mut self,
        _transition: ProductEvaluationAttemptTransitionV1,
    ) -> Result<ProductEvaluationAttemptReceiptV1, ProductEvaluationAttemptJournalErrorV1> {
        Err(ProductEvaluationAttemptJournalErrorV1::Indeterminate)
    }
    fn latest(
        &mut self,
        _attempt_id: &StableId,
    ) -> Result<Option<ProductEvaluationAttemptReceiptV1>, ProductEvaluationAttemptJournalErrorV1>
    {
        Ok(None)
    }
}

#[test]
fn journal_failure_preserves_consumed_holdout_and_blocks_release() {
    let plan = freeze_cross_fold_plan(cross_fold()).expect("freeze");
    let mut holdout = FinalHoldoutJournalV1::new();
    let receipt = holdout
        .consume(holdout.head_digest(), &plan)
        .expect("consume");
    let mut provider = Provider {
        manifest_calls: 0,
        release_calls: 0,
        inputs: None,
    };
    let mut journal = IndeterminateJournal;
    {
        let mut recorded = RecordedHoldoutProviderV1 {
            attempt_id: id("attempt-1"),
            plan_digest: plan.plan_digest,
            inner: &mut provider,
            journal: &mut journal,
            consumed_record_digest: None,
            journal_error: None,
        };
        assert!(matches!(
            recorded.release_after_consumption(&receipt),
            Err(ProductProviderErrorV1::Indeterminate)
        ));
        assert_eq!(recorded.consumed_record_digest, Some(receipt.record_digest));
        assert_eq!(
            recorded.journal_error,
            Some(ProductEvaluationAttemptJournalErrorV1::Indeterminate)
        );
    }
    assert_eq!(provider.release_calls, 0);
}

#[test]
fn durable_intent_failure_precedes_all_provider_and_holdout_calls() {
    let mut runner = RecordedProductEvaluationRunnerV1::new(owner(MemoryCas::default()));
    let before = runner.holdout_state_digest();
    let (plan, candidate, baseline) = product_plan();
    let mut provider = Provider {
        manifest_calls: 0,
        release_calls: 0,
        inputs: None,
    };
    assert!(matches!(
        runner.evaluate_temporal_comparison(
            id("attempt"),
            &plan,
            &candidate,
            &baseline,
            &mut provider,
            &mut IndeterminateJournal
        ),
        Err(RecordedProductEvaluationErrorV1::Journal(_))
    ));
    assert_eq!(runner.holdout_state_digest(), before);
    assert_eq!((provider.manifest_calls, provider.release_calls), (0, 0));
}

#[test]
fn sealed_comparison_remains_pending_and_cannot_be_reexecuted() {
    let mut runner = RecordedProductEvaluationRunnerV1::new(owner(MemoryCas::default()));
    let (plan, candidate, baseline) = product_plan();
    let mut provider = Provider {
        manifest_calls: 0,
        release_calls: 0,
        inputs: Some(inputs()),
    };
    let mut journal = InMemoryProductEvaluationAttemptJournalV1::default();
    let receipt = runner
        .evaluate_temporal_comparison(
            id("attempt"),
            &plan,
            &candidate,
            &baseline,
            &mut provider,
            &mut journal,
        )
        .expect("evaluate");
    let history = journal.history(&id("attempt")).expect("history");
    assert_eq!(
        history
            .iter()
            .map(|event| event.transition.phase)
            .collect::<Vec<_>>(),
        vec![
            ProductEvaluationAttemptPhaseV1::IntentPersisted,
            ProductEvaluationAttemptPhaseV1::HoldoutConsumed,
            ProductEvaluationAttemptPhaseV1::ComparisonSealed,
        ]
    );
    assert_eq!(
        history[0].transition.holdout_record_digest,
        digest("namespace")
    );
    assert_eq!(
        history[2].transition.terminal_digest,
        receipt.execution_digest
    );
    assert_eq!(
        journal
            .pending(/*after*/ None, /*limit*/ 1)
            .expect("pending"),
        vec![history[2].clone()]
    );
    assert!(matches!(
        runner.evaluate_temporal_comparison(
            id("attempt"),
            &plan,
            &candidate,
            &baseline,
            &mut provider,
            &mut journal
        ),
        Err(RecordedProductEvaluationErrorV1::AttemptRequiresRecovery { .. })
    ));
    assert_eq!((provider.manifest_calls, provider.release_calls), (1, 1));
}

#[test]
fn replacing_attempt_journal_cannot_release_consumed_holdout_again() {
    let (plan, candidate, baseline) = product_plan();
    let mut holdout = owner(MemoryCas::default());
    holdout
        .consume(&plan.frozen_plan)
        .expect("previously consumed");
    let mut runner = RecordedProductEvaluationRunnerV1::new(holdout);
    let mut provider = Provider {
        manifest_calls: 0,
        release_calls: 0,
        inputs: Some(inputs()),
    };
    let mut replacement = InMemoryProductEvaluationAttemptJournalV1::default();
    assert!(
        runner
            .evaluate_temporal_comparison(
                id("replacement-attempt"),
                &plan,
                &candidate,
                &baseline,
                &mut provider,
                &mut replacement
            )
            .is_err()
    );
    assert_eq!(provider.release_calls, 0);
}

#[test]
fn post_consumption_provider_failure_keeps_irreversible_history() {
    let mut runner = RecordedProductEvaluationRunnerV1::new(owner(MemoryCas::default()));
    let (plan, candidate, baseline) = product_plan();
    let mut provider = Provider {
        manifest_calls: 0,
        release_calls: 0,
        inputs: None,
    };
    let mut journal = InMemoryProductEvaluationAttemptJournalV1::default();
    assert!(
        runner
            .evaluate_temporal_comparison(
                id("attempt"),
                &plan,
                &candidate,
                &baseline,
                &mut provider,
                &mut journal
            )
            .is_err()
    );
    let history = journal.history(&id("attempt")).expect("history");
    assert_eq!(
        history
            .iter()
            .map(|event| event.transition.phase)
            .collect::<Vec<_>>(),
        vec![
            ProductEvaluationAttemptPhaseV1::IntentPersisted,
            ProductEvaluationAttemptPhaseV1::HoldoutConsumed,
            ProductEvaluationAttemptPhaseV1::Failed,
        ]
    );
    assert_eq!(provider.release_calls, 1);
}

#[cfg(unix)]
#[path = "recorded_runner_process_tests.rs"]
mod process_tests;
