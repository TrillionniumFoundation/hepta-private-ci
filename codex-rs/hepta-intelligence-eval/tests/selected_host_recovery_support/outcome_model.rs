use codex_hepta_intelligence_eval::ClusterAssignment;
use codex_hepta_intelligence_eval::ClusterConfidencePlan;
use codex_hepta_intelligence_eval::CrossFoldPartitionV1;
use codex_hepta_intelligence_eval::CrossFoldPlanV1;
use codex_hepta_intelligence_eval::EvaluationClaimScopeV1;
use codex_hepta_intelligence_eval::EvaluationDirectionV1;
use codex_hepta_intelligence_eval::FinalHoldoutJournalReceiptV1;
use codex_hepta_intelligence_eval::FinalOutcomeHoldoutProviderV1;
use codex_hepta_intelligence_eval::HeldOutTarget;
use codex_hepta_intelligence_eval::MetricContractV1;
use codex_hepta_intelligence_eval::MetricRoleContractV2;
use codex_hepta_intelligence_eval::MetricRoleV2;
use codex_hepta_intelligence_eval::OpeAction;
use codex_hepta_intelligence_eval::OpePlan;
use codex_hepta_intelligence_eval::OpeRow;
use codex_hepta_intelligence_eval::OutcomeTrainingSample;
use codex_hepta_intelligence_eval::ProductEvaluationError;
use codex_hepta_intelligence_eval::ProductFrozenOutcomePlanV1;
use codex_hepta_intelligence_eval::ProductMetricSourceContractV1;
use codex_hepta_intelligence_eval::ProductMetricSourceV1;
use codex_hepta_intelligence_eval::ProductOutcomeChannelContractV1;
use codex_hepta_intelligence_eval::ProductOutcomeInputV1;
use codex_hepta_intelligence_eval::ProductProviderErrorV1;
use codex_hepta_intelligence_eval::TemporalComparisonInputsV1;
use codex_hepta_intelligence_eval::TemporalEvaluationPlan;
use codex_hepta_intelligence_eval::TemporalFoldPlan;
use codex_hepta_intelligence_eval::freeze_product_outcome_plan_v1;
use codex_hepta_intelligence_eval::product_outcome_inputs_digest_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

pub fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).unwrap_or_else(|error| panic!("valid id: {error:?}"))
}

pub fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn temporal(name: &str) -> TemporalEvaluationPlan {
    let mut plan = TemporalEvaluationPlan {
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
            minimum_rows: 2,
            minimum_ess: FixedQ32::ONE,
            maximum_weight: FixedQ32::ONE,
        },
        confidence: ClusterConfidencePlan {
            plan_digest: digest(&format!("{name}-confidence")),
            assumptions_digest: digest("independent"),
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 4,
            minimum_clusters: 2,
        },
    };
    plan.plan_digest = plan
        .canonical_digest()
        .unwrap_or_else(|error| panic!("canonical plan: {error:?}"));
    plan
}

fn inputs(channel: &str, outcome: FixedQ32) -> TemporalComparisonInputsV1 {
    let training = (0..2)
        .map(|index| OutcomeTrainingSample {
            decision_id: id(&format!("{channel}-training-{index}")),
            principal_lineage: id(&format!("{channel}-training-principal-{index}")),
            episode_lineage: id(&format!("{channel}-training-episode-{index}")),
            window_id: id(&format!("{channel}-training-window")),
            action_id: id("action"),
            outcome,
            observed_at: 5,
            evidence_digest: digest(channel),
        })
        .collect();
    let targets = (0..128)
        .map(|index| HeldOutTarget {
            decision_id: id(&format!("decision-{index}")),
            principal_lineage: id(&format!("principal-{index}")),
            episode_lineage: id(&format!("episode-{index}")),
            window_id: id("final-window"),
            decision_at: 20,
            actions: vec![id("action")],
        })
        .collect();
    let rows: Vec<_> = (0..128)
        .map(|index| OpeRow {
            decision_id: id(&format!("decision-{index}")),
            chosen_action: id("action"),
            complete_candidates: true,
            actions: vec![OpeAction {
                action_id: id("action"),
                behavior_probability: ProbabilityQ32::from_raw(1 << 32)
                    .unwrap_or_else(|error| panic!("probability: {error:?}")),
                evaluation_probability: ProbabilityQ32::from_raw(1 << 32)
                    .unwrap_or_else(|error| panic!("probability: {error:?}")),
                predicted_outcome: FixedQ32::ZERO,
            }],
            finalized_outcome: Some(outcome),
            outcome_observed_at: 50,
            outcome_evidence: digest(channel),
            outcome_model_evidence: digest("replaced-model"),
        })
        .collect();
    let assignments = (0..128)
        .map(|index| ClusterAssignment {
            decision_id: id(&format!("decision-{index}")),
            cluster_id: id(&format!("cluster-{index}")),
        })
        .collect();
    TemporalComparisonInputsV1 {
        training,
        targets,
        candidate_observations: rows.clone(),
        baseline_observations: rows,
        assignments,
        snapshot_ids: vec![id("snapshot")],
        future_window_ids: vec![id("final-window")],
    }
}

fn channel(name: &str, data: &TemporalComparisonInputsV1) -> ProductOutcomeChannelContractV1 {
    ProductOutcomeChannelContractV1 {
        metric_id: id(name),
        channel_id: id(name),
        schema_digest: digest("scalar-schema"),
        unit_id: id("unit-interval"),
        normalization_digest: digest("identity-normalization"),
        subgroup_digest: digest("all-enrolled"),
        window_id: id("final-window"),
        measurement_start_micros: 20,
        measurement_end_micros: 100,
        provenance_digest: digest(&format!("custodian-{name}")),
        inputs_digest: product_outcome_inputs_digest_v1(data)
            .unwrap_or_else(|error| panic!("input digest: {error:?}")),
        candidate_plan: temporal(&format!("{name}-candidate")),
        baseline_plan: temporal(&format!("{name}-baseline")),
    }
}

fn freeze(
    channels: Vec<ProductOutcomeChannelContractV1>,
    roles: Vec<MetricRoleContractV2>,
) -> Result<ProductFrozenOutcomePlanV1, ProductEvaluationError> {
    let metrics: Vec<_> = channels
        .iter()
        .map(|row| MetricContractV1 {
            metric_id: row.metric_id.clone(),
            direction: EvaluationDirectionV1::Maximize,
            safety_floor: Some(FixedQ32::ZERO),
        })
        .collect();
    let sources = channels
        .iter()
        .map(|row| ProductMetricSourceContractV1 {
            metric_id: row.metric_id.clone(),
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
    freeze_product_outcome_plan_v1(
        CrossFoldPlanV1 {
            plan_id: id("selected-host-outcome-plan"),
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
            final_holdout_digest: digest("outcome-manifest"),
        },
        roles,
        sources,
        channels,
    )
}

pub struct OutcomeProvider {
    batch: Vec<ProductOutcomeInputV1>,
}

impl FinalOutcomeHoldoutProviderV1 for OutcomeProvider {
    fn manifest_digest(&mut self) -> Result<Digest32, ProductProviderErrorV1> {
        Ok(digest("outcome-manifest"))
    }

    fn release_after_consumption(
        &mut self,
        _receipt: &FinalHoldoutJournalReceiptV1,
    ) -> Result<Vec<ProductOutcomeInputV1>, ProductProviderErrorV1> {
        Ok(std::mem::take(&mut self.batch))
    }
}

pub fn fixture() -> (
    ProductFrozenOutcomePlanV1,
    OutcomeProvider,
    Vec<MetricRoleContractV2>,
) {
    let data = [
        inputs("accuracy", FixedQ32::ONE),
        inputs("cost", FixedQ32::ZERO),
    ];
    let channels = vec![channel("accuracy", &data[0]), channel("cost", &data[1])];
    let roles: Vec<_> = channels
        .iter()
        .map(|row| MetricRoleContractV2 {
            metric_id: row.metric_id.clone(),
            role: MetricRoleV2::PrimarySuperiority {
                minimum_improvement: FixedQ32::ZERO,
            },
        })
        .collect();
    let plan = freeze(channels, roles.clone())
        .unwrap_or_else(|error| panic!("frozen outcome plan: {error:?}"));
    let batch = plan
        .channels()
        .iter()
        .zip(data)
        .map(|(contract, inputs)| ProductOutcomeInputV1 {
            channel_id: contract.channel_id.clone(),
            contract_digest: contract
                .canonical_digest()
                .unwrap_or_else(|error| panic!("contract digest: {error:?}")),
            inputs,
        })
        .collect();
    (plan, OutcomeProvider { batch }, roles)
}
