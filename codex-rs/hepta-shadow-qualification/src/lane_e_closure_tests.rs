use codex_hepta_bellman_operator::BellmanReferenceCellV1;
use codex_hepta_bellman_operator::BellmanReferencePlanV1;
use codex_hepta_bellman_operator::WorldModelSampleV1;
use codex_hepta_bellman_operator::evaluate_bellman_reference;
use codex_hepta_bellman_operator::fit_transition_model;
use codex_hepta_intelligence_eval::CrossFoldPartitionV1;
use codex_hepta_intelligence_eval::CrossFoldPlanV1;
use codex_hepta_intelligence_eval::EvaluationClaimScopeV1;
use codex_hepta_intelligence_eval::EvaluationDirectionV1;
use codex_hepta_intelligence_eval::EvaluationIntervalV1;
use codex_hepta_intelligence_eval::FinalHoldoutRegistry;
use codex_hepta_intelligence_eval::IndependentEvaluationBundleV1;
use codex_hepta_intelligence_eval::IndependentEvaluationDispositionV1;
use codex_hepta_intelligence_eval::MetricContractV1;
use codex_hepta_intelligence_eval::MetricGateV1;
use codex_hepta_intelligence_eval::decide_independently;
use codex_hepta_intelligence_eval::freeze_cross_fold_plan;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactLifecycleEventV1;
use codex_hepta_learning_artifacts::ArtifactLifecycleStateV1;
use codex_hepta_learning_artifacts::DatasetWithdrawalRegistry;
use codex_hepta_learning_artifacts::LearningArtifactManifestV2;
use codex_hepta_learning_artifacts::ProvenanceModeV1;
use codex_hepta_learning_artifacts::validate_artifact_lifecycle_transition;
use codex_hepta_learning_ledger::AuthenticatedOutcomeV1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
use codex_hepta_learning_ledger::CreditAllocationBatchV1;
use codex_hepta_learning_ledger::CreditAllocationV1;
use codex_hepta_learning_ledger::DatasetFreezeRequestV1;
use codex_hepta_learning_ledger::OutcomeTerminalityV1;
use codex_hepta_learning_ledger::OutcomeWatermarkV1;
use codex_hepta_learning_ledger::finalize_credit_batch;
use codex_hepta_learning_ledger::freeze_dataset;
use codex_hepta_learning_ledger::validate_authenticated_outcome;
use codex_hepta_learning_ledger::validate_candidate_set_completeness;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

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
    let generator = actor("generator", "generator-credential", "generator-key");
    let observer = actor("observer", "observer-credential", "observer-key");
    let evaluator = actor("evaluator", "evaluator-credential", "evaluator-key");

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
    let withdrawal_registry = DatasetWithdrawalRegistry::new();
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
    let estimand_digest = digest("system-longitudinal-task-utility");
    let frozen_plan = match freeze_cross_fold_plan(CrossFoldPlanV1 {
        plan_id: id("evaluation-plan"),
        claim_scope: EvaluationClaimScopeV1::SystemLongitudinal,
        candidate_id: artifact_id.clone(),
        baseline_id: id("baseline-1"),
        objective_digest,
        dataset_digest: dataset.dataset_digest,
        estimand_digest,
        metric_contracts: vec![MetricContractV1 {
            metric_id: id("task-utility"),
            direction: EvaluationDirectionV1::Maximize,
            safety_floor: Some(FixedQ32::from_raw(95)),
        }],
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 1,
        folds: vec![
            CrossFoldPartitionV1 {
                fold_id: id("evaluation-fold-1"),
                training_principals: vec![id("evaluation-principal-2")],
                training_episodes: vec![id("evaluation-episode-2")],
                training_windows: vec![id("evaluation-train-window-1")],
                holdout_principals: vec![id("evaluation-principal-1")],
                holdout_episodes: vec![id("evaluation-episode-1")],
                holdout_windows: vec![id("window-1")],
                model_digest: digest("evaluation-model-1"),
                predictions_digest: digest("evaluation-predictions-1"),
            },
            CrossFoldPartitionV1 {
                fold_id: id("evaluation-fold-2"),
                training_principals: vec![id("evaluation-principal-1")],
                training_episodes: vec![id("evaluation-episode-1")],
                training_windows: vec![id("evaluation-train-window-2")],
                holdout_principals: vec![id("evaluation-principal-2")],
                holdout_episodes: vec![id("evaluation-episode-2")],
                holdout_windows: vec![id("window-2")],
                model_digest: digest("evaluation-model-2"),
                predictions_digest: digest("evaluation-predictions-2"),
            },
        ],
        final_holdout_window_id: id("window-2"),
        final_holdout_digest: digest("final-holdout"),
    }) {
        Ok(receipt) => receipt,
        Err(error) => panic!("frozen evaluation plan failed: {error}"),
    };
    let mut final_holdout_registry = FinalHoldoutRegistry::new();
    let holdout_use = match final_holdout_registry.consume(&frozen_plan) {
        Ok(receipt) => receipt,
        Err(error) => panic!("final holdout use failed: {error}"),
    };

    let evaluation = match decide_independently(
        IndependentEvaluationBundleV1 {
            evaluation_id: id("evaluation-1"),
            candidate_id: artifact_id.clone(),
            baseline_id: id("baseline-1"),
            claim_scope: EvaluationClaimScopeV1::SystemLongitudinal,
            generator: generator.clone(),
            evaluator: evaluator.clone(),
            frozen_plan,
            holdout_use,
            objective_digest,
            dataset_digest: dataset.dataset_digest,
            estimand_digest,
            estimate_receipt_digest: bellman.evidence_digest,
            support_audit_digest: candidate_digest,
            confidence_receipt_digest: digest("confidence"),
            retention_receipt_digests: vec![digest("retention")],
            unlearning_receipt_digest: digest("unlearning"),
            snapshot_ids: vec![id("snapshot-1"), id("snapshot-2"), id("snapshot-3")],
            future_window_ids: vec![id("window-1"), id("window-2")],
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            metrics: vec![MetricGateV1 {
                metric_id: id("task-utility"),
                direction: EvaluationDirectionV1::Maximize,
                candidate: EvaluationIntervalV1 {
                    lower: FixedQ32::from_raw(100),
                    upper: FixedQ32::from_raw(110),
                },
                baseline: EvaluationIntervalV1 {
                    lower: FixedQ32::from_raw(80),
                    upper: FixedQ32::from_raw(90),
                },
                safety_floor: Some(FixedQ32::from_raw(95)),
                support_digest: outcome_digest,
            }],
        },
        50,
    ) {
        Ok(decision) => decision,
        Err(error) => panic!("independent evaluation failed: {error}"),
    };
    assert_eq!(
        evaluation.disposition,
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection
    );
    assert!(!evaluation.authority.grants_any());

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
        evidence_digest: evaluation.evidence_digest,
        authority_epoch: 8,
        occurred_at: 50,
    };
    assert!(validate_artifact_lifecycle_transition(&producer_id, &evaluated_event).is_ok());

    assert!(!withdrawal_registry.is_withdrawn(dataset.dataset_digest));
}
