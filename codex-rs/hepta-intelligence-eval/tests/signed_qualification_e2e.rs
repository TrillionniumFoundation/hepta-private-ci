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
use codex_hepta_intelligence_eval::MetricRoleContractV2;
use codex_hepta_intelligence_eval::MetricRoleV2;
use codex_hepta_intelligence_eval::SignedEvaluationEvidenceV1;
use codex_hepta_intelligence_eval::decide_with_signed_evidence_v2;
use codex_hepta_intelligence_eval::evaluation_signing_payload_v2;
use codex_hepta_intelligence_eval::freeze_cross_fold_plan_v2;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).unwrap()
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn principal(
    name: &str,
    credential: &str,
    key: &SigningKey,
    scope: Digest32,
) -> AuthenticatedPrincipalV1 {
    AuthenticatedPrincipalV1 {
        principal_id: id(name),
        credential_chain_digest: digest(credential),
        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
        scope_digest: scope,
        authority_epoch: 9,
        authenticated_at: 10,
        expires_at: 100,
    }
}

fn fold(index: u8) -> CrossFoldPartitionV1 {
    CrossFoldPartitionV1 {
        fold_id: id(&format!("fold-{index}")),
        training_principals: vec![id(&format!("train-principal-{index}"))],
        training_episodes: vec![id(&format!("train-episode-{index}"))],
        training_windows: vec![id(&format!("train-window-{index}"))],
        holdout_principals: vec![id(&format!("holdout-principal-{index}"))],
        holdout_episodes: vec![id(&format!("holdout-episode-{index}"))],
        holdout_windows: vec![id(&format!("holdout-window-{index}"))],
        model_digest: digest(&format!("model-{index}")),
        predictions_digest: digest(&format!("predictions-{index}")),
    }
}

fn sign(
    verifier: &LearningEvidenceVerifierV1,
    principal: &AuthenticatedPrincipalV1,
    key: &SigningKey,
    role: LearningEvidenceRoleV1,
    objective_digest: Digest32,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("{}-evidence", principal.principal_id)),
        principal_id: principal.principal_id.clone(),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: principal.scope_digest,
        objective_digest,
        authority_epoch: 9,
        issued_at: 20,
        expires_at: 90,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    evidence
}

#[test]
fn signed_qualification_e2e_binds_plan_holdout_roles_and_trust() {
    let objective_digest = digest("objective");
    let dataset_digest = digest("dataset");
    let estimand_digest = digest("qualification-estimand");
    let scope_digest = digest("shared-learning-scope");
    let generator_key = SigningKey::from_bytes(&[31; 32]);
    let evaluator_key = SigningKey::from_bytes(&[47; 32]);
    let generator = principal(
        "generator",
        "generator-credential",
        &generator_key,
        scope_digest,
    );
    let evaluator = principal(
        "evaluator",
        "evaluator-credential",
        &evaluator_key,
        scope_digest,
    );

    let roles = vec![MetricRoleContractV2 {
        metric_id: id("task-utility"),
        role: MetricRoleV2::PrimarySuperiority {
            minimum_improvement: FixedQ32::from_raw(5),
        },
    }];
    let frozen_plan = freeze_cross_fold_plan_v2(
        CrossFoldPlanV1 {
            plan_id: id("qualification-plan"),
            claim_scope: EvaluationClaimScopeV1::Qualification,
            candidate_id: id("candidate"),
            baseline_id: id("baseline"),
            objective_digest,
            dataset_digest,
            estimand_digest,
            metric_contracts: vec![MetricContractV1 {
                metric_id: id("task-utility"),
                direction: EvaluationDirectionV1::Maximize,
                safety_floor: Some(FixedQ32::from_raw(80)),
            }],
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            folds: vec![fold(1), fold(2)],
            final_holdout_window_id: id("holdout-window-2"),
            final_holdout_digest: digest("final-holdout"),
        },
        roles.clone(),
    )
    .unwrap();
    let holdout_use = FinalHoldoutRegistry::new().consume(&frozen_plan).unwrap();

    let bundle = IndependentEvaluationBundleV1 {
        evaluation_id: id("evaluation"),
        candidate_id: id("candidate"),
        baseline_id: id("baseline"),
        claim_scope: EvaluationClaimScopeV1::Qualification,
        generator: generator.clone(),
        evaluator: evaluator.clone(),
        frozen_plan,
        holdout_use,
        objective_digest,
        dataset_digest,
        estimand_digest,
        estimate_receipt_digest: digest("estimate"),
        support_audit_digest: digest("support-audit"),
        confidence_receipt_digest: digest("confidence"),
        retention_receipt_digests: Vec::new(),
        unlearning_receipt_digest: Digest32::ZERO,
        snapshot_ids: vec![id("snapshot-1")],
        future_window_ids: vec![id("future-window-1")],
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
            safety_floor: Some(FixedQ32::from_raw(80)),
            support_digest: digest("metric-support"),
        }],
    };

    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest,
        objective_digest,
        authority_epoch: 9,
        signers: vec![
            TrustedLearningSignerV1 {
                principal: generator.clone(),
                controller_id: generator.principal_id.clone(),
                verifying_key: generator_key.verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Generator],
                revoked_at: None,
            },
            TrustedLearningSignerV1 {
                principal: evaluator.clone(),
                controller_id: evaluator.principal_id.clone(),
                verifying_key: evaluator_key.verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Evaluator],
                revoked_at: None,
            },
        ],
    })
    .unwrap();

    let payload = evaluation_signing_payload_v2(&bundle, &roles).unwrap();
    let evidence = SignedEvaluationEvidenceV1 {
        generator_plan: sign(
            &verifier,
            &generator,
            &generator_key,
            LearningEvidenceRoleV1::Generator,
            objective_digest,
            bundle.frozen_plan.plan_digest.as_array(),
        ),
        evaluator_bundle: sign(
            &verifier,
            &evaluator,
            &evaluator_key,
            LearningEvidenceRoleV1::Evaluator,
            objective_digest,
            &payload,
        ),
    };

    let decision =
        decide_with_signed_evidence_v2(bundle.clone(), roles.clone(), &evidence, &verifier, 50)
            .unwrap();
    assert_eq!(
        decision.decision.disposition,
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection
    );
    assert!(!decision.decision.authority.grants_any());

    let mut tampered = bundle;
    tampered.metrics[0].candidate.lower = FixedQ32::from_raw(99);
    assert!(decide_with_signed_evidence_v2(tampered, roles, &evidence, &verifier, 50).is_err());
}
