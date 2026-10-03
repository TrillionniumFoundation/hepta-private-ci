use super::*;
use crate::intelligence_product::evaluation_tests::evidence_fixture;
use codex_hepta_intelligence::build_legal_candidates;

pub(super) fn signed_fixture() -> (
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
    let prepared: PreparedAgentdIntelligenceRunV1 = *prepared;
    assert!(!prepared.envelope.evaluation_receipt_digest.is_zero());
    assert!(!prepared.envelope.authority.grants_any());
    let snapshot = prepared.run_snapshot();
    assert_eq!(
        run_receipt,
        crate::RunReceipt {
            run_id: snapshot.run_id,
            revision: 2,
            phase: crate::RunPhase::ContextAttached,
            context_digest: Some(prepared.envelope.context_receipt_digest.to_string()),
            authority_epoch: snapshot.authority_epoch,
            generation: snapshot.generation,
            fence_digest: snapshot.fence_digest,
            deadline_ms: snapshot.deadline_ms,
            cancel_reason: None,
            cancel_ack_deadline_ms: None,
            compilation_receipt_digest: Some(prepared.envelope.envelope_digest.to_string()),
            terminal_observed: false,
            idempotent: false,
        }
    );
}

#[cfg(feature = "qualification-legacy-learning-write")]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn randomized_selected_decision_preserves_intrinsic_abstain_and_exact_propensity() {
    let (mut value, trust) = signed_fixture();
    let legal = build_legal_candidates(value.request.legal_candidates.clone()).expect("legal set");
    let abstain_probability = probability(ProbabilityQ32::ONE.raw() / 4);
    let selected_probability = probability(ProbabilityQ32::ONE.raw() - abstain_probability.raw());
    let intuition = &mut value.inputs.intuition_request;
    intuition.candidates[0].assignment_probability = selected_probability;
    intuition.assignment = AssignmentModeV1::CounterBased {
        random_stream_digest: digest("randomized-qualification-stream"),
        draw: probability(ProbabilityQ32::ONE.raw() / 2),
        abstain_probability,
    };
    intuition.completeness.candidate_set_digest =
        canonical_candidate_set_digest_v1(&intuition.candidates).expect("randomized candidate set");
    let intuition_receipt = decide_calibrated_v2(intuition.clone()).expect("randomized policy");
    assert_eq!(
        (
            &intuition_receipt.disposition,
            &intuition_receipt.propensities,
            intuition_receipt.abstain_probability,
            intuition_receipt.slow_path_probability,
        ),
        (
            &CalibratedDispositionV1::Selected(id("action.read")),
            &vec![codex_hepta_intuition::CalibratedCandidatePropensityV1 {
                candidate_id: id("action.read"),
                probability: selected_probability,
            }],
            abstain_probability,
            ProbabilityQ32::ZERO,
        )
    );

    let directory = tempfile::tempdir().expect("directory");
    let authority = directory.path().join("authority.json");
    write_authority_file(
        &authority,
        &value.owners,
        value.request.snapshot.revocation_frontier_digest(),
    );
    let runner = AgentdIntelligenceProductRunnerV1::new(authority, authority_verifier())
        .expect("runner")
        .with_evaluation_trust(trust)
        .expect("host-root trust");
    let outcome = runner
        .prepare(&product_test_coordinator(), value.request, value.inputs)
        .await
        .expect("signed randomized preparation");
    let AgentdIntelligenceProductOutcomeV1::Ready(prepared) = outcome else {
        panic!("the counter-based draw must select the action");
    };
    assert_eq!(prepared.candidate_ids, vec![id("action.read")]);
    assert_eq!(
        (
            prepared.envelope.candidate_set_digest,
            prepared.envelope.decision.candidate_set_digest,
            prepared.envelope.decision.intuition_receipt_digest,
            &prepared.envelope.decision.decision,
        ),
        (
            legal.candidate_set_digest,
            legal.candidate_set_digest,
            intuition_receipt.receipt_digest,
            &AdvisoryDecisionV1::Selected {
                candidate_id: id("action.read"),
                propensity: selected_probability,
            },
        )
    );
    let prepared_before = prepared.clone();
    let expected = LedgerEvent::Decision(EpisodeDecision {
        record_id: prepared.envelope.run_id.clone(),
        episode_id: id("episode.randomized"),
        objective_digest: prepared.envelope.objective_digest,
        policy_id: id("intuition.policy"),
        candidate_ids: vec![id("abstain"), id("action.read")],
        selected_candidate_id: id("action.read"),
        selected_propensity: selected_probability,
        completeness: CandidateSetCompleteness::Complete,
        support_digest: prepared.dispatch_proposal_digest,
    });
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(directory.path().join("ledger"))
        .expect("create ledger");
    let mut ledger = DurableLedger::create(file, digest("randomized-qualification-binding"), 16)
        .expect("ledger");
    runner
        .append_decision(
            &mut ledger,
            Digest32::ZERO,
            &prepared,
            id("episode.randomized"),
            id("intuition.policy"),
        )
        .expect("randomized decision append");
    assert_eq!(ledger.records().expect("records")[0].event, expected);
    assert_eq!(prepared, prepared_before);
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
