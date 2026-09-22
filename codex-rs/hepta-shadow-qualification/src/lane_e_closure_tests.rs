use codex_hepta_bellman_operator::BellmanReferenceCellV1;
use codex_hepta_bellman_operator::BellmanReferencePlanV1;
use codex_hepta_bellman_operator::WorldModelSampleV1;
use codex_hepta_bellman_operator::evaluate_bellman_reference;
use codex_hepta_bellman_operator::fit_transition_model;
use codex_hepta_intelligence_eval::ClusterAssignment;
use codex_hepta_intelligence_eval::ClusterConfidencePlan;
use codex_hepta_intelligence_eval::CrossFoldPartitionV1;
use codex_hepta_intelligence_eval::CrossFoldPlanV1;
use codex_hepta_intelligence_eval::EvaluationClaimScopeV1;
use codex_hepta_intelligence_eval::EvaluationDirectionV1;
use codex_hepta_intelligence_eval::FencedFinalHoldoutOwnerV1;
use codex_hepta_intelligence_eval::FinalHoldoutCasRecordV1;
use codex_hepta_intelligence_eval::FinalHoldoutCasStoreError;
use codex_hepta_intelligence_eval::FinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::FinalHoldoutJournalReceiptV1;
use codex_hepta_intelligence_eval::HeldOutTarget;
use codex_hepta_intelligence_eval::HoldoutWriterFenceV1;
use codex_hepta_intelligence_eval::IndependentEvaluationDispositionV1;
use codex_hepta_intelligence_eval::MetricContractV1;
use codex_hepta_intelligence_eval::MetricRoleContractV2;
use codex_hepta_intelligence_eval::MetricRoleV2;
use codex_hepta_intelligence_eval::OpeAction;
use codex_hepta_intelligence_eval::OpePlan;
use codex_hepta_intelligence_eval::OpeRow;
use codex_hepta_intelligence_eval::OutcomeTrainingSample;
use codex_hepta_intelligence_eval::ProductEvaluationRunnerV1;
use codex_hepta_intelligence_eval::ProductEvidenceSinkErrorV1;
use codex_hepta_intelligence_eval::ProductMetricSourceContractV1;
use codex_hepta_intelligence_eval::ProductMetricSourceV1;
use codex_hepta_intelligence_eval::ProductProviderErrorV1;
use codex_hepta_intelligence_eval::ProductQualificationContextV1;
use codex_hepta_intelligence_eval::ProductQualificationEvidenceSinkV1;
use codex_hepta_intelligence_eval::ProductTimingEvidenceV1;
use codex_hepta_intelligence_eval::SignedEvaluationDecisionV1;
use codex_hepta_intelligence_eval::SignedEvaluationEvidenceV1;
use codex_hepta_intelligence_eval::TemporalComparisonInputsV1;
use codex_hepta_intelligence_eval::TemporalEvaluationPlan;
use codex_hepta_intelligence_eval::TemporalFoldPlan;
use codex_hepta_intelligence_eval::evaluation_signing_payload_v2;
use codex_hepta_intelligence_eval::freeze_product_evaluation_plan_v1;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactLifecycleEventV1;
use codex_hepta_learning_artifacts::ArtifactLifecycleStateV1;
use codex_hepta_learning_artifacts::DatasetWithdrawalRegistry;
use codex_hepta_learning_artifacts::DatasetWithdrawalRegistryBindingV1;
use codex_hepta_learning_artifacts::LearningArtifactManifestV2;
use codex_hepta_learning_artifacts::ProvenanceModeV1;
use codex_hepta_learning_artifacts::validate_artifact_lifecycle_transition;
use codex_hepta_learning_ledger::AuthenticatedOutcomeV1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
use codex_hepta_learning_ledger::CreditAllocationBatchV1;
use codex_hepta_learning_ledger::CreditAllocationV1;
use codex_hepta_learning_ledger::DatasetFreezeRequestV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::OutcomeTerminalityV1;
use codex_hepta_learning_ledger::OutcomeWatermarkV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_learning_ledger::finalize_credit_batch;
use codex_hepta_learning_ledger::freeze_dataset;
use codex_hepta_learning_ledger::validate_authenticated_outcome;
use codex_hepta_learning_ledger::validate_candidate_set_completeness;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn id(value: &str) -> StableId {
    match StableId::new(value.to_owned()) {
        Ok(value) => value,
        Err(error) => panic!("invalid test id {value}: {error}"),
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    match Generation::new(value) {
        Ok(value) => value,
        Err(error) => panic!("invalid test generation {value}: {error}"),
    }
}

fn actor(name: &str, credential: &str, key: &str) -> AuthenticatedPrincipalV1 {
    AuthenticatedPrincipalV1 {
        principal_id: id(name),
        credential_chain_digest: digest(credential),
        signing_key_digest: digest(key),
        scope_digest: digest(&format!("scope-{name}")),
        authority_epoch: 8,
        authenticated_at: 10,
        expires_at: 100,
    }
}

fn sign_learning_evidence(
    principal: &AuthenticatedPrincipalV1,
    key: &SigningKey,
    role: LearningEvidenceRoleV1,
    verifier: &LearningEvidenceVerifierV1,
    objective_digest: Digest32,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: principal.principal_id.clone(),
        principal_id: principal.principal_id.clone(),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: principal.scope_digest,
        objective_digest,
        authority_epoch: principal.authority_epoch,
        issued_at: 20,
        expires_at: 90,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    evidence
}

#[derive(Default)]
struct LocalCas {
    state: Option<FinalHoldoutCasRecordV1>,
}

impl FinalHoldoutCasStoreV1 for LocalCas {
    fn load(
        &mut self,
        binding: Digest32,
    ) -> Result<Option<FinalHoldoutCasRecordV1>, FinalHoldoutCasStoreError> {
        if self
            .state
            .as_ref()
            .is_some_and(|record| record.binding != binding)
        {
            return Err(FinalHoldoutCasStoreError::Conflict);
        }
        Ok(self.state.clone())
    }

    fn compare_and_swap(
        &mut self,
        binding: Digest32,
        expected: Option<Digest32>,
        next: &FinalHoldoutCasRecordV1,
    ) -> Result<(), FinalHoldoutCasStoreError> {
        if next.binding != binding
            || self.state.as_ref().map(|record| record.state_digest) != expected
        {
            return Err(FinalHoldoutCasStoreError::Conflict);
        }
        self.state = Some(next.clone());
        Ok(())
    }
}

struct EvalProvider {
    inputs: Option<TemporalComparisonInputsV1>,
}

impl codex_hepta_intelligence_eval::FinalHoldoutProviderV1 for EvalProvider {
    fn manifest_digest(&mut self) -> Result<Digest32, ProductProviderErrorV1> {
        Ok(digest("final-holdout"))
    }

    fn release_after_consumption(
        &mut self,
        _receipt: &FinalHoldoutJournalReceiptV1,
    ) -> Result<TemporalComparisonInputsV1, ProductProviderErrorV1> {
        self.inputs.take().ok_or(ProductProviderErrorV1::Rejected)
    }
}

struct EvalSink;

impl ProductQualificationEvidenceSinkV1 for EvalSink {
    fn persist(
        &mut self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
        let mut bytes = b"lane-e.product-qualification-publication.v1".to_vec();
        bytes.extend_from_slice(execution_digest.as_array());
        bytes.extend_from_slice(decision.decision.evidence_digest.as_array());
        Ok(Digest32::of_bytes(&bytes))
    }
}

fn temporal_plan(name: &str, objective_digest: Digest32) -> TemporalEvaluationPlan {
    let mut plan = TemporalEvaluationPlan {
        plan_digest: Digest32::ZERO,
        evaluation_id: id(&format!("{name}-evaluation")),
        objective_digest,
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
        Ok(value) => value,
        Err(error) => panic!("canonical temporal plan failed: {error}"),
    };
    plan
}

fn evaluation_inputs(outcome_digest: Digest32) -> TemporalComparisonInputsV1 {
    let mut training = Vec::new();
    for action in ["a", "b"] {
        for index in 0..2 {
            training.push(OutcomeTrainingSample {
                decision_id: id(&format!("evaluation-train-{action}-{index}")),
                principal_lineage: id(&format!("evaluation-train-principal-{action}-{index}")),
                episode_lineage: id(&format!("evaluation-train-episode-{action}-{index}")),
                window_id: id(&format!("evaluation-train-window-{action}-{index}")),
                action_id: id(action),
                outcome: if action == "a" {
                    FixedQ32::ONE
                } else {
                    FixedQ32::ZERO
                },
                observed_at: 5,
                evidence_digest: digest("evaluation-training-evidence"),
            });
        }
    }
    let mut targets = Vec::new();
    let mut candidate_observations = Vec::new();
    let mut baseline_observations = Vec::new();
    let mut assignments = Vec::new();
    for index in 0..1024 {
        let decision_id = id(&format!("evaluation-decision-{index}"));
        targets.push(HeldOutTarget {
            decision_id: decision_id.clone(),
            principal_lineage: id(&format!("evaluation-principal-{index}")),
            episode_lineage: id(&format!("evaluation-episode-{index}")),
            window_id: id("window-2"),
            decision_at: 20,
            actions: vec![id("a"), id("b")],
        });
        let observation = |a_probability: u64, b_probability: u64| OpeRow {
            decision_id: decision_id.clone(),
            chosen_action: id("a"),
            complete_candidates: true,
            actions: vec![
                OpeAction {
                    action_id: id("a"),
                    behavior_probability: ProbabilityQ32::from_raw(1 << 31)
                        .unwrap_or_else(|error| panic!("behavior probability: {error}")),
                    evaluation_probability: ProbabilityQ32::from_raw(a_probability)
                        .unwrap_or_else(|error| panic!("evaluation probability: {error}")),
                    predicted_outcome: FixedQ32::ZERO,
                },
                OpeAction {
                    action_id: id("b"),
                    behavior_probability: ProbabilityQ32::from_raw(1 << 31)
                        .unwrap_or_else(|error| panic!("behavior probability: {error}")),
                    evaluation_probability: ProbabilityQ32::from_raw(b_probability)
                        .unwrap_or_else(|error| panic!("evaluation probability: {error}")),
                    predicted_outcome: FixedQ32::ZERO,
                },
            ],
            finalized_outcome: Some(FixedQ32::ONE),
            outcome_observed_at: 50,
            outcome_evidence: outcome_digest,
            outcome_model_evidence: digest("ignored-caller-model"),
        };
        candidate_observations.push(observation(3 << 30, 1 << 30));
        baseline_observations.push(observation(1 << 30, 3 << 30));
        assignments.push(ClusterAssignment {
            decision_id,
            cluster_id: id(&format!("evaluation-cluster-{index}")),
        });
    }
    TemporalComparisonInputsV1 {
        training,
        targets,
        candidate_observations,
        baseline_observations,
        assignments,
        snapshot_ids: vec![id("dataset-1")],
        future_window_ids: vec![id("window-2")],
    }
}

fn bellman_cell(
    sensor: &str,
    action: &str,
    reward: i64,
    continuation: i64,
) -> BellmanReferenceCellV1 {
    BellmanReferenceCellV1 {
        sensor_id: id(sensor),
        action_id: id(action),
        reward: FixedQ32::from_raw(reward),
        continuation_value: FixedQ32::from_raw(continuation),
        terminal: false,
        evidence_digest: digest(&format!("cell-{sensor}-{action}")),
    }
}

#[test]
fn lane_e_causal_candidate_chain_is_digest_bound_and_deny_all() {
    let generator_key = SigningKey::from_bytes(&[11; 32]);
    let evaluator_key = SigningKey::from_bytes(&[22; 32]);
    let mut generator = actor("generator", "generator-credential", "generator-key");
    let observer = actor("observer", "observer-credential", "observer-key");
    let mut evaluator = actor("evaluator", "evaluator-credential", "evaluator-key");
    let evaluation_scope = digest("lane-e-evaluation-scope");
    generator.scope_digest = evaluation_scope;
    evaluator.scope_digest = evaluation_scope;
    generator.signing_key_digest = Digest32::of_bytes(&generator_key.verifying_key().to_bytes());
    evaluator.signing_key_digest = Digest32::of_bytes(&evaluator_key.verifying_key().to_bytes());

    let candidate_receipt = CandidateSetCompletenessReceiptV1 {
        set_id: id("candidate-set-1"),
        state_digest: digest("decision-state"),
        generator_id: id("candidate-generator-1"),
        generator_code_digest: digest("generator-code"),
        grammar_digest: digest("candidate-grammar"),
        hard_filter_digest: digest("hard-filter"),
        truncation_digest: digest("truncation"),
        candidates_digest: digest("candidate-bytes"),
        candidate_count: 2,
        omitted_count_bound: 0,
        canonical_order_digest: digest("candidate-order"),
        complete_for_generator: true,
    };
    let candidate_digest = match validate_candidate_set_completeness(&candidate_receipt) {
        Ok(digest) => digest,
        Err(error) => panic!("candidate completeness failed: {error}"),
    };

    let outcome = AuthenticatedOutcomeV1 {
        record_id: id("outcome-record-1"),
        outcome_id: id("outcome-1"),
        episode_id: id("episode-1"),
        observer,
        observed_at: Some(40),
        value: Some(FixedQ32::from_raw(100)),
        unit_profile_digest: digest("utility-unit"),
        support_digest: digest("outcome-support"),
        watermark: OutcomeWatermarkV1 {
            latest_observable_at: 45,
            expected_delay_profile_digest: digest("delay-profile"),
            terminality: OutcomeTerminalityV1::Terminal,
            censoring_reason: None,
            correction_predecessor: None,
            finalized_at: Some(46),
        },
    };
    let outcome_digest = match validate_authenticated_outcome(&generator, &outcome, 50) {
        Ok(digest) => digest,
        Err(error) => panic!("authenticated outcome failed: {error}"),
    };

    let credit = match finalize_credit_batch(
        CreditAllocationBatchV1 {
            batch_id: id("credit-batch-1"),
            episode_id: id("episode-1"),
            outcome_id: id("outcome-1"),
            allocator: evaluator.clone(),
            terminal_outcome: FixedQ32::from_raw(100),
            allocations: vec![CreditAllocationV1 {
                target_id: id("candidate-1"),
                credit: FixedQ32::from_raw(100),
            }],
            conservation_residual: FixedQ32::ZERO,
            support_digest: digest("credit-support"),
            finalized: true,
        },
        50,
    ) {
        Ok(receipt) => receipt,
        Err(error) => panic!("credit conservation failed: {error}"),
    };
    assert!(!credit.authority.grants_any());

    let dataset = match freeze_dataset(
        DatasetFreezeRequestV1 {
            snapshot_id: id("dataset-1"),
            producer: evaluator.clone(),
            ledger_head_digest: digest("ledger-head"),
            objective_digest: digest("objective"),
            eligible_frontier: 3,
            outcome_watermark: 45,
            correction_cut_digest: digest("correction-cut"),
            revocation_cut_digest: digest("revocation-cut"),
            inclusion_policy_digest: digest("inclusion-policy"),
            source_record_digests: vec![candidate_digest, outcome_digest, credit.batch_digest],
            pending_outcomes: 0,
            censored_outcomes: 0,
        },
        50,
    ) {
        Ok(snapshot) => snapshot,
        Err(error) => panic!("dataset freeze failed: {error}"),
    };
    assert!(!dataset.authority.grants_any());

    let world_model = match fit_transition_model(
        id("world-model-1"),
        dataset.dataset_digest,
        vec![WorldModelSampleV1 {
            sample_id: id("sample-1"),
            state_id: id("state-1"),
            action_id: id("candidate-1"),
            next_state_id: id("state-2"),
            outcome: FixedQ32::from_raw(100),
            evidence_digest: outcome_digest,
        }],
    ) {
        Ok(model) => model,
        Err(error) => panic!("world-model fit failed: {error}"),
    };
    assert!(!world_model.authority.grants_any());

    let bellman = match evaluate_bellman_reference(BellmanReferencePlanV1 {
        plan_id: id("bellman-reference-1"),
        objective_digest: digest("objective"),
        sensor_core_digest: digest("sensor-core"),
        gamma: FixedQ32::ONE,
        sensor_ids: vec![id("sensor-1"), id("sensor-2")],
        action_ids: vec![id("candidate-1"), id("candidate-2")],
        cells: vec![
            bellman_cell("sensor-1", "candidate-1", 10, 20),
            bellman_cell("sensor-1", "candidate-2", 5, 20),
            bellman_cell("sensor-2", "candidate-1", 20, 20),
            bellman_cell("sensor-2", "candidate-2", 10, 20),
        ],
    }) {
        Ok(receipt) => receipt,
        Err(error) => panic!("Bellman reference failed: {error}"),
    };
    assert!(!bellman.authority.grants_any());

    let artifact_id = id("candidate-1");
    let producer_id = generator.principal_id.clone();
    let withdrawal_registry = DatasetWithdrawalRegistry::new(DatasetWithdrawalRegistryBindingV1 {
        registry_id: id("dataset-withdrawals"),
        scope_digest: digest("lane-e-qualification"),
        authority_id: id("dataset-owner"),
    })
    .expect("valid withdrawal registry binding");
    let artifact = match withdrawal_registry.admit_manifest(
        LearningArtifactManifestV2 {
            artifact_id: artifact_id.clone(),
            kind: ArtifactKind::Model,
            generation: generation(1),
            provenance_mode: ProvenanceModeV1::DatasetDerived,
            source_dataset_digests: vec![dataset.dataset_digest],
            lineage_digests: vec![
                candidate_digest,
                outcome_digest,
                credit.batch_digest,
                world_model.model_digest,
                bellman.evidence_digest,
            ],
            predecessor_ids: Vec::new(),
            rollback_predecessor: None,
            bytes_digest: digest("artifact-bytes"),
            encoded_size_bytes: 1024,
            training_code_digest: digest("training-code"),
            runtime_tuple_digest: digest("runtime-tuple"),
            device_profile_digest: digest("device-profile"),
            objective_class_digest: digest("objective"),
            compatibility_digest: digest("compatibility"),
            schema_profile_digest: digest("schema-profile"),
            normalization_digest: digest("normalization"),
            producer_id: producer_id.clone(),
            created_at: 47,
            expires_at: 100,
        },
        50,
    ) {
        Ok(artifact) => artifact,
        Err(error) => panic!("artifact admission failed: {error}"),
    };
    assert!(!artifact.authority.grants_any());

    let objective_digest = digest("objective");
    let metric_roles = vec![MetricRoleContractV2 {
        metric_id: id("task-utility"),
        role: MetricRoleV2::PrimarySuperiority {
            minimum_improvement: FixedQ32::ZERO,
        },
    }];
    let candidate_plan = temporal_plan("candidate", objective_digest);
    let baseline_plan = temporal_plan("baseline", objective_digest);
    let frozen_plan = match freeze_product_evaluation_plan_v1(
        CrossFoldPlanV1 {
            plan_id: id("evaluation-plan"),
            claim_scope: EvaluationClaimScopeV1::Qualification,
            candidate_id: artifact_id.clone(),
            baseline_id: id("baseline-1"),
            objective_digest,
            dataset_digest: dataset.dataset_digest,
            estimand_digest: digest("qualification-task-utility"),
            metric_contracts: vec![MetricContractV1 {
                metric_id: id("task-utility"),
                direction: EvaluationDirectionV1::Maximize,
                safety_floor: Some(FixedQ32::ZERO),
            }],
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            folds: vec![
                CrossFoldPartitionV1 {
                    fold_id: id("evaluation-fold-1"),
                    training_principals: vec![id("evaluation-training-principal-1")],
                    training_episodes: vec![id("evaluation-training-episode-1")],
                    training_windows: vec![id("evaluation-training-window-1")],
                    holdout_principals: vec![id("evaluation-holdout-principal-1")],
                    holdout_episodes: vec![id("evaluation-holdout-episode-1")],
                    holdout_windows: vec![id("window-1")],
                    model_digest: digest("evaluation-model-1"),
                    predictions_digest: digest("evaluation-predictions-1"),
                },
                CrossFoldPartitionV1 {
                    fold_id: id("evaluation-fold-2"),
                    training_principals: vec![id("evaluation-training-principal-2")],
                    training_episodes: vec![id("evaluation-training-episode-2")],
                    training_windows: vec![id("evaluation-training-window-2")],
                    holdout_principals: vec![id("evaluation-holdout-principal-2")],
                    holdout_episodes: vec![id("evaluation-holdout-episode-2")],
                    holdout_windows: vec![id("window-2")],
                    model_digest: digest("evaluation-model-2"),
                    predictions_digest: digest("evaluation-predictions-2"),
                },
            ],
            final_holdout_window_id: id("window-2"),
            final_holdout_digest: digest("final-holdout"),
        },
        metric_roles.clone(),
        vec![ProductMetricSourceContractV1 {
            metric_id: id("task-utility"),
            source: ProductMetricSourceV1::DoublyRobust,
        }],
        &candidate_plan,
        &baseline_plan,
    ) {
        Ok(value) => value,
        Err(error) => panic!("product evaluation plan failed: {error}"),
    };
    let owner = match FencedFinalHoldoutOwnerV1::initialize(
        LocalCas::default(),
        digest("lane-e-final-holdout-owner"),
        HoldoutWriterFenceV1 {
            owner_id: id("learning-eval-owner"),
            generation: 1,
            lease_digest: digest("learning-eval-lease"),
        },
    ) {
        Ok(value) => value,
        Err(error) => panic!("fenced holdout owner failed: {error}"),
    };
    let mut runner = ProductEvaluationRunnerV1::new(owner);
    let mut provider = EvalProvider {
        inputs: Some(evaluation_inputs(outcome_digest)),
    };
    let temporal = match runner.evaluate_temporal_comparison(
        &frozen_plan,
        &candidate_plan,
        &baseline_plan,
        &mut provider,
    ) {
        Ok(value) => value,
        Err(error) => panic!("temporal product evaluation failed: {error}"),
    };

    let verifier = match LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: evaluation_scope,
        objective_digest,
        authority_epoch: 8,
        signers: vec![
            TrustedLearningSignerV1 {
                principal: generator.clone(),
                controller_id: id("generator-controller"),
                verifying_key: generator_key.verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Generator],
                revoked_at: None,
            },
            TrustedLearningSignerV1 {
                principal: evaluator.clone(),
                controller_id: id("evaluator-controller"),
                verifying_key: evaluator_key.verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Evaluator],
                revoked_at: None,
            },
        ],
    }) {
        Ok(value) => value,
        Err(error) => panic!("host-owned evaluation trust failed: {error}"),
    };
    let context = ProductQualificationContextV1 {
        generator: generator.clone(),
        evaluator: evaluator.clone(),
        retention_receipt_digests: Vec::new(),
        unlearning_receipt_digest: Digest32::ZERO,
    };
    let bundle = match runner.qualification_bundle(&temporal, &context) {
        Ok(value) => value,
        Err(error) => panic!("qualification bundle failed: {error}"),
    };
    let evaluation_payload = match evaluation_signing_payload_v2(&bundle, &metric_roles) {
        Ok(value) => value,
        Err(error) => panic!("evaluation signing payload failed: {error}"),
    };
    let evidence = SignedEvaluationEvidenceV1 {
        generator_plan: sign_learning_evidence(
            &generator,
            &generator_key,
            LearningEvidenceRoleV1::Generator,
            &verifier,
            objective_digest,
            bundle.frozen_plan.plan_digest.as_array(),
        ),
        evaluator_bundle: sign_learning_evidence(
            &evaluator,
            &evaluator_key,
            LearningEvidenceRoleV1::Evaluator,
            &verifier,
            objective_digest,
            &evaluation_payload,
        ),
    };
    let mut sink = EvalSink;
    let qualification = match runner.qualify_and_persist(
        &temporal,
        &context,
        &evidence,
        ProductTimingEvidenceV1::Qualification,
        &verifier,
        50,
        &mut sink,
    ) {
        Ok(value) => value,
        Err(error) => panic!("product qualification failed: {error}"),
    };
    assert_eq!(
        qualification.decision.decision.disposition,
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection
    );
    assert!(!qualification.authority.grants_any());

    let trained_event = ArtifactLifecycleEventV1 {
        event_id: id("lifecycle-trained"),
        artifact_id: artifact_id.clone(),
        prior_state: ArtifactLifecycleStateV1::Proposed,
        next_state: ArtifactLifecycleStateV1::Trained,
        actor_id: producer_id.clone(),
        actor_credential_digest: generator.credential_chain_digest,
        evidence_digest: artifact.manifest_digest,
        authority_epoch: 8,
        occurred_at: 48,
    };
    assert!(validate_artifact_lifecycle_transition(&producer_id, &trained_event).is_ok());
    let evaluated_event = ArtifactLifecycleEventV1 {
        event_id: id("lifecycle-evaluated"),
        artifact_id,
        prior_state: ArtifactLifecycleStateV1::Trained,
        next_state: ArtifactLifecycleStateV1::Evaluated,
        actor_id: evaluator.principal_id,
        actor_credential_digest: evaluator.credential_chain_digest,
        evidence_digest: qualification.evidence_digest,
        authority_epoch: 8,
        occurred_at: 50,
    };
    assert!(validate_artifact_lifecycle_transition(&producer_id, &evaluated_event).is_ok());

    assert!(!withdrawal_registry.is_withdrawn(dataset.dataset_digest));
}
