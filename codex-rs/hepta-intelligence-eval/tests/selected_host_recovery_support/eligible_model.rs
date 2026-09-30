//! Synthetic paired measurements for an actually eligible native multi-outcome
//! receipt. This exercises estimators; it is not real learning-efficacy evidence.
use codex_hepta_intelligence_eval::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

pub fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture id")
}
pub fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

const ROWS: usize = 4096;

fn temporal(name: &str) -> TemporalEvaluationPlan {
    let mut value = TemporalEvaluationPlan {
        plan_digest: Digest32::ZERO,
        evaluation_id: id(name),
        objective_digest: digest("objective"),
        fold: TemporalFoldPlan {
            plan_digest: digest(&format!("{name}-fold")),
            fold_id: id(name),
            training_watermark: 10,
            evaluation_start: 20,
            minimum_per_action: 2,
        },
        ope: OpePlan {
            plan_digest: digest(&format!("{name}-ope")),
            outcome_watermark: 100,
            minimum_rows: ROWS,
            minimum_ess: FixedQ32::from_raw(100_i64 << 32),
            maximum_weight: FixedQ32::from_raw(2_i64 << 32),
        },
        confidence: ClusterConfidencePlan {
            plan_digest: digest(&format!("{name}-confidence")),
            assumptions_digest: digest("synthetic-independent-equal-size-clusters"),
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 4,
            minimum_clusters: ROWS,
        },
    };
    value.plan_digest = value.canonical_digest().expect("temporal digest");
    value
}

fn inputs(channel: &str, good: FixedQ32, bad: FixedQ32) -> TemporalComparisonInputsV1 {
    let mut training = Vec::new();
    for (action, outcome) in [("good", good), ("bad", bad)] {
        for index in 0..4 {
            training.push(OutcomeTrainingSample {
                decision_id: id(&format!("{channel}-train-{action}-{index}")),
                principal_lineage: id(&format!("train-p-{action}-{index}")),
                episode_lineage: id(&format!("train-e-{action}-{index}")),
                window_id: id("training-window"),
                action_id: id(action),
                outcome,
                observed_at: 5,
                evidence_digest: digest(&format!("{channel}-training")),
            });
        }
    }
    let targets = (0..ROWS)
        .map(|index| HeldOutTarget {
            decision_id: id(&format!("decision-{index}")),
            principal_lineage: id(&format!("principal-{index}")),
            episode_lineage: id(&format!("episode-{index}")),
            window_id: id("final-window"),
            decision_at: 20,
            actions: vec![id("good"), id("bad")],
        })
        .collect();
    let rows = |candidate: bool| {
        (0..ROWS)
            .map(|index| {
                let chosen_good = index % 2 == 0;
                OpeRow {
                    decision_id: id(&format!("decision-{index}")),
                    chosen_action: id(if chosen_good { "good" } else { "bad" }),
                    complete_candidates: true,
                    actions: ["good", "bad"]
                        .into_iter()
                        .map(|action| OpeAction {
                            action_id: id(action),
                            behavior_probability: ProbabilityQ32::from_raw(1 << 31)
                                .expect("behavior"),
                            evaluation_probability: ProbabilityQ32::from_raw(
                                if (action == "good") == candidate {
                                    1 << 32
                                } else {
                                    0
                                },
                            )
                            .expect("evaluation"),
                            predicted_outcome: FixedQ32::ZERO,
                        })
                        .collect(),
                    finalized_outcome: Some(if chosen_good { good } else { bad }),
                    outcome_observed_at: 50,
                    outcome_evidence: digest(&format!("{channel}-observed-{index}")),
                    outcome_model_evidence: digest("replaced-by-training-only-fit"),
                }
            })
            .collect()
    };
    TemporalComparisonInputsV1 {
        training,
        targets,
        candidate_observations: rows(true),
        baseline_observations: rows(false),
        assignments: (0..ROWS)
            .map(|index| ClusterAssignment {
                decision_id: id(&format!("decision-{index}")),
                cluster_id: id(&format!("cluster-{index}")),
            })
            .collect(),
        snapshot_ids: vec![id("snapshot")],
        future_window_ids: vec![id("final-window")],
    }
}

pub struct Provider {
    batch: Option<Vec<ProductOutcomeInputV1>>,
}

impl FinalOutcomeHoldoutProviderV1 for Provider {
    fn manifest_digest(&mut self) -> Result<Digest32, ProductProviderErrorV1> {
        Ok(digest("eligible-outcome-manifest"))
    }
    fn release_after_consumption(
        &mut self,
        _: &FinalHoldoutJournalReceiptV1,
    ) -> Result<Vec<ProductOutcomeInputV1>, ProductProviderErrorV1> {
        self.batch.take().ok_or(ProductProviderErrorV1::Rejected)
    }
}

pub fn fixture() -> (
    ProductFrozenOutcomePlanV1,
    Provider,
    Vec<MetricRoleContractV2>,
) {
    let data = [
        inputs("accuracy", FixedQ32::ONE, FixedQ32::ZERO),
        inputs(
            "retention",
            FixedQ32::from_raw(3_i64 << 30),
            FixedQ32::from_raw(1_i64 << 30),
        ),
    ];
    let channels: Vec<_> = ["accuracy", "retention"]
        .into_iter()
        .zip(&data)
        .map(|(name, inputs)| ProductOutcomeChannelContractV1 {
            metric_id: id(name),
            channel_id: id(name),
            schema_digest: digest("scalar-schema"),
            unit_id: id("unit-interval"),
            normalization_digest: digest("identity-normalization"),
            subgroup_digest: digest("fixture-population"),
            window_id: id("final-window"),
            measurement_start_micros: 20,
            measurement_end_micros: 100,
            provenance_digest: digest(&format!("synthetic-custodian-{name}")),
            inputs_digest: product_outcome_inputs_digest_v1(inputs).expect("input digest"),
            candidate_plan: temporal(&format!("{name}-candidate")),
            baseline_plan: temporal(&format!("{name}-baseline")),
        })
        .collect();
    let roles: Vec<_> = channels
        .iter()
        .map(|channel| MetricRoleContractV2 {
            metric_id: channel.metric_id.clone(),
            role: MetricRoleV2::PrimarySuperiority {
                minimum_improvement: FixedQ32::ZERO,
            },
        })
        .collect();
    let metrics = channels
        .iter()
        .map(|channel| MetricContractV1 {
            metric_id: channel.metric_id.clone(),
            direction: EvaluationDirectionV1::Maximize,
            safety_floor: Some(FixedQ32::ZERO),
        })
        .collect();
    let sources = channels
        .iter()
        .map(|channel| ProductMetricSourceContractV1 {
            metric_id: channel.metric_id.clone(),
            source: ProductMetricSourceV1::Ips,
        })
        .collect();
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
    let plan = freeze_product_outcome_plan_v1(
        CrossFoldPlanV1 {
            plan_id: id("eligible-outcome-plan"),
            claim_scope: EvaluationClaimScopeV1::Qualification,
            candidate_id: id("candidate"),
            baseline_id: id("baseline"),
            objective_digest: digest("objective"),
            dataset_digest: digest("dataset"),
            estimand_digest: digest("estimand"),
            metric_contracts: metrics,
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 4,
            folds,
            final_holdout_window_id: id("final-window"),
            final_holdout_digest: digest("eligible-outcome-manifest"),
        },
        roles.clone(),
        sources,
        channels,
    )
    .expect("freeze native measured plan");
    let batch = plan
        .channels()
        .iter()
        .zip(data)
        .map(|(contract, inputs)| ProductOutcomeInputV1 {
            channel_id: contract.channel_id.clone(),
            contract_digest: contract.canonical_digest().expect("channel digest"),
            inputs,
        })
        .collect();
    (plan, Provider { batch: Some(batch) }, roles)
}
