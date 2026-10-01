use super::*;
use crate::intelligence_product::evaluation_tests::evidence_fixture;
use codex_hepta_intelligence::build_legal_candidates;
use codex_hepta_intuition::CanonicalRiskRuleV1;
use codex_hepta_intuition::LearnedScorerContractV1;

#[allow(
    clippy::expect_used,
    reason = "Test setup and success assertions intentionally fail the test on unexpected errors."
)]
fn signed_fixture() -> (
    Fixture,
    codex_hepta_learning_ledger::ActivatedLearningTrustV1,
) {
    signed_fixture_with_distribution_expiry(super::wall_clock_ms().expect("clock"), None)
}

#[allow(
    clippy::expect_used,
    reason = "Test setup and success assertions intentionally fail the test on unexpected errors."
)]
fn signed_fixture_with_distribution_expiry(
    now: u64,
    expires_at: Option<u64>,
) -> (
    Fixture,
    codex_hepta_learning_ledger::ActivatedLearningTrustV1,
) {
    let mut value = fixture();
    let key = SigningKey::from_bytes(&[47; 32]);
    for owner in &mut value.owners {
        if owner.owner_id.as_str() == "learning.eval" {
            owner.key_digest = Digest32::of_bytes(&key.verifying_key().to_bytes());
        }
    }
    let snapshot = &value.request.snapshot;
    value.request.snapshot = CanonicalIntelligenceSnapshotV1::admit(CanonicalSnapshotRequestV1 {
        objective_digest: snapshot.objective_digest(),
        authority_epoch: snapshot.authority_epoch(),
        body_generation: snapshot.body_generation(),
        configuration_digest: snapshot.configuration_digest(),
        revocation_frontier_digest: snapshot.revocation_frontier_digest(),
        owner_bindings: value.owners.clone(),
    })
    .expect("snapshot with real test evaluator key");
    value.inputs.context_request.run_snapshot_digest = value.request.snapshot.digest();
    let context = compile(value.inputs.context_request.clone()).expect("context compilation");
    let legal = build_legal_candidates(value.request.legal_candidates.clone()).expect("legal set");
    let binding = AgentdEvaluationBindingV1 {
        run_id: value.request.run_id.clone(),
        objective_digest: value.request.snapshot.objective_digest(),
        snapshot_digest: value.request.snapshot.digest(),
        context_receipt_digest: context.context_digest,
        candidate_set_digest: legal.candidate_set_digest,
        selected_candidate_id: id("action.read"),
    };
    let (trust, signed) = match expires_at {
        Some(expires_at) => {
            crate::intelligence_product::evaluation_tests::evidence_fixture_with_distribution_expiry(
                &binding, now, expires_at,
            )
        }
        None => evidence_fixture(&binding, now),
    };
    value.inputs.signed_evaluation = Some(signed);
    (value, trust)
}

fn routing_profile(
    request: &CalibratedDecisionRequestV1,
    risk_rule: CanonicalRiskRuleV1,
) -> CanonicalPolicyProfileV1 {
    CanonicalPolicyProfileV1 {
        profile_id: id("intuition.product.routing"),
        policy_digest: request.policy_digest,
        objective_class_digest: request.objective_class_digest,
        generation: request.policy_generation,
        valid_from_sequence: request.calibration.valid_from_sequence,
        expires_after_sequence: request.calibration.expires_after_sequence,
        minimum_confidence: request.minimum_confidence,
        maximum_ece_ppm: request.maximum_ece_ppm,
        maximum_ood_false_acceptance_ppm: request.maximum_ood_false_acceptance_ppm,
        maximum_in_domain_score: request.ood.maximum_in_domain_score,
        risk_rule,
        scorer: LearnedScorerContractV1 {
            model_digest: digest("routing-model"),
            feature_schema_digest: digest("routing-features"),
            output_schema_digest: digest("routing-outputs"),
            score_semantics_digest: digest("routing-score-semantics"),
            scorer_contract_digest: digest("routing-scorer-contract"),
        },
        calibration_dataset_digest: digest("routing-calibration-dataset"),
        ood_dataset_digest: digest("routing-ood-dataset"),
        calibration_artifact_digest: request.calibration.artifact_digest,
        ood_artifact_digest: request.ood.artifact_digest,
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[allow(
    clippy::expect_used,
    reason = "Test setup and success assertions intentionally fail the test on unexpected errors."
)]
async fn product_profile_routes_slow_path_before_context_and_evaluation() {
    for (risk_rule, risk_class) in [
        (CanonicalRiskRuleV1::AlwaysSlowPath, RiskClass::Low),
        (
            CanonicalRiskRuleV1::ElevatedAndHighSlowPath,
            RiskClass::Elevated,
        ),
        (CanonicalRiskRuleV1::HighOnlySlowPath, RiskClass::High),
    ] {
        let (mut value, trust) = signed_fixture();
        value.inputs.intuition_request.risk_class = risk_class;
        let profile = routing_profile(&value.inputs.intuition_request, risk_rule);
        let expected = decide_calibrated_v4(value.inputs.intuition_request.clone(), &profile)
            .expect("production policy");
        assert!(matches!(
            expected.disposition,
            ProductionDispositionV1::SlowPath(_)
        ));

        // If routing incorrectly selects, these untrusted later inputs fail.
        // SlowPath must stop before they can run or publish a proposal.
        value.inputs.context_request.objective_digest = digest("wrong-context-objective");
        value.inputs.signed_evaluation = None;
        let directory = tempfile::tempdir().expect("directory");
        let path = directory.path().join("authority.json");
        write_authority_file(
            &path,
            &value.owners,
            value.request.snapshot.revocation_frontier_digest(),
        );
        let runner = AgentdIntelligenceProductRunnerV1::new(path, authority_verifier())
            .expect("runner")
            .with_evaluation_trust(trust)
            .expect("host-root trust");
        let coordinator = product_test_coordinator();
        let outcome = runner
            .prepare_for_composition_with_intuition(
                coordinator.composition(),
                value.request,
                value.inputs,
                AgentdIntuitionComputationV1::Product(Box::new(profile)),
            )
            .await
            .expect("profile-controlled canonical preparation");
        assert_eq!(outcome, AgentdIntelligenceProductOutcomeV1::SlowPath);
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[allow(
    clippy::expect_used,
    reason = "Test setup and success assertions intentionally fail the test on unexpected errors."
)]
async fn selected_product_profile_preserves_v4_receipt_and_propensity() {
    for risk_rule in [
        CanonicalRiskRuleV1::HighOnlySlowPath,
        CanonicalRiskRuleV1::ElevatedAndHighSlowPath,
    ] {
        let (value, trust) = signed_fixture();
        let profile = routing_profile(&value.inputs.intuition_request, risk_rule);
        let expected = decide_calibrated_v4(value.inputs.intuition_request.clone(), &profile)
            .expect("production policy");
        let directory = tempfile::tempdir().expect("directory");
        let path = directory.path().join("authority.json");
        write_authority_file(
            &path,
            &value.owners,
            value.request.snapshot.revocation_frontier_digest(),
        );
        let runner = AgentdIntelligenceProductRunnerV1::new(path, authority_verifier())
            .expect("runner")
            .with_evaluation_trust(trust)
            .expect("host-root trust");
        let coordinator = product_test_coordinator();
        let outcome = runner
            .prepare_for_composition_with_intuition(
                coordinator.composition(),
                value.request,
                value.inputs,
                AgentdIntuitionComputationV1::Product(Box::new(profile)),
            )
            .await
            .expect("profile-controlled canonical preparation");
        let AgentdIntelligenceProductOutcomeV1::Ready(prepared) = outcome else {
            panic!("eligible low-risk product profile must be ready");
        };
        assert_eq!(
            prepared.envelope.decision.intuition_receipt_digest,
            expected.receipt_digest
        );
        let ProductionDispositionV1::Selected(candidate_id) = expected.disposition else {
            panic!("expected a selected pure product decision");
        };
        assert_eq!(
            prepared.envelope.decision.decision,
            codex_hepta_intelligence::AdvisoryDecisionV1::Selected {
                candidate_id,
                propensity: expected.propensities[0].probability,
            }
        );
        assert!(!prepared.envelope.authority.grants_any());
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[allow(
    clippy::expect_used,
    reason = "Test setup and success assertions intentionally fail the test on unexpected errors."
)]
async fn signed_evaluation_completes_existing_owner_preparation_and_run_admission() {
    let (value, trust) = signed_fixture();
    let directory = tempfile::tempdir().expect("directory");
    let path = directory.path().join("authority.json");
    write_authority_file(
        &path,
        &value.owners,
        value.request.snapshot.revocation_frontier_digest(),
    );
    let runner = AgentdIntelligenceProductRunnerV1::new(path, authority_verifier())
        .expect("runner")
        .with_evaluation_trust(trust)
        .expect("host-root trust");
    let mut coordinator = product_test_coordinator();
    let outcome = runner
        .prepare_and_admit(&mut coordinator, value.request, value.inputs)
        .await
        .expect("signed preparation");
    let AgentdIntelligenceAdmittedOutcomeV1::Ready {
        prepared,
        run_receipt,
    } = outcome
    else {
        panic!("expected the signed existing path to reach ready");
    };
    assert!(!prepared.envelope.evaluation_receipt_digest.is_zero());
    assert!(!prepared.envelope.authority.grants_any());
    assert_eq!(run_receipt.run_id, prepared.run_snapshot().run_id);
    assert_eq!(run_receipt.phase, crate::RunPhase::ContextAttached);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[allow(
    clippy::expect_used,
    reason = "Test setup and success assertions intentionally fail the test on unexpected errors."
)]
async fn signed_input_cannot_install_host_trust_or_change_actual_context() {
    let (value, _) = signed_fixture();
    let directory = tempfile::tempdir().expect("directory");
    let path = directory.path().join("authority.json");
    write_authority_file(
        &path,
        &value.owners,
        value.request.snapshot.revocation_frontier_digest(),
    );
    let runner =
        AgentdIntelligenceProductRunnerV1::new(path.clone(), authority_verifier()).expect("runner");
    assert!(matches!(
        runner
            .prepare(&product_test_coordinator(), value.request, value.inputs)
            .await,
        Err(AgentdIntelligenceProductError::InvalidAuthorityVerifier)
    ));

    let (mut value, trust) = signed_fixture();
    value.inputs.context_request.items[0].content_digest = digest("substituted-context");
    let runner = AgentdIntelligenceProductRunnerV1::new(path, authority_verifier())
        .expect("runner")
        .with_evaluation_trust(trust)
        .expect("trust");
    assert!(matches!(
        runner
            .prepare(&product_test_coordinator(), value.request, value.inputs)
            .await,
        Err(AgentdIntelligenceProductError::Canonical(
            CanonicalIntelligenceError::PortFailure {
                stage: CanonicalStageV1::EvaluationAdmitted,
                ..
            }
        ))
    ));
}

#[path = "intelligence_product_final_use_tests.rs"]
mod final_use;
