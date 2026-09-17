use codex_hepta_intelligence_eval::CrossFoldPartitionV1;
use codex_hepta_intelligence_eval::CrossFoldPlanV1;
use codex_hepta_intelligence_eval::EvaluationClaimScopeV1;
use codex_hepta_intelligence_eval::EvaluationDirectionV1;
use codex_hepta_intelligence_eval::EvaluationIntervalV1;
use codex_hepta_intelligence_eval::FinalHoldoutJournalV1;
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
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).expect("valid id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn principal(name: &str, seed: u8) -> AuthenticatedPrincipalV1 {
    let key = SigningKey::from_bytes(&[seed; 32])
        .verifying_key()
        .to_bytes();
    AuthenticatedPrincipalV1 {
        principal_id: id(name),
        credential_chain_digest: digest(&format!("credential-{name}")),
        signing_key_digest: Digest32::of_bytes(&key),
        scope_digest: digest("production-scope"),
        authority_epoch: 11,
        authenticated_at: 10,
        expires_at: 100,
    }
}

fn trusted_signer(
    name: &str,
    controller: &str,
    seed: u8,
    role: LearningEvidenceRoleV1,
) -> TrustedLearningSignerV1 {
    TrustedLearningSignerV1 {
        principal: principal(name, seed),
        controller_id: id(controller),
        verifying_key: SigningKey::from_bytes(&[seed; 32])
            .verifying_key()
            .to_bytes(),
        roles: vec![role],
        revoked_at: None,
    }
}

fn verifier() -> LearningEvidenceVerifierV1 {
    LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: digest("production-scope"),
        objective_digest: digest("objective"),
        authority_epoch: 11,
        signers: vec![
            trusted_signer(
                "generator",
                "generator-controller",
                1,
                LearningEvidenceRoleV1::Generator,
            ),
            trusted_signer(
                "evaluator",
                "evaluator-controller",
                2,
                LearningEvidenceRoleV1::Evaluator,
            ),
        ],
    })
    .expect("valid trust")
}

fn sign(
    verifier: &LearningEvidenceVerifierV1,
    name: &str,
    role: LearningEvidenceRoleV1,
    seed: u8,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("{name}-evidence")),
        principal_id: id(name),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: digest("production-scope"),
        objective_digest: digest("objective"),
        authority_epoch: 11,
        issued_at: 20,
        expires_at: 90,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = SigningKey::from_bytes(&[seed; 32])
        .sign(&evidence.signing_bytes())
        .to_bytes();
    evidence
}

fn fold(name: &str, train: &str, holdout: &str) -> CrossFoldPartitionV1 {
    CrossFoldPartitionV1 {
        fold_id: id(name),
        training_principals: vec![id(&format!("principal-{train}"))],
        training_episodes: vec![id(&format!("episode-{train}"))],
        training_windows: vec![id(&format!("training-{train}"))],
        holdout_principals: vec![id(&format!("principal-{holdout}"))],
        holdout_episodes: vec![id(&format!("episode-{holdout}"))],
        holdout_windows: vec![id(holdout)],
        model_digest: digest(&format!("model-{name}")),
        predictions_digest: digest(&format!("predictions-{name}")),
    }
}

fn roles() -> Vec<MetricRoleContractV2> {
    vec![MetricRoleContractV2 {
        metric_id: id("utility"),
        role: MetricRoleV2::PrimarySuperiority {
            minimum_improvement: FixedQ32::ZERO,
        },
    }]
}

fn bundle() -> IndependentEvaluationBundleV1 {
    let objective_digest = digest("objective");
    let dataset_digest = digest("dataset");
    let estimand_digest = digest("qualification-estimand");
    let frozen_plan = freeze_cross_fold_plan_v2(
        CrossFoldPlanV1 {
            plan_id: id("production-plan"),
            claim_scope: EvaluationClaimScopeV1::Qualification,
            candidate_id: id("candidate"),
            baseline_id: id("baseline"),
            objective_digest,
            dataset_digest,
            estimand_digest,
            metric_contracts: vec![MetricContractV1 {
                metric_id: id("utility"),
                direction: EvaluationDirectionV1::Maximize,
                safety_floor: Some(FixedQ32::from_raw(70)),
            }],
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            folds: vec![
                fold("fold-a", "b", "a"),
                fold("fold-b", "a", "final-holdout"),
            ],
            final_holdout_window_id: id("final-holdout"),
            final_holdout_digest: digest("final-holdout-bytes"),
        },
        roles(),
    )
    .expect("plan freezes");
    let mut journal = FinalHoldoutJournalV1::new();
    let holdout_use = journal
        .consume(Digest32::ZERO, &frozen_plan)
        .expect("holdout consumed")
        .use_receipt;
    IndependentEvaluationBundleV1 {
        evaluation_id: id("production-evaluation"),
        candidate_id: id("candidate"),
        baseline_id: id("baseline"),
        claim_scope: EvaluationClaimScopeV1::Qualification,
        generator: principal("generator", 1),
        evaluator: principal("evaluator", 2),
        frozen_plan,
        holdout_use,
        objective_digest,
        dataset_digest,
        estimand_digest,
        estimate_receipt_digest: digest("estimate-receipt"),
        support_audit_digest: digest("support-audit"),
        confidence_receipt_digest: digest("confidence-receipt"),
        retention_receipt_digests: vec![digest("retention-receipt")],
        unlearning_receipt_digest: digest("unlearning-receipt"),
        snapshot_ids: vec![id("snapshot-a"), id("snapshot-b")],
        future_window_ids: vec![id("future-a"), id("future-b")],
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 1,
        metrics: vec![MetricGateV1 {
            metric_id: id("utility"),
            direction: EvaluationDirectionV1::Maximize,
            candidate: EvaluationIntervalV1 {
                lower: FixedQ32::from_raw(85),
                upper: FixedQ32::from_raw(90),
            },
            baseline: EvaluationIntervalV1 {
                lower: FixedQ32::from_raw(50),
                upper: FixedQ32::from_raw(60),
            },
            safety_floor: Some(FixedQ32::from_raw(70)),
            support_digest: digest("metric-support"),
        }],
    }
}

fn signed_evidence(
    bundle: &IndependentEvaluationBundleV1,
    verifier: &LearningEvidenceVerifierV1,
) -> SignedEvaluationEvidenceV1 {
    let evaluator_payload =
        evaluation_signing_payload_v2(bundle, &roles()).expect("signing payload");
    SignedEvaluationEvidenceV1 {
        generator_plan: sign(
            verifier,
            "generator",
            LearningEvidenceRoleV1::Generator,
            1,
            bundle.frozen_plan.plan_digest.as_array(),
        ),
        evaluator_bundle: sign(
            verifier,
            "evaluator",
            LearningEvidenceRoleV1::Evaluator,
            2,
            &evaluator_payload,
        ),
    }
}

#[test]
fn signed_v2_frozen_holdout_chain_is_production_eligible_but_deny_all() {
    let verifier = verifier();
    let bundle = bundle();
    let evidence = signed_evidence(&bundle, &verifier);
    let decision = decide_with_signed_evidence_v2(bundle, roles(), &evidence, &verifier, 50)
        .expect("signed production qualification succeeds");
    assert_eq!(
        decision.decision.disposition,
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection
    );
    assert!(!decision.decision.authority.grants_any());
    assert!(!decision.authentication_digest.is_zero());
    assert_eq!(decision.trust_digest, verifier.trust_digest());
}

#[test]
fn tampered_evaluator_signature_fails_before_qualification() {
    let verifier = verifier();
    let bundle = bundle();
    let mut evidence = signed_evidence(&bundle, &verifier);
    evidence.evaluator_bundle.signature[0] ^= 1;
    let error = decide_with_signed_evidence_v2(bundle, roles(), &evidence, &verifier, 50)
        .expect_err("tampered signature must fail closed");
    assert!(matches!(
        error,
        codex_hepta_intelligence_eval::SignedEvaluationError::Evidence(
            SignedEvidenceError::InvalidSignature
        )
    ));
}

#[test]
fn shared_controller_is_not_independent_even_with_distinct_keys() {
    let mut trust = LearningEvidenceTrustV1 {
        scope_digest: digest("production-scope"),
        objective_digest: digest("objective"),
        authority_epoch: 11,
        signers: vec![
            trusted_signer(
                "generator",
                "shared-controller",
                1,
                LearningEvidenceRoleV1::Generator,
            ),
            trusted_signer(
                "evaluator",
                "shared-controller",
                2,
                LearningEvidenceRoleV1::Evaluator,
            ),
        ],
    };
    trust.signers.sort_by_key(|signer| signer.principal.principal_id.clone());
    let verifier = LearningEvidenceVerifierV1::new(trust).expect("valid trust snapshot");
    let bundle = bundle();
    let evidence = signed_evidence(&bundle, &verifier);
    assert!(decide_with_signed_evidence_v2(bundle, roles(), &evidence, &verifier, 50).is_err());
}
