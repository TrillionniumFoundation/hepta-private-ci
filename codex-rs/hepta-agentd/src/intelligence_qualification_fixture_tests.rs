//! Test fixtures run the actual fenced evaluation and persist its terminal evidence.
use super::*;
use codex_hepta_intelligence_eval::*;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use std::io::Write;

struct Provider {
    manifest: Digest32,
    inputs: Option<TemporalComparisonInputsV1>,
    release_count: usize,
}
impl FinalHoldoutProviderV1 for Provider {
    fn manifest_digest(&mut self) -> Result<Digest32, ProductProviderErrorV1> {
        Ok(self.manifest)
    }
    fn release_after_consumption(
        &mut self,
        receipt: &FinalHoldoutJournalReceiptV1,
    ) -> Result<TemporalComparisonInputsV1, ProductProviderErrorV1> {
        if receipt.sequence == 0 {
            return Err(ProductProviderErrorV1::Rejected);
        }
        self.release_count += 1;
        self.inputs.take().ok_or(ProductProviderErrorV1::Rejected)
    }
}
struct FileSink(std::fs::File);
impl ProductQualificationEvidenceSinkV1 for FileSink {
    fn persist(
        &mut self,
        execution: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
        let mut bytes = execution.as_array().to_vec();
        bytes.extend_from_slice(decision.decision.evidence_digest.as_array());
        bytes.extend_from_slice(decision.authentication_digest.as_array());
        self.0
            .write_all(&bytes)
            .and_then(|()| self.0.sync_all())
            .map_err(|_| ProductEvidenceSinkErrorV1::Indeterminate)?;
        Ok(Digest32::of_bytes(&bytes))
    }
}
struct Fixture {
    cross_fold: CrossFoldPlanV1,
    roles: Vec<MetricRoleContractV2>,
    sources: Vec<ProductMetricSourceContractV1>,
    candidate_plan: TemporalEvaluationPlan,
    baseline_plan: TemporalEvaluationPlan,
    provider: Provider,
}

fn temporal_plan(name: &str, objective: Digest32) -> TemporalEvaluationPlan {
    let mut plan = TemporalEvaluationPlan {
        plan_digest: Digest32::ZERO,
        evaluation_id: id(name),
        objective_digest: objective,
        fold: TemporalFoldPlan {
            plan_digest: digest(&format!("{name}-fold-plan")),
            fold_id: id(&format!("{name}-fold")),
            training_watermark: 10,
            evaluation_start: 20,
            minimum_per_action: 2,
        },
        ope: OpePlan {
            plan_digest: digest(&format!("{name}-ope-plan")),
            outcome_watermark: 100,
            minimum_rows: 2,
            minimum_ess: FixedQ32::ONE,
            // Prespecified legal-action ratio ceiling for these frozen policies.
            maximum_weight: FixedQ32::from_raw(3_i64 << 31),
        },
        confidence: ClusterConfidencePlan {
            plan_digest: digest(&format!("{name}-confidence-plan")),
            assumptions_digest: digest("independent-clusters"),
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            minimum_clusters: 2,
        },
    };
    plan.plan_digest = match plan.canonical_digest() {
        Ok(digest) => digest,
        Err(error) => panic!("canonical temporal plan: {error}"),
    };
    plan
}

fn fixture(binding: &AgentdEvaluationBindingV1) -> Fixture {
    let objective = binding.objective_digest;
    let manifest = digest("final-holdout");
    let candidate_plan = temporal_plan("candidate-evaluation", objective);
    let baseline_plan = temporal_plan("baseline-evaluation", objective);
    let cross_fold = CrossFoldPlanV1 {
        plan_id: id("product-plan"),
        claim_scope: EvaluationClaimScopeV1::Qualification,
        candidate_id: binding.selected_candidate_id.clone(),
        baseline_id: id("baseline"),
        objective_digest: objective,
        dataset_digest: digest("dataset"),
        estimand_digest: digest("task-success-estimand"),
        metric_contracts: vec![MetricContractV1 {
            metric_id: id("task-success"),
            direction: EvaluationDirectionV1::Maximize,
            safety_floor: Some(FixedQ32::ZERO),
        }],
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 1,
        folds: vec![
            CrossFoldPartitionV1 {
                fold_id: id("fold-a"),
                training_principals: vec![id("train-principal-a")],
                training_episodes: vec![id("train-episode-a")],
                training_windows: vec![id("past-a")],
                holdout_principals: vec![id("holdout-principal-a")],
                holdout_episodes: vec![id("holdout-episode-a")],
                holdout_windows: vec![id("final-window")],
                model_digest: digest("model-a"),
                predictions_digest: digest("predictions-a"),
            },
            CrossFoldPartitionV1 {
                fold_id: id("fold-b"),
                training_principals: vec![id("train-principal-b")],
                training_episodes: vec![id("train-episode-b")],
                training_windows: vec![id("past-b")],
                holdout_principals: vec![id("holdout-principal-b")],
                holdout_episodes: vec![id("holdout-episode-b")],
                holdout_windows: vec![id("other-window")],
                model_digest: digest("model-b"),
                predictions_digest: digest("predictions-b"),
            },
        ],
        final_holdout_window_id: id("final-window"),
        final_holdout_digest: manifest,
    };
    let roles = vec![MetricRoleContractV2 {
        metric_id: id("task-success"),
        role: MetricRoleV2::PrimarySuperiority {
            minimum_improvement: FixedQ32::ZERO,
        },
    }];
    let sources = vec![ProductMetricSourceContractV1 {
        metric_id: id("task-success"),
        source: ProductMetricSourceV1::DoublyRobust,
    }];

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
    for index in 0..1024 {
        let decision = id(&format!("decision-{index}"));
        targets.push(HeldOutTarget {
            decision_id: decision.clone(),
            principal_lineage: id(&format!("principal-{index}")),
            episode_lineage: id(&format!("episode-{index}")),
            window_id: id("final-window"),
            decision_at: 20,
            actions: vec![id("a"), id("b")],
        });
        let make = |candidate: bool| OpeRow {
            decision_id: decision.clone(),
            chosen_action: id("a"),
            complete_candidates: true,
            actions: vec![
                OpeAction {
                    action_id: id("a"),
                    behavior_probability: match ProbabilityQ32::from_raw(1 << 31) {
                        Ok(value) => value,
                        Err(error) => panic!("behavior probability: {error}"),
                    },
                    evaluation_probability: match ProbabilityQ32::from_raw(if candidate {
                        3 << 30
                    } else {
                        1 << 30
                    }) {
                        Ok(value) => value,
                        Err(error) => panic!("evaluation probability: {error}"),
                    },
                    predicted_outcome: FixedQ32::ZERO,
                },
                OpeAction {
                    action_id: id("b"),
                    behavior_probability: match ProbabilityQ32::from_raw(1 << 31) {
                        Ok(value) => value,
                        Err(error) => panic!("behavior probability: {error}"),
                    },
                    evaluation_probability: match ProbabilityQ32::from_raw(if candidate {
                        1 << 30
                    } else {
                        3 << 30
                    }) {
                        Ok(value) => value,
                        Err(error) => panic!("evaluation probability: {error}"),
                    },
                    predicted_outcome: FixedQ32::ZERO,
                },
            ],
            finalized_outcome: Some(FixedQ32::ONE),
            outcome_observed_at: 50,
            outcome_evidence: digest("heldout-outcome"),
            outcome_model_evidence: digest("ignored-model"),
        };
        candidate_observations.push(make(true));
        baseline_observations.push(make(false));
        assignments.push(ClusterAssignment {
            decision_id: decision,
            cluster_id: id(&format!("cluster-{index}")),
        });
    }
    Fixture {
        cross_fold,
        roles,
        sources,
        candidate_plan,
        baseline_plan,
        provider: Provider {
            manifest,
            inputs: Some(TemporalComparisonInputsV1 {
                training,
                targets,
                candidate_observations,
                baseline_observations,
                assignments,
                snapshot_ids: vec![id("snapshot-1")],
                future_window_ids: vec![id("final-window")],
            }),
            release_count: 0,
        },
    }
}

pub(super) fn qualify(
    binding: &AgentdEvaluationBindingV1,
    generator: &AuthenticatedPrincipalV1,
    evaluator: &AuthenticatedPrincipalV1,
    trust: &ActivatedLearningTrustV1,
    generator_key: &SigningKey,
    evaluator_key: &SigningKey,
    now: u64,
) -> ProductQualificationReceiptV1 {
    let mut fixture = fixture(binding);
    let frozen = freeze_product_evaluation_plan_v1(
        fixture.cross_fold,
        fixture.roles.clone(),
        fixture.sources,
        &fixture.candidate_plan,
        &fixture.baseline_plan,
    )
    .unwrap();
    let scope = digest("actual-test-holdout-owner");
    let store =
        LockedFileFinalHoldoutCasStoreV1::create(tempfile::tempfile().unwrap(), scope).unwrap();
    let owner = FencedFinalHoldoutOwnerV1::initialize(
        store,
        scope,
        HoldoutWriterFenceV1 {
            owner_id: id("evaluation-owner"),
            generation: 1,
            lease_digest: digest("lease"),
        },
    )
    .unwrap();
    let mut runner = ProductEvaluationRunnerV1::new(owner);
    let temporal = runner
        .evaluate_temporal_comparison(
            &frozen,
            &fixture.candidate_plan,
            &fixture.baseline_plan,
            &mut fixture.provider,
        )
        .unwrap();
    assert_eq!(fixture.provider.release_count, 1);
    let context = ProductQualificationContextV1 {
        generator: generator.clone(),
        evaluator: evaluator.clone(),
        retention_receipt_digests: Vec::new(),
        unlearning_receipt_digest: Digest32::ZERO,
    };
    let bundle = runner.qualification_bundle(&temporal, &context).unwrap();
    let payload = evaluation_signing_payload_v2(&bundle, &fixture.roles).unwrap();
    let evidence = SignedEvaluationEvidenceV1 {
        generator_plan: sign(
            trust.verifier(),
            generator,
            generator_key,
            LearningEvidenceRoleV1::Generator,
            binding.objective_digest,
            bundle.frozen_plan.plan_digest.as_array(),
        ),
        evaluator_bundle: sign(
            trust.verifier(),
            evaluator,
            evaluator_key,
            LearningEvidenceRoleV1::Evaluator,
            binding.objective_digest,
            &payload,
        ),
    };
    let mut sink = FileSink(tempfile::tempfile().unwrap());
    let receipt = runner
        .qualify_and_persist(
            &temporal,
            &context,
            &evidence,
            ProductTimingEvidenceV1::Qualification,
            trust.verifier(),
            now,
            &mut sink,
        )
        .unwrap();
    assert_eq!(sink.0.metadata().unwrap().len(), 96);
    receipt.validate_integrity().unwrap();
    receipt
}
