use std::cell::RefCell;
use std::rc::Rc;

use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use pretty_assertions::assert_eq;

use crate::*;

fn id(value: &str) -> codex_hepta_types::StableId {
    codex_hepta_types::StableId::new(value).expect("test identity")
}
fn digest(value: &str) -> codex_hepta_types::Digest32 {
    codex_hepta_types::Digest32::of_bytes(value.as_bytes())
}

fn temporal(name: &str) -> TemporalEvaluationPlan {
    let mut plan = TemporalEvaluationPlan {
        plan_digest: codex_hepta_types::Digest32::ZERO,
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
    plan.plan_digest = plan.canonical_digest().expect("canonical plan");
    plan
}

fn inputs(channel: &str, outcome: FixedQ32) -> TemporalComparisonInputsV1 {
    let training = (0..2)
        .map(|index| OutcomeTrainingSample {
            decision_id: id(&format!("training-{index}")),
            principal_lineage: id(&format!("training-principal-{index}")),
            episode_lineage: id(&format!("training-episode-{index}")),
            window_id: id("training-window"),
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
                behavior_probability: ProbabilityQ32::from_raw(1 << 32).expect("probability"),
                evaluation_probability: ProbabilityQ32::from_raw(1 << 32).expect("probability"),
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
        inputs_digest: product_outcome_inputs_digest_v1(data).expect("input digest"),
        candidate_plan: temporal(&format!("{name}-candidate")),
        baseline_plan: temporal(&format!("{name}-baseline")),
    }
}

fn freeze(
    channels: Vec<ProductOutcomeChannelContractV1>,
) -> Result<ProductFrozenOutcomePlanV1, ProductEvaluationError> {
    let metrics: Vec<_> = channels
        .iter()
        .map(|row| MetricContractV1 {
            metric_id: row.metric_id.clone(),
            direction: EvaluationDirectionV1::Maximize,
            safety_floor: Some(FixedQ32::ZERO),
        })
        .collect();
    let roles = channels
        .iter()
        .map(|row| MetricRoleContractV2 {
            metric_id: row.metric_id.clone(),
            role: MetricRoleV2::PrimarySuperiority {
                minimum_improvement: FixedQ32::ZERO,
            },
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
            plan_id: id("outcome-plan"),
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
            final_holdout_digest: digest("manifest"),
        },
        roles,
        sources,
        channels,
    )
}

#[derive(Clone, Default)]
struct Store(Rc<RefCell<Option<FinalHoldoutCasRecordV1>>>);
impl FinalHoldoutCasStoreV1 for Store {
    fn load(
        &mut self,
        binding: codex_hepta_types::Digest32,
    ) -> Result<Option<FinalHoldoutCasRecordV1>, FinalHoldoutCasStoreError> {
        let record = self.0.borrow();
        if record
            .as_ref()
            .is_some_and(|value| value.binding != binding)
        {
            return Err(FinalHoldoutCasStoreError::Conflict);
        }
        Ok(record.clone())
    }
    fn compare_and_swap(
        &mut self,
        binding: codex_hepta_types::Digest32,
        expected: Option<codex_hepta_types::Digest32>,
        next: &FinalHoldoutCasRecordV1,
    ) -> Result<(), FinalHoldoutCasStoreError> {
        let mut record = self.0.borrow_mut();
        if next.binding != binding || record.as_ref().map(|value| value.state_digest) != expected {
            return Err(FinalHoldoutCasStoreError::Conflict);
        }
        *record = Some(next.clone());
        Ok(())
    }
}
fn runner() -> RecordedProductEvaluationRunnerV1<Store> {
    RecordedProductEvaluationRunnerV1::new(
        FencedFinalHoldoutOwnerV1::initialize(
            Store::default(),
            digest("namespace"),
            HoldoutWriterFenceV1 {
                owner_id: id("owner"),
                generation: 1,
                lease_digest: digest("lease"),
            },
        )
        .expect("owner"),
    )
}
struct Provider {
    batch: Vec<ProductOutcomeInputV1>,
    calls: usize,
}
impl FinalOutcomeHoldoutProviderV1 for Provider {
    fn manifest_digest(&mut self) -> Result<codex_hepta_types::Digest32, ProductProviderErrorV1> {
        Ok(digest("manifest"))
    }
    fn release_after_consumption(
        &mut self,
        _receipt: &FinalHoldoutJournalReceiptV1,
    ) -> Result<Vec<ProductOutcomeInputV1>, ProductProviderErrorV1> {
        self.calls += 1;
        Ok(std::mem::take(&mut self.batch))
    }
}
fn fixture() -> (ProductFrozenOutcomePlanV1, Provider) {
    let data = [
        inputs("accuracy", FixedQ32::ONE),
        inputs("cost", FixedQ32::ZERO),
    ];
    let channels = vec![channel("accuracy", &data[0]), channel("cost", &data[1])];
    let plan = freeze(channels).expect("frozen channel plan");
    let batch = plan
        .channels()
        .iter()
        .zip(data)
        .map(|(contract, inputs)| ProductOutcomeInputV1 {
            channel_id: contract.channel_id.clone(),
            contract_digest: contract.canonical_digest().expect("contract"),
            inputs,
        })
        .collect();
    (plan, Provider { batch, calls: 0 })
}

#[test]
fn measured_channels_with_same_estimator_have_distinct_intervals_and_one_consumption() {
    let (plan, mut provider) = fixture();
    let mut runner = runner();
    let mut journal = InMemoryProductEvaluationAttemptJournalV1::default();
    let receipt = runner
        .evaluate_outcome_comparison(id("attempt"), &plan, &mut provider, &mut journal)
        .expect("measured evaluation");
    assert_eq!(provider.calls, 1);
    assert_eq!(receipt.metric_gates().len(), 2);
    assert!(receipt.metric_gates()[0].candidate.lower > receipt.metric_gates()[1].candidate.upper);
    let latest = journal
        .latest(&id("attempt"))
        .expect("latest")
        .expect("sealed");
    assert_eq!(
        (latest.transition.phase, latest.transition.terminal_digest),
        (
            ProductEvaluationAttemptPhaseV1::ComparisonSealed,
            receipt.execution_digest()
        )
    );
    assert!(
        runner
            .evaluate_outcome_comparison(id("attempt"), &plan, &mut provider, &mut journal)
            .is_err()
    );
    assert_eq!(provider.calls, 1);
}

#[test]
fn swapping_payloads_without_changing_frozen_contracts_fails_after_consumption() {
    let (plan, mut provider) = fixture();
    let other = provider.batch[1].inputs.clone();
    provider.batch[1].inputs = provider.batch[0].inputs.clone();
    provider.batch[0].inputs = other;
    let mut journal = InMemoryProductEvaluationAttemptJournalV1::default();
    assert!(
        runner()
            .evaluate_outcome_comparison(id("attempt"), &plan, &mut provider, &mut journal)
            .is_err()
    );
    assert_eq!(
        journal
            .latest(&id("attempt"))
            .expect("latest")
            .expect("failure")
            .transition
            .phase,
        ProductEvaluationAttemptPhaseV1::Failed
    );
}

#[test]
fn incomplete_or_relabelled_channel_batches_do_not_seal_partial_results() {
    for mode in 0..3 {
        let (plan, mut provider) = fixture();
        match mode {
            0 => {
                provider.batch.pop();
            }
            1 => {
                provider.batch[1].channel_id = provider.batch[0].channel_id.clone();
            }
            2 => {
                provider.batch[1].contract_digest = digest("other-schema-or-unit");
            }
            _ => unreachable!(),
        }
        let mut journal = InMemoryProductEvaluationAttemptJournalV1::default();
        assert!(
            runner()
                .evaluate_outcome_comparison(id("attempt"), &plan, &mut provider, &mut journal)
                .is_err()
        );
        assert_eq!(
            journal
                .latest(&id("attempt"))
                .expect("latest")
                .expect("failure")
                .transition
                .phase,
            ProductEvaluationAttemptPhaseV1::Failed
        );
    }
}

#[test]
fn channel_semantic_mutations_change_the_frozen_estimand() {
    let (original, _) = fixture();
    for field in 0..11 {
        let mut channels = original.channels().to_vec();
        let row = &mut channels[0];
        match field {
            0 => row.channel_id = id("another-channel"),
            1 => row.schema_digest = digest("another-schema"),
            2 => row.unit_id = id("another-unit"),
            3 => row.normalization_digest = digest("another-normalization"),
            4 => row.subgroup_digest = digest("another-subgroup"),
            5 => row.provenance_digest = digest("another-custodian"),
            6 => row.inputs_digest = digest("another-input-set"),
            7 => {
                row.candidate_plan.evaluation_id = id("another-candidate-estimation");
                row.candidate_plan.plan_digest =
                    row.candidate_plan.canonical_digest().expect("digest");
            }
            8 => {
                row.baseline_plan.evaluation_id = id("another-baseline-estimation");
                row.baseline_plan.plan_digest =
                    row.baseline_plan.canonical_digest().expect("digest");
            }
            9 => {
                row.measurement_start_micros += 1;
            }
            10 => {
                row.measurement_end_micros -= 1;
            }
            _ => unreachable!(),
        }
        match freeze(channels) {
            Ok(changed) => assert_ne!(
                changed.frozen_plan().estimand_digest,
                original.frozen_plan().estimand_digest
            ),
            Err(_) => assert!(field >= 9),
        }
    }
}

#[test]
fn duplicate_measured_inputs_are_not_distinct_metric_channels() {
    let (plan, _) = fixture();
    let mut channels = plan.channels().to_vec();
    channels[1].inputs_digest = channels[0].inputs_digest;
    assert!(freeze(channels).is_err());
}

#[test]
fn payload_digest_is_order_independent_and_binds_values_and_lineage() {
    let data = inputs("accuracy", FixedQ32::ONE);
    let expected = product_outcome_inputs_digest_v1(&data).expect("digest");
    let mut reordered = data.clone();
    reordered.training.reverse();
    reordered.targets.reverse();
    reordered.assignments.reverse();
    reordered.candidate_observations.reverse();
    reordered.baseline_observations.reverse();
    assert_eq!(
        product_outcome_inputs_digest_v1(&reordered).expect("digest"),
        expected
    );
    for field in 0..8 {
        let mut changed = data.clone();
        match field {
            0 => changed.training[0].outcome = FixedQ32::ZERO,
            1 => changed.targets[0].principal_lineage = id("other-principal"),
            2 => changed.candidate_observations[0].finalized_outcome = Some(FixedQ32::ZERO),
            3 => changed.baseline_observations[0].outcome_evidence = digest("other-evidence"),
            4 => changed.assignments[0].cluster_id = id("other-cluster"),
            5 => changed.snapshot_ids[0] = id("other-snapshot"),
            6 => changed.future_window_ids[0] = id("other-window"),
            7 => changed.candidate_observations[0].actions[0].predicted_outcome = FixedQ32::ONE,
            _ => unreachable!(),
        }
        assert_ne!(
            product_outcome_inputs_digest_v1(&changed).expect("digest"),
            expected
        );
    }
    let mut duplicate = data;
    duplicate.assignments.push(duplicate.assignments[0].clone());
    assert!(product_outcome_inputs_digest_v1(&duplicate).is_err());
}
