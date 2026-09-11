use super::*;

fn id(value: &str) -> StableId {
    match StableId::new(value.to_owned()) {
        Ok(value) => value,
        Err(error) => panic!("invalid test id {value}: {error}"),
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn actor(name: &str, credential: &str, key: &str) -> AuthenticatedPrincipalV1 {
    AuthenticatedPrincipalV1 {
        principal_id: id(name),
        credential_chain_digest: digest(credential),
        signing_key_digest: digest(key),
        scope_digest: digest(&format!("scope-{name}")),
        authority_epoch: 4,
        authenticated_at: 10,
        expires_at: 100,
    }
}

fn metric() -> MetricGateV1 {
    MetricGateV1 {
        metric_id: id("task-utility"),
        direction: EvaluationDirectionV1::Maximize,
        candidate: EvaluationIntervalV1 {
            lower: FixedQ32::from_raw(80),
            upper: FixedQ32::from_raw(90),
        },
        baseline: EvaluationIntervalV1 {
            lower: FixedQ32::from_raw(50),
            upper: FixedQ32::from_raw(70),
        },
        safety_floor: Some(FixedQ32::from_raw(75)),
        support_digest: digest("metric-support"),
    }
}

fn metric_contract() -> MetricContractV1 {
    MetricContractV1 {
        metric_id: id("task-utility"),
        direction: EvaluationDirectionV1::Maximize,
        safety_floor: Some(FixedQ32::from_raw(75)),
    }
}

fn fold(
    name: &str,
    training_principal: &str,
    training_episode: &str,
    training_window: &str,
    holdout_principal: &str,
    holdout_episode: &str,
    holdout_window: &str,
) -> CrossFoldPartitionV1 {
    CrossFoldPartitionV1 {
        fold_id: id(name),
        training_principals: vec![id(training_principal)],
        training_episodes: vec![id(training_episode)],
        training_windows: vec![id(training_window)],
        holdout_principals: vec![id(holdout_principal)],
        holdout_episodes: vec![id(holdout_episode)],
        holdout_windows: vec![id(holdout_window)],
        model_digest: digest(&format!("model-{name}")),
        predictions_digest: digest(&format!("predictions-{name}")),
    }
}

fn plan() -> CrossFoldPlanV1 {
    CrossFoldPlanV1 {
        plan_id: id("cross-fold-plan"),
        claim_scope: EvaluationClaimScopeV1::SystemLongitudinal,
        candidate_id: id("candidate-1"),
        baseline_id: id("baseline-1"),
        objective_digest: digest("objective"),
        dataset_digest: digest("dataset"),
        estimand_digest: digest("system-longitudinal-task-utility"),
        metric_contracts: vec![metric_contract()],
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 1,
        folds: vec![
            fold("fold-1", "p-2", "e-2", "train-w-1", "p-1", "e-1", "w-1"),
            fold("fold-2", "p-1", "e-1", "train-w-2", "p-2", "e-2", "w-2"),
        ],
        final_holdout_window_id: id("w-2"),
        final_holdout_digest: digest("final-holdout"),
    }
}

fn freeze_plan(value: CrossFoldPlanV1) -> CrossFoldPlanReceiptV1 {
    match freeze_cross_fold_plan(value) {
        Ok(receipt) => receipt,
        Err(error) => panic!("valid cross-fold plan failed: {error}"),
    }
}

fn bundle() -> IndependentEvaluationBundleV1 {
    let frozen_plan = freeze_plan(plan());
    let mut registry = FinalHoldoutRegistry::new();
    let holdout_use = match registry.consume(&frozen_plan) {
        Ok(receipt) => receipt,
        Err(error) => panic!("valid holdout use failed: {error}"),
    };
    IndependentEvaluationBundleV1 {
        evaluation_id: id("evaluation-1"),
        candidate_id: id("candidate-1"),
        baseline_id: id("baseline-1"),
        claim_scope: EvaluationClaimScopeV1::SystemLongitudinal,
        generator: actor("generator", "generator-credential", "generator-key"),
        evaluator: actor("evaluator", "evaluator-credential", "evaluator-key"),
        frozen_plan,
        holdout_use,
        objective_digest: digest("objective"),
        dataset_digest: digest("dataset"),
        estimand_digest: digest("system-longitudinal-task-utility"),
        estimate_receipt_digest: digest("estimate"),
        support_audit_digest: digest("support-audit"),
        confidence_receipt_digest: digest("confidence"),
        retention_receipt_digests: vec![digest("retention-old-task")],
        unlearning_receipt_digest: digest("unlearning"),
        snapshot_ids: vec![id("snapshot-3"), id("snapshot-1"), id("snapshot-2")],
        future_window_ids: vec![id("window-2"), id("window-1")],
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 1,
        metrics: vec![metric()],
    }
}

#[test]
fn eval_03_intersects_superiority_safety_retention_and_unlearning() {
    let decision = match decide_independently(bundle(), 50) {
        Ok(decision) => decision,
        Err(error) => panic!("valid independent evaluation failed: {error}"),
    };
    assert_eq!(
        decision.disposition,
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection
    );
    assert!(decision.failed_metrics.is_empty());
    assert!(!decision.evidence_digest.is_zero());
    assert!(!decision.authority.grants_any());
}

#[test]
fn eval_04_rejects_role_collision_and_missing_future_windows() {
    let mut collision = bundle();
    collision.evaluator.signing_key_digest = collision.generator.signing_key_digest;
    assert!(matches!(
        decide_independently(collision, 50),
        Err(EvaluationClosureError::Role(CausalV2Error::RoleCollision(
            "signing key"
        )))
    ));

    let mut insufficient = bundle();
    insufficient.future_window_ids.truncate(1);
    let decision = match decide_independently(insufficient, 50) {
        Ok(decision) => decision,
        Err(error) => panic!("insufficient evidence should be a decision: {error}"),
    };
    assert_eq!(
        decision.disposition,
        IndependentEvaluationDispositionV1::InsufficientEvidence
    );
}

#[test]
fn evaluation_fails_candidate_when_interval_or_floor_does_not_pass() {
    let mut value = bundle();
    value.metrics[0].candidate.lower = FixedQ32::from_raw(69);
    let decision = match decide_independently(value, 50) {
        Ok(decision) => decision,
        Err(error) => panic!("failed metric should produce an ineligible decision: {error}"),
    };
    assert_eq!(
        decision.disposition,
        IndependentEvaluationDispositionV1::Ineligible
    );
    assert_eq!(decision.failed_metrics, vec![id("task-utility")]);
}

#[test]
fn eval_cross_fold_plan_binds_disjoint_lineage_and_final_holdout() {
    let receipt = freeze_plan(plan());
    assert_eq!(receipt.fold_count, 2);
    assert_eq!(receipt.candidate_id, id("candidate-1"));
    assert!(!receipt.plan_digest.is_zero());

    let mut leaking = plan();
    leaking.plan_id = id("leaking-plan");
    leaking.folds[0].training_principals = vec![id("p-1")];
    assert_eq!(
        freeze_cross_fold_plan(leaking),
        Err(EvaluationClosureError::CrossFoldLeakage(
            "fold-1".to_owned()
        ))
    );
}

fn assert_identity_conflict(registry: &mut FinalHoldoutRegistry, changed: CrossFoldPlanV1) {
    let changed = freeze_plan(changed);
    assert_eq!(
        registry.consume(&changed),
        Err(EvaluationClosureError::FinalHoldoutIdentityConflict(
            "cross-fold-plan".to_owned()
        ))
    );
}

#[test]
fn final_holdout_registry_allows_exact_retry_but_blocks_adaptive_reuse() {
    let original = plan();
    let frozen = freeze_plan(original.clone());
    let mut registry = FinalHoldoutRegistry::new();
    let first = match registry.consume(&frozen) {
        Ok(receipt) => receipt,
        Err(error) => panic!("first holdout use failed: {error}"),
    };
    assert_eq!(first.disposition, HoldoutUseDispositionV1::Recorded);
    let retry = match registry.consume(&frozen) {
        Ok(receipt) => receipt,
        Err(error) => panic!("exact retry failed: {error}"),
    };
    assert_eq!(retry.disposition, HoldoutUseDispositionV1::IdempotentReplay);
    assert_eq!(retry.registry_digest, first.registry_digest);
    assert_eq!(retry.use_digest, first.use_digest);

    let mut changed_model = original.clone();
    changed_model.folds[0].model_digest = digest("changed-model");
    assert_identity_conflict(&mut registry, changed_model);

    let mut changed_predictions = original.clone();
    changed_predictions.folds[0].predictions_digest = digest("changed-predictions");
    assert_identity_conflict(&mut registry, changed_predictions);

    let mut changed_lineage = original.clone();
    changed_lineage.folds[0].training_episodes = vec![id("e-3")];
    assert_identity_conflict(&mut registry, changed_lineage);

    let mut changed_scope = original.clone();
    changed_scope.claim_scope = EvaluationClaimScopeV1::Qualification;
    assert_identity_conflict(&mut registry, changed_scope);

    let mut changed_candidate = original.clone();
    changed_candidate.candidate_id = id("candidate-2");
    assert_identity_conflict(&mut registry, changed_candidate);

    let mut changed_objective = original.clone();
    changed_objective.objective_digest = digest("changed-objective");
    assert_identity_conflict(&mut registry, changed_objective);

    let mut changed_threshold = original.clone();
    changed_threshold.metric_contracts[0].safety_floor = Some(FixedQ32::from_raw(76));
    assert_identity_conflict(&mut registry, changed_threshold);

    let mut different_plan = original.clone();
    different_plan.plan_id = id("plan-2");
    let different_plan = freeze_plan(different_plan);
    assert_eq!(
        registry.consume(&different_plan),
        Err(EvaluationClosureError::FinalHoldoutReused)
    );

    let mut same_window_changed_bytes = original;
    same_window_changed_bytes.plan_id = id("plan-3");
    same_window_changed_bytes.final_holdout_digest = digest("changed-holdout-bytes");
    let same_window_changed_bytes = freeze_plan(same_window_changed_bytes);
    assert_eq!(
        registry.consume(&same_window_changed_bytes),
        Err(EvaluationClosureError::FinalHoldoutReused)
    );
}

#[test]
fn final_holdout_replay_receipt_is_stable_after_unrelated_registry_growth() {
    let frozen = freeze_plan(plan());
    let mut registry = FinalHoldoutRegistry::new();
    let first = match registry.consume(&frozen) {
        Ok(receipt) => receipt,
        Err(error) => panic!("first holdout use failed: {error}"),
    };

    let mut unrelated = plan();
    unrelated.plan_id = id("unrelated-plan");
    unrelated.candidate_id = id("unrelated-candidate");
    unrelated.folds[0].holdout_windows = vec![id("w-3")];
    unrelated.folds[1].holdout_windows = vec![id("w-4")];
    unrelated.final_holdout_window_id = id("w-4");
    unrelated.final_holdout_digest = digest("unrelated-final-holdout");
    let unrelated = freeze_plan(unrelated);
    let unrelated_receipt = match registry.consume(&unrelated) {
        Ok(receipt) => receipt,
        Err(error) => panic!("unrelated holdout use failed: {error}"),
    };
    assert_eq!(
        unrelated_receipt.disposition,
        HoldoutUseDispositionV1::Recorded
    );
    assert_ne!(registry.digest(), first.registry_digest);

    let replay = match registry.consume(&frozen) {
        Ok(receipt) => receipt,
        Err(error) => panic!("stable replay failed: {error}"),
    };
    let mut expected = first;
    expected.disposition = HoldoutUseDispositionV1::IdempotentReplay;
    expected.receipt_seal = holdout_use_receipt_seal(&expected);
    assert_eq!(replay, expected);
}

#[test]
fn independent_decision_consumes_bound_holdout_receipt() {
    let mut tampered_plan = bundle();
    tampered_plan.frozen_plan.plan_digest = digest("tampered-frozen-plan");
    assert_eq!(
        decide_independently(tampered_plan, 50),
        Err(EvaluationClosureError::FrozenPlanReceiptIntegrity)
    );

    let mut changed_scope = bundle();
    changed_scope.claim_scope = EvaluationClaimScopeV1::Qualification;
    assert_eq!(
        decide_independently(changed_scope, 50),
        Err(EvaluationClosureError::FrozenPlanBindingMismatch(
            "claim scope"
        ))
    );

    let mut changed_use = bundle();
    changed_use.holdout_use.plan_digest = digest("adaptive-second-analysis");
    assert_eq!(
        decide_independently(changed_use, 50),
        Err(EvaluationClosureError::HoldoutUseReceiptIntegrity)
    );

    let mut changed_contract = bundle();
    changed_contract.metrics[0].safety_floor = Some(FixedQ32::from_raw(76));
    assert_eq!(
        decide_independently(changed_contract, 50),
        Err(EvaluationClosureError::FrozenPlanBindingMismatch(
            "metric contract"
        ))
    );

    let mut changed_candidate = bundle();
    changed_candidate.candidate_id = id("adaptive-candidate");
    assert_eq!(
        decide_independently(changed_candidate, 50),
        Err(EvaluationClosureError::FrozenPlanBindingMismatch(
            "candidate"
        ))
    );
}

fn bind_metric_roles(
    bundle: &mut IndependentEvaluationBundleV1,
    roles: &[MetricRoleContractV2],
) -> Result<(), EvaluationClosureError> {
    let mut plan = plan();
    plan.metric_contracts = metric_contracts(&bundle.metrics);
    plan.simultaneous_comparisons = bundle.simultaneous_comparisons;
    bundle.frozen_plan = freeze_cross_fold_plan_v2(plan, roles.to_vec())?;
    bundle.holdout_use = FinalHoldoutRegistry::new().consume(&bundle.frozen_plan)?;
    Ok(())
}

fn mixed_role_bundle()
-> Result<(IndependentEvaluationBundleV1, Vec<MetricRoleContractV2>), EvaluationClosureError> {
    let mut value = bundle();
    value.metrics.extend([
        MetricGateV1 {
            metric_id: id("safety-events"),
            direction: EvaluationDirectionV1::Minimize,
            candidate: EvaluationIntervalV1 {
                lower: FixedQ32::ZERO,
                upper: FixedQ32::ZERO,
            },
            baseline: EvaluationIntervalV1 {
                lower: FixedQ32::ZERO,
                upper: FixedQ32::ZERO,
            },
            safety_floor: Some(FixedQ32::ZERO),
            support_digest: digest("safety-support"),
        },
        MetricGateV1 {
            metric_id: id("resource-cost"),
            direction: EvaluationDirectionV1::Minimize,
            candidate: EvaluationIntervalV1 {
                lower: FixedQ32::from_raw(95),
                upper: FixedQ32::from_raw(100),
            },
            baseline: EvaluationIntervalV1 {
                lower: FixedQ32::from_raw(80),
                upper: FixedQ32::from_raw(90),
            },
            safety_floor: Some(FixedQ32::from_raw(100)),
            support_digest: digest("resource-support"),
        },
    ]);
    value.simultaneous_comparisons = 3;
    let roles = vec![
        MetricRoleContractV2 {
            metric_id: id("task-utility"),
            role: MetricRoleV2::PrimarySuperiority {
                minimum_improvement: FixedQ32::ZERO,
            },
        },
        MetricRoleContractV2 {
            metric_id: id("safety-events"),
            role: MetricRoleV2::NonInferiority {
                maximum_regression: FixedQ32::ZERO,
            },
        },
        MetricRoleContractV2 {
            metric_id: id("resource-cost"),
            role: MetricRoleV2::AbsoluteConstraint,
        },
    ];
    bind_metric_roles(&mut value, &roles)?;
    Ok((value, roles))
}

#[test]
fn preregistered_roles_allow_unchanged_safety_and_cost_within_budget()
-> Result<(), EvaluationClosureError> {
    let (value, roles) = mixed_role_bundle()?;
    let decision = decide_independently_v2(value.clone(), roles.clone(), 50)?;
    assert_eq!(
        (
            decision.disposition,
            decision.failed_metrics,
            decision.authority
        ),
        (
            IndependentEvaluationDispositionV1::EligibleForIndependentSelection,
            vec![],
            AuthorityPosture::DENY_ALL,
        )
    );
    assert_eq!(
        decide_independently(value.clone(), 50),
        Err(EvaluationClosureError::FrozenPlanBindingMismatch(
            "metric contract"
        ))
    );

    let mut no_improvement = value.clone();
    no_improvement.metrics[0].candidate.lower = FixedQ32::from_raw(75);
    no_improvement.metrics[0].baseline.upper = FixedQ32::from_raw(75);
    let failed = decide_independently_v2(no_improvement, roles.clone(), 50)?;
    assert_eq!(
        (failed.disposition, failed.failed_metrics),
        (
            IndependentEvaluationDispositionV1::Ineligible,
            vec![id("task-utility")]
        )
    );

    let mut over_budget = value.clone();
    over_budget.metrics[2].candidate.upper = FixedQ32::from_raw(101);
    let failed = decide_independently_v2(over_budget, roles.clone(), 50)?;
    assert_eq!(
        (failed.disposition, failed.failed_metrics),
        (
            IndependentEvaluationDispositionV1::Ineligible,
            vec![id("resource-cost")]
        )
    );

    let mut missing_support = value;
    missing_support.metrics[1].support_digest = Digest32::ZERO;
    assert_eq!(
        decide_independently_v2(missing_support, roles, 50)?.disposition,
        IndependentEvaluationDispositionV1::InsufficientEvidence
    );
    Ok(())
}

#[test]
fn noninferiority_uses_direction_and_includes_the_registered_margin()
-> Result<(), EvaluationClosureError> {
    for direction in [
        EvaluationDirectionV1::Maximize,
        EvaluationDirectionV1::Minimize,
    ] {
        let (mut value, mut roles) = mixed_role_bundle()?;
        roles[1].role = MetricRoleV2::NonInferiority {
            maximum_regression: FixedQ32::from_raw(5),
        };
        value.metrics[1].direction = direction;
        value.metrics[1].safety_floor = None;
        value.metrics[1].baseline = EvaluationIntervalV1 {
            lower: FixedQ32::from_raw(50),
            upper: FixedQ32::from_raw(50),
        };
        let boundary = match direction {
            EvaluationDirectionV1::Maximize => 45,
            EvaluationDirectionV1::Minimize => 55,
        };
        value.metrics[1].candidate = EvaluationIntervalV1 {
            lower: FixedQ32::from_raw(boundary),
            upper: FixedQ32::from_raw(boundary),
        };
        bind_metric_roles(&mut value, &roles)?;
        assert_eq!(
            decide_independently_v2(value.clone(), roles.clone(), 50)?.disposition,
            IndependentEvaluationDispositionV1::EligibleForIndependentSelection
        );
        match direction {
            EvaluationDirectionV1::Maximize => {
                value.metrics[1].candidate.lower = FixedQ32::from_raw(44)
            }
            EvaluationDirectionV1::Minimize => {
                value.metrics[1].candidate.upper = FixedQ32::from_raw(56)
            }
        }
        assert_eq!(
            decide_independently_v2(value, roles, 50)?.failed_metrics,
            vec![id("safety-events")]
        );
    }
    Ok(())
}

#[test]
fn role_contracts_cannot_be_changed_reordered_away_or_reused_on_holdout()
-> Result<(), EvaluationClosureError> {
    let (value, roles) = mixed_role_bundle()?;
    let original = decide_independently_v2(value.clone(), roles.clone(), 50)?;
    let mut reordered = roles.clone();
    reordered.reverse();
    assert_eq!(
        decide_independently_v2(value.clone(), reordered, 50)?,
        original
    );
    let mut changed = roles.clone();
    changed[1].role = MetricRoleV2::NonInferiority {
        maximum_regression: FixedQ32::ONE,
    };
    assert_eq!(
        decide_independently_v2(value.clone(), changed.clone(), 50),
        Err(EvaluationClosureError::FrozenPlanBindingMismatch(
            "metric contract"
        ))
    );
    let mut registry = FinalHoldoutRegistry::new();
    registry.consume(&value.frozen_plan)?;
    let mut revised = value.clone();
    bind_metric_roles(&mut revised, &changed)?;
    assert_ne!(
        revised.frozen_plan.plan_digest,
        value.frozen_plan.plan_digest
    );
    assert_ne!(
        revised.frozen_plan.metric_contract_digest,
        value.frozen_plan.metric_contract_digest
    );
    assert_eq!(
        registry.consume(&revised.frozen_plan),
        Err(EvaluationClosureError::FinalHoldoutIdentityConflict(
            "cross-fold-plan".to_owned()
        ))
    );
    let mut missing = roles.clone();
    missing.pop();
    assert_eq!(
        decide_independently_v2(value.clone(), missing, 50),
        Err(EvaluationClosureError::FrozenPlanBindingMismatch(
            "metric role coverage"
        ))
    );
    let mut duplicate = roles;
    duplicate[1] = duplicate[0].clone();
    assert_eq!(
        decide_independently_v2(value, duplicate, 50),
        Err(EvaluationClosureError::FrozenPlanBindingMismatch(
            "metric role coverage"
        ))
    );
    Ok(())
}

#[test]
fn freezing_rejects_vacuous_or_invalid_metric_roles() -> Result<(), EvaluationClosureError> {
    let mut only_primary = vec![MetricRoleContractV2 {
        metric_id: id("task-utility"),
        role: MetricRoleV2::NonInferiority {
            maximum_regression: FixedQ32::ZERO,
        },
    }];
    assert_eq!(
        freeze_cross_fold_plan_v2(plan(), only_primary.clone()),
        Err(EvaluationClosureError::FrozenPlanBindingMismatch(
            "missing primary objective"
        ))
    );
    for (role, label) in [
        (
            MetricRoleV2::PrimarySuperiority {
                minimum_improvement: FixedQ32::from_raw(-1),
            },
            "negative superiority margin",
        ),
        (
            MetricRoleV2::NonInferiority {
                maximum_regression: FixedQ32::from_raw(-1),
            },
            "negative noninferiority margin",
        ),
    ] {
        only_primary[0].role = role;
        assert_eq!(
            freeze_cross_fold_plan_v2(plan(), only_primary.clone()),
            Err(EvaluationClosureError::FrozenPlanBindingMismatch(label))
        );
    }
    let (value, roles) = mixed_role_bundle()?;
    let mut unbounded = plan();
    unbounded.metric_contracts = metric_contracts(&value.metrics);
    unbounded.metric_contracts[2].safety_floor = None;
    assert_eq!(
        freeze_cross_fold_plan_v2(unbounded, roles),
        Err(EvaluationClosureError::FrozenPlanBindingMismatch(
            "missing absolute constraint bound"
        ))
    );
    Ok(())
}

#[test]
fn primary_superiority_has_strict_margins_without_q32_subtraction_overflow()
-> Result<(), EvaluationClosureError> {
    for direction in [
        EvaluationDirectionV1::Maximize,
        EvaluationDirectionV1::Minimize,
    ] {
        let mut value = bundle();
        let roles = vec![MetricRoleContractV2 {
            metric_id: id("task-utility"),
            role: MetricRoleV2::PrimarySuperiority {
                minimum_improvement: FixedQ32::from_raw(10),
            },
        }];
        value.metrics[0].direction = direction;
        value.metrics[0].safety_floor = None;
        value.metrics[0].baseline = EvaluationIntervalV1 {
            lower: FixedQ32::from_raw(50),
            upper: FixedQ32::from_raw(50),
        };
        let boundary = match direction {
            EvaluationDirectionV1::Maximize => 60,
            EvaluationDirectionV1::Minimize => 40,
        };
        value.metrics[0].candidate = EvaluationIntervalV1 {
            lower: FixedQ32::from_raw(boundary),
            upper: FixedQ32::from_raw(boundary),
        };
        bind_metric_roles(&mut value, &roles)?;
        assert_eq!(
            decide_independently_v2(value.clone(), roles.clone(), 50)?.disposition,
            IndependentEvaluationDispositionV1::Ineligible
        );
        let (candidate, baseline) = match direction {
            EvaluationDirectionV1::Maximize => (i64::MAX, i64::MIN),
            EvaluationDirectionV1::Minimize => (i64::MIN, i64::MAX),
        };
        value.metrics[0].candidate = EvaluationIntervalV1 {
            lower: FixedQ32::from_raw(candidate),
            upper: FixedQ32::from_raw(candidate),
        };
        value.metrics[0].baseline = EvaluationIntervalV1 {
            lower: FixedQ32::from_raw(baseline),
            upper: FixedQ32::from_raw(baseline),
        };
        assert_eq!(
            decide_independently_v2(value, roles, 50)?.disposition,
            IndependentEvaluationDispositionV1::EligibleForIndependentSelection
        );
    }
    Ok(())
}

#[test]
fn signed_evaluation_binds_metrics_roles_and_host_identities() {
    use crate::SignedEvaluationError;
    use crate::SignedEvaluationEvidenceV1;
    use crate::decide_with_signed_evidence_v1;
    use crate::decide_with_signed_evidence_v2;
    use crate::evaluation_signing_payload_v2;
    use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
    use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
    use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
    use codex_hepta_learning_ledger::SignedEvidenceError;
    use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
    use codex_hepta_learning_ledger::TrustedLearningSignerV1;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    let roles = vec![MetricRoleContractV2 {
        metric_id: id("task-utility"),
        role: MetricRoleV2::PrimarySuperiority {
            minimum_improvement: FixedQ32::ZERO,
        },
    }];
    let mut value = bundle();
    value.frozen_plan = freeze_cross_fold_plan_v2(plan(), roles.clone()).expect("frozen roles");
    value.holdout_use = FinalHoldoutRegistry::new()
        .consume(&value.frozen_plan)
        .expect("holdout");
    let generator_key = SigningKey::from_bytes(&[11; 32]);
    let evaluator_key = SigningKey::from_bytes(&[22; 32]);
    let mut signers = Vec::new();
    for (principal, key, role) in [
        (
            &mut value.generator,
            &generator_key,
            LearningEvidenceRoleV1::Generator,
        ),
        (
            &mut value.evaluator,
            &evaluator_key,
            LearningEvidenceRoleV1::Evaluator,
        ),
    ] {
        principal.scope_digest = digest("shared-learning-scope");
        principal.signing_key_digest = Digest32::of_bytes(&key.verifying_key().to_bytes());
        signers.push(TrustedLearningSignerV1 {
            principal: principal.clone(),
            controller_id: principal.principal_id.clone(),
            verifying_key: key.verifying_key().to_bytes(),
            roles: vec![role],
            revoked_at: None,
        });
    }
    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: digest("shared-learning-scope"),
        objective_digest: value.objective_digest,
        authority_epoch: 4,
        signers,
    })
    .expect("host authority trust");
    let payload = evaluation_signing_payload_v2(&value, &roles).expect("signing payload");
    let mut attestations = Vec::new();
    for (principal, key, role, payload) in [
        (
            &value.generator,
            &generator_key,
            LearningEvidenceRoleV1::Generator,
            value.frozen_plan.plan_digest.as_array().as_slice(),
        ),
        (
            &value.evaluator,
            &evaluator_key,
            LearningEvidenceRoleV1::Evaluator,
            payload.as_slice(),
        ),
    ] {
        let mut signed = SignedLearningEvidenceV1 {
            evidence_id: principal.principal_id.clone(),
            principal_id: principal.principal_id.clone(),
            role,
            trust_digest: verifier.trust_digest(),
            scope_digest: principal.scope_digest,
            objective_digest: value.objective_digest,
            authority_epoch: 4,
            issued_at: 20,
            expires_at: 90,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
        attestations.push(signed);
    }
    let evidence = SignedEvaluationEvidenceV1 {
        generator_plan: attestations[0].clone(),
        evaluator_bundle: attestations[1].clone(),
    };
    let admitted =
        decide_with_signed_evidence_v2(value.clone(), roles.clone(), &evidence, &verifier, 50)
            .expect("verified evaluation");
    assert_eq!(
        admitted.decision.disposition,
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection
    );
    assert!(!admitted.decision.authority.grants_any());
    assert!(!admitted.authentication_digest.is_zero());
    let mut edited = value.clone();
    edited.metrics[0].candidate.upper = FixedQ32::from_raw(95);
    assert_eq!(
        decide_with_signed_evidence_v2(edited, roles, &evidence, &verifier, 50),
        Err(SignedEvaluationError::Evidence(
            SignedEvidenceError::PayloadMismatch
        ))
    );
    let edited_roles = vec![MetricRoleContractV2 {
        metric_id: id("task-utility"),
        role: MetricRoleV2::PrimarySuperiority {
            minimum_improvement: FixedQ32::from_raw(1),
        },
    }];
    assert_eq!(
        decide_with_signed_evidence_v2(value.clone(), edited_roles, &evidence, &verifier, 50),
        Err(SignedEvaluationError::Evidence(
            SignedEvidenceError::PayloadMismatch
        ))
    );
    // V2 signatures cannot authorize the legacy evaluator with different rules.
    assert_eq!(
        decide_with_signed_evidence_v1(value, &evidence, &verifier, 50),
        Err(SignedEvaluationError::Evidence(
            SignedEvidenceError::PayloadMismatch
        ))
    );
}
