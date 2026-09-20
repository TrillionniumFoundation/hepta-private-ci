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
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
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

fn actor(name: &str, credential: &str, key: &str) -> AuthenticatedPrincipalV1 {
    AuthenticatedPrincipalV1 {
        principal_id: id(name),
        credential_chain_digest: digest(credential),
        signing_key_digest: digest(key),
        scope_digest: digest(&format!("scope-{name}")),
        authority_epoch: 5,
        authenticated_at: 10,
        expires_at: 100,
    }
}

fn fold(name: &str, train: &str, holdout: &str) -> CrossFoldPartitionV1 {
    CrossFoldPartitionV1 {
        fold_id: id(name),
        training_principals: vec![id(&format!("training-principal-{train}"))],
        training_episodes: vec![id(&format!("training-episode-{train}"))],
        training_windows: vec![id(&format!("training-window-{train}"))],
        holdout_principals: vec![id(&format!("holdout-principal-{holdout}"))],
        holdout_episodes: vec![id(&format!("holdout-episode-{holdout}"))],
        holdout_windows: vec![id(holdout)],
        model_digest: digest(&format!("model-{name}")),
        predictions_digest: digest(&format!("predictions-{name}")),
    }
}

#[test]
fn op_03_high_fit_without_retention_is_insufficient() {
    let objective_digest = digest("objective");
    let dataset_digest = digest("operator-evaluation-dataset");
    let estimand_digest = digest("system-longitudinal-operator-utility");
    let frozen_plan = match freeze_cross_fold_plan(CrossFoldPlanV1 {
        plan_id: id("operator-evaluation-plan"),
        claim_scope: EvaluationClaimScopeV1::SystemLongitudinal,
        candidate_id: id("high-fit-operator"),
        baseline_id: id("deterministic-baseline"),
        objective_digest,
        dataset_digest,
        estimand_digest,
        metric_contracts: vec![MetricContractV1 {
            metric_id: id("in-sample-fit"),
            direction: EvaluationDirectionV1::Maximize,
            safety_floor: None,
        }],
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 1,
        folds: vec![
            fold("fold-1", "two", "holdout-window-1"),
            fold("fold-2", "one", "holdout-window-2"),
        ],
        final_holdout_window_id: id("holdout-window-2"),
        final_holdout_digest: digest("final-holdout"),
    }) {
        Ok(receipt) => receipt,
        Err(error) => panic!("valid frozen plan failed: {error}"),
    };
    let mut registry = FinalHoldoutRegistry::new();
    let holdout_use = match registry.consume(&frozen_plan) {
        Ok(receipt) => receipt,
        Err(error) => panic!("valid holdout use failed: {error}"),
    };
    let decision = match decide_independently(
        IndependentEvaluationBundleV1 {
            evaluation_id: id("operator-evaluation"),
            candidate_id: id("high-fit-operator"),
            baseline_id: id("deterministic-baseline"),
            claim_scope: EvaluationClaimScopeV1::SystemLongitudinal,
            generator: actor("operator-trainer", "trainer-credential", "trainer-key"),
            evaluator: actor(
                "operator-evaluator",
                "evaluator-credential",
                "evaluator-key",
            ),
            frozen_plan,
            holdout_use,
            objective_digest,
            dataset_digest,
            estimand_digest,
            estimate_receipt_digest: digest("excellent-in-sample-fit"),
            support_audit_digest: digest("support-audit"),
            confidence_receipt_digest: digest("confidence"),
            retention_receipt_digests: Vec::new(),
            unlearning_receipt_digest: Digest32::ZERO,
            snapshot_ids: vec![id("snapshot-1"), id("snapshot-2"), id("snapshot-3")],
            future_window_ids: vec![id("future-1"), id("future-2")],
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            metrics: vec![MetricGateV1 {
                metric_id: id("in-sample-fit"),
                direction: EvaluationDirectionV1::Maximize,
                candidate: EvaluationIntervalV1 {
                    lower: FixedQ32::from_raw(100),
                    upper: FixedQ32::from_raw(110),
                },
                baseline: EvaluationIntervalV1 {
                    lower: FixedQ32::from_raw(10),
                    upper: FixedQ32::from_raw(20),
                },
                safety_floor: None,
                support_digest: digest("fit-support"),
            }],
        },
        50,
    ) {
        Ok(decision) => decision,
        Err(error) => panic!("missing longitudinal evidence should be a disposition: {error}"),
    };
    assert_eq!(
        decision.disposition,
        IndependentEvaluationDispositionV1::InsufficientEvidence
    );
    assert!(decision.failed_metrics.is_empty());
    assert!(!decision.authority.grants_any());
}
