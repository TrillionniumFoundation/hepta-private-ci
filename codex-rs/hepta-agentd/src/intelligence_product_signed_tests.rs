use super::*;
use crate::intelligence_product::evaluation_tests::evidence_fixture;
use codex_hepta_intelligence::build_legal_candidates;
use pretty_assertions::assert_eq;

fn signed_fixture() -> (
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
    let (trust, signed) = evidence_fixture(&binding, wall_clock_ms().expect("clock"));
    value.inputs.signed_evaluation = Some(signed);
    (value, trust)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
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
async fn durable_objective_deadline_cannot_be_extended_by_owner_preparation() {
    let (value, trust) = signed_fixture();
    let directory = tempfile::tempdir().expect("directory");
    let path = directory.path().join("authority.json");
    write_authority_file(
        &path,
        &value.owners,
        value.request.snapshot.revocation_frontier_digest(),
    );
    let runner = AgentdIntelligenceProductRunnerV1::new(path.clone(), authority_verifier())
        .expect("runner")
        .with_evaluation_trust(trust)
        .expect("host-root trust");
    let mut coordinator = product_test_coordinator();
    let AgentdIntelligenceProductOutcomeV1::Ready(mut prepared) = runner
        .prepare(&coordinator, value.request, value.inputs)
        .await
        .expect("real owner preparation")
    else {
        panic!("expected the signed existing path to reach ready");
    };
    let mut expected_snapshot = prepared.run_snapshot();
    let mut expected_attachment = prepared.context_attachment();
    let original_deadline_ms = expected_snapshot.deadline_ms;
    let objective_deadline_ms = original_deadline_ms - 10;
    expected_snapshot.deadline_ms = objective_deadline_ms;
    expected_attachment.deadline_ms = objective_deadline_ms;
    prepared.bind_to_objective_deadline(objective_deadline_ms * 1_000 + 999);
    assert_eq!(prepared.run_snapshot(), expected_snapshot);
    assert_eq!(prepared.context_attachment(), expected_attachment);
    // Repeat the real owner composition with a different computation budget.
    // Its local clock/budget deadline must not replace the durable identity.
    let (mut retry_value, retry_trust) = signed_fixture();
    retry_value.request.budget.total_micros += 1_000_000;
    let retry_runner = AgentdIntelligenceProductRunnerV1::new(path, authority_verifier())
        .expect("retry runner")
        .with_evaluation_trust(retry_trust)
        .expect("retry host-root trust");
    let AgentdIntelligenceProductOutcomeV1::Ready(mut retry) = retry_runner
        .prepare(&coordinator, retry_value.request, retry_value.inputs)
        .await
        .expect("repeated real owner preparation")
    else {
        panic!("expected signed retry preparation to reach ready");
    };
    assert_ne!(retry.run_snapshot().deadline_ms, original_deadline_ms);
    let mut expected_retry_snapshot = retry.run_snapshot();
    let mut expected_retry_attachment = retry.context_attachment();
    expected_retry_snapshot.deadline_ms = objective_deadline_ms;
    expected_retry_attachment.deadline_ms = objective_deadline_ms;
    retry.bind_to_objective_deadline(objective_deadline_ms * 1_000 + 999);
    assert_eq!(retry.run_snapshot(), expected_retry_snapshot);
    assert_eq!(retry.context_attachment(), expected_retry_attachment);
    let snapshot = prepared.run_snapshot();
    assert_eq!(
        coordinator.start_run(
            objective_deadline_ms,
            crate::RunSnapshot {
                run_id: snapshot.run_id,
                request_digest: snapshot.request_digest,
                objective_digest: snapshot.objective_digest,
                body_digest: snapshot.body_digest,
                artifact_set_digest: snapshot.artifact_set_digest,
                authority_epoch: snapshot.authority_epoch,
                generation: snapshot.generation,
                fence_digest: snapshot.fence_digest,
                deadline_ms: snapshot.deadline_ms,
            },
        ),
        Err(crate::AgentRunError::InvalidDeadline),
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
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
