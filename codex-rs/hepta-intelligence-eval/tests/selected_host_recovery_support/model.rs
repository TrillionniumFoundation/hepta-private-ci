use codex_hepta_intelligence_eval::ClusterAssignment;
use codex_hepta_intelligence_eval::ClusterConfidencePlan;
use codex_hepta_intelligence_eval::CrossFoldPartitionV1;
use codex_hepta_intelligence_eval::CrossFoldPlanV1;
use codex_hepta_intelligence_eval::EvaluationClaimScopeV1;
use codex_hepta_intelligence_eval::EvaluationDirectionV1;
use codex_hepta_intelligence_eval::FinalHoldoutJournalReceiptV1;
use codex_hepta_intelligence_eval::FinalHoldoutProviderV1;
use codex_hepta_intelligence_eval::HeldOutTarget;
use codex_hepta_intelligence_eval::MetricContractV1;
use codex_hepta_intelligence_eval::MetricRoleContractV2;
use codex_hepta_intelligence_eval::MetricRoleV2;
use codex_hepta_intelligence_eval::OpeAction;
use codex_hepta_intelligence_eval::OpePlan;
use codex_hepta_intelligence_eval::OpeRow;
use codex_hepta_intelligence_eval::OutcomeTrainingSample;
use codex_hepta_intelligence_eval::ProductFrozenEvaluationPlanV1;
use codex_hepta_intelligence_eval::ProductMetricSourceContractV1;
use codex_hepta_intelligence_eval::ProductMetricSourceV1;
use codex_hepta_intelligence_eval::ProductProviderErrorV1;
use codex_hepta_intelligence_eval::TemporalComparisonInputsV1;
use codex_hepta_intelligence_eval::TemporalEvaluationPlan;
use codex_hepta_intelligence_eval::TemporalFoldPlan;
use codex_hepta_intelligence_eval::freeze_product_evaluation_plan_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

pub fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).expect("valid id")
}

pub fn digest(value: &str) -> Digest32 {
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
        plan_id: id("selected-host-recovery-plan"),
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

pub fn product_plan() -> (
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

pub struct Provider {
    pub inputs: Option<TemporalComparisonInputsV1>,
}

impl FinalHoldoutProviderV1 for Provider {
    fn manifest_digest(&mut self) -> Result<Digest32, ProductProviderErrorV1> {
        Ok(digest("final-holdout"))
    }

    fn release_after_consumption(
        &mut self,
        _receipt: &FinalHoldoutJournalReceiptV1,
    ) -> Result<TemporalComparisonInputsV1, ProductProviderErrorV1> {
        self.inputs
            .take()
            .ok_or(ProductProviderErrorV1::Unavailable)
    }
}

pub fn inputs() -> TemporalComparisonInputsV1 {
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
                    behavior_probability: ProbabilityQ32::from_raw(1 << 31)
                        .expect("behavior probability"),
                    evaluation_probability: ProbabilityQ32::from_raw(weight)
                        .expect("evaluation probability"),
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
