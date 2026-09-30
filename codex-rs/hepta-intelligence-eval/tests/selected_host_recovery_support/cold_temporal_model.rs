//! Synthetic temporal and V3 inputs for cold-process recovery qualification.
//! The external-window packet is a fixture, not future-calendar efficacy.
use codex_hepta_intelligence_eval::*;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;

#[path = "model.rs"]
mod existing;
use existing::digest;
use existing::id;

pub struct Provider {
    inputs: Option<TemporalComparisonInputsV1>,
}

impl FinalHoldoutProviderV1 for Provider {
    fn manifest_digest(&mut self) -> Result<codex_hepta_types::Digest32, ProductProviderErrorV1> {
        Ok(digest("cold-temporal-manifest"))
    }
    fn release_after_consumption(
        &mut self,
        _: &FinalHoldoutJournalReceiptV1,
    ) -> Result<TemporalComparisonInputsV1, ProductProviderErrorV1> {
        self.inputs.take().ok_or(ProductProviderErrorV1::Rejected)
    }
}

pub fn fixture(
    longitudinal: bool,
) -> (
    ProductFrozenEvaluationPlanV1,
    TemporalEvaluationPlan,
    TemporalEvaluationPlan,
    Provider,
) {
    let (_, mut candidate, mut baseline) = existing::product_plan();
    for plan in [&mut candidate, &mut baseline] {
        plan.fold.evaluation_start = 30;
        plan.ope.minimum_rows = 4096;
        plan.ope.minimum_ess = FixedQ32::from_raw(1024_i64 << 32);
        plan.ope.maximum_weight = FixedQ32::from_raw(2_i64 << 32);
        plan.confidence.minimum_clusters = 4096;
        plan.confidence.simultaneous_comparisons = 4;
        plan.plan_digest = plan
            .canonical_digest()
            .unwrap_or_else(|error| panic!("rebind temporal plan: {error:?}"));
    }
    let roles = vec![MetricRoleContractV2 {
        metric_id: id("utility"),
        role: MetricRoleV2::PrimarySuperiority {
            minimum_improvement: FixedQ32::ZERO,
        },
    }];
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
                "future-window-2"
            })],
            model_digest: digest(&format!("model-{suffix}")),
            predictions_digest: digest(&format!("predictions-{suffix}")),
        })
        .collect();
    let product = freeze_product_evaluation_plan_v1(
        CrossFoldPlanV1 {
            plan_id: id("cold-temporal-plan"),
            claim_scope: if longitudinal {
                EvaluationClaimScopeV1::SystemLongitudinal
            } else {
                EvaluationClaimScopeV1::Qualification
            },
            candidate_id: id("candidate"),
            baseline_id: id("baseline"),
            objective_digest: digest("objective"),
            dataset_digest: digest("dataset"),
            estimand_digest: digest("cold-temporal-estimand"),
            metric_contracts: vec![MetricContractV1 {
                metric_id: id("utility"),
                direction: EvaluationDirectionV1::Maximize,
                safety_floor: Some(FixedQ32::ZERO),
            }],
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 4,
            folds,
            final_holdout_window_id: id("final-window"),
            final_holdout_digest: digest("cold-temporal-manifest"),
        },
        roles,
        vec![ProductMetricSourceContractV1 {
            metric_id: id("utility"),
            source: ProductMetricSourceV1::DoublyRobust,
        }],
        &candidate,
        &baseline,
    )
    .unwrap_or_else(|error| panic!("freeze typed temporal plan: {error:?}"));
    let template = existing::inputs();
    let mut inputs = TemporalComparisonInputsV1 {
        training: template.training.clone(),
        targets: Vec::new(),
        candidate_observations: Vec::new(),
        baseline_observations: Vec::new(),
        assignments: Vec::new(),
        snapshot_ids: if longitudinal {
            vec![id("snapshot-0"), id("snapshot-1"), id("snapshot-2")]
        } else {
            vec![id("snapshot-1")]
        },
        future_window_ids: if longitudinal {
            vec![id("final-window"), id("future-window-2")]
        } else {
            vec![id("final-window")]
        },
    };
    for index in 0..4096 {
        let decision_id = id(&format!("cold-decision-{index}"));
        let mut target = template.targets[0].clone();
        target.decision_id = decision_id.clone();
        target.principal_lineage = id(&format!("cold-principal-{index}"));
        target.episode_lineage = id(&format!("cold-episode-{index}"));
        target.decision_at = 31;
        inputs.targets.push(target);
        let candidate_row = |candidate_policy: bool| {
            let mut row = template.candidate_observations[0].clone();
            row.decision_id = decision_id.clone();
            row.chosen_action = id(if index % 2 == 0 { "a" } else { "b" });
            row.finalized_outcome = Some(if index % 2 == 0 {
                FixedQ32::ONE
            } else {
                FixedQ32::ZERO
            });
            row.outcome_observed_at = 40;
            row.outcome_evidence = digest(&format!("cold-observation-{index}"));
            for action in &mut row.actions {
                action.evaluation_probability = ProbabilityQ32::from_raw(
                    if (action.action_id.as_str() == "a") == candidate_policy {
                        1 << 32
                    } else {
                        0
                    },
                )
                .unwrap_or_else(|error| panic!("evaluation probability: {error:?}"));
            }
            row
        };
        inputs.candidate_observations.push(candidate_row(true));
        inputs.baseline_observations.push(candidate_row(false));
        inputs.assignments.push(ClusterAssignment {
            decision_id,
            cluster_id: id(&format!("cold-cluster-{index}")),
        });
    }
    (
        product,
        candidate,
        baseline,
        Provider {
            inputs: Some(inputs),
        },
    )
}
