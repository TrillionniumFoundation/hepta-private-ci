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

fn bundle() -> IndependentEvaluationBundleV1 {
    IndependentEvaluationBundleV1 {
        evaluation_id: id("evaluation-1"),
        candidate_id: id("candidate-1"),
        baseline_id: id("baseline-1"),
        claim_scope: EvaluationClaimScopeV1::SystemLongitudinal,
        generator: actor("generator", "generator-credential", "generator-key"),
        evaluator: actor("evaluator", "evaluator-credential", "evaluator-key"),
        plan_digest: digest("plan"),
        objective_digest: digest("objective"),
        estimate_receipt_digest: digest("estimate"),
        support_audit_digest: digest("support-audit"),
        confidence_receipt_digest: digest("confidence"),
        retention_receipt_digests: vec![digest("retention-old-task")],
        unlearning_receipt_digest: digest("unlearning"),
        snapshot_ids: vec![id("snapshot-3"), id("snapshot-1"), id("snapshot-2")],
        future_window_ids: vec![id("window-2"), id("window-1")],
        final_holdout_digest: digest("final-holdout"),
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 1,
        analysis_plan_frozen: true,
        final_holdout_reused: false,
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

#[test]
fn eval_cross_fold_plan_binds_disjoint_lineage_and_final_holdout() {
    let plan = CrossFoldPlanV1 {
        plan_id: id("cross-fold-plan"),
        folds: vec![
            fold("fold-1", "p-2", "e-2", "train-w-1", "p-1", "e-1", "w-1"),
            fold("fold-2", "p-1", "e-1", "train-w-2", "p-2", "e-2", "w-2"),
        ],
        final_holdout_window_id: id("w-2"),
        final_holdout_digest: digest("final-holdout"),
    };
    let receipt = match freeze_cross_fold_plan(plan) {
        Ok(receipt) => receipt,
        Err(error) => panic!("valid cross-fold plan failed: {error}"),
    };
    assert_eq!(receipt.fold_count, 2);
    assert!(!receipt.plan_digest.is_zero());

    let leaking = CrossFoldPlanV1 {
        plan_id: id("leaking-plan"),
        folds: vec![
            fold("fold-1", "p-1", "e-2", "train-w-1", "p-1", "e-1", "w-1"),
            fold("fold-2", "p-1", "e-1", "train-w-2", "p-2", "e-2", "w-2"),
        ],
        final_holdout_window_id: id("w-2"),
        final_holdout_digest: digest("final-holdout"),
    };
    assert_eq!(
        freeze_cross_fold_plan(leaking),
        Err(EvaluationClosureError::CrossFoldLeakage(
            "fold-1".to_owned()
        ))
    );
}

#[test]
fn final_holdout_registry_allows_exact_retry_but_blocks_adaptive_reuse() {
    let mut registry = FinalHoldoutRegistry::new();
    let holdout = digest("final-holdout");
    let first = match registry.consume(id("plan-1"), holdout) {
        Ok(receipt) => receipt,
        Err(error) => panic!("first holdout use failed: {error}"),
    };
    assert_eq!(first.disposition, HoldoutUseDispositionV1::Recorded);
    let retry = match registry.consume(id("plan-1"), holdout) {
        Ok(receipt) => receipt,
        Err(error) => panic!("exact retry failed: {error}"),
    };
    assert_eq!(retry.disposition, HoldoutUseDispositionV1::IdempotentReplay);
    assert_eq!(
        registry.consume(id("plan-2"), holdout),
        Err(EvaluationClosureError::FinalHoldoutReused)
    );
}
