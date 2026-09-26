#![allow(clippy::unwrap_used)]
//! Synthetic evaluation data through the real runner, daemon, AuthBus and SQLite.
use super::*;
use codex_hepta_agentd::AgentdEvaluationEvidenceSinkV1;
use codex_hepta_agentd::evaluation_publication_envelope_payload;
use codex_hepta_agentd::evaluation_publication_evidence_id;
use codex_hepta_intelligence_eval::IndependentEvaluationDispositionV1;
use codex_hepta_intelligence_eval::ProductQualificationEvidenceSinkV1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_types::Digest32;
use std::sync::Arc;
use std::sync::Mutex;

#[allow(dead_code)]
#[path = "../../../hepta-intelligence-eval/tests/support/product_qualification_fixture.rs"]
mod qualified;

const EVALUATOR: &str = "issuer:product-evaluator";

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn product_runner_publishes_through_real_agentd_and_recovers_same_signed_intent() -> Result<()>
{
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT_ID, "learning-eval-product-publication")?;
    let model = core_test_support::responses::start_mock_server().await;
    MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;
    let generator_key = SigningKey::from_bytes(&[61; 32]);
    let evaluator_key = SigningKey::from_bytes(&[62; 32]);
    let trust_file = agent.layout.home_root().join("evidence-trust.json");
    std::fs::set_permissions(
        agent.layout.home_root(),
        std::fs::Permissions::from_mode(0o700),
    )?;
    write_trust(
        &trust_file,
        &agent.agent_id.to_string(),
        &[TrustEntry {
            issuer_id: EVALUATOR,
            key: &evaluator_key,
            revoked: false,
            roles: &["evaluator"],
        }],
    )?;
    fleet.start_with_evidence_trust_file(&agent, &trust_file)?;
    let (control, _) = fleet.wait_ready(&agent, 1).await?;
    let control = Arc::new(control);
    let now = now_ms()?;
    let objective = Digest32::of_bytes(b"product-evaluation-objective");
    let scope = Digest32::of_bytes(b"product-evaluation-scope");
    let principal = |name: &str, key: &SigningKey| AuthenticatedPrincipalV1 {
        principal_id: StableId::new(name).unwrap(),
        credential_chain_digest: Digest32::of_bytes(name.as_bytes()),
        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
        scope_digest: scope,
        authority_epoch: 7,
        authenticated_at: now - 10,
        expires_at: now + 300_000,
    };
    let generator = principal("issuer:product-generator", &generator_key);
    let evaluator = principal(EVALUATOR, &evaluator_key);
    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: scope,
        objective_digest: objective,
        authority_epoch: 7,
        signers: vec![
            TrustedLearningSignerV1 {
                principal: generator.clone(),
                controller_id: StableId::new("controller:generator").unwrap(),
                verifying_key: generator_key.verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Generator],
                revoked_at: None,
            },
            TrustedLearningSignerV1 {
                principal: evaluator.clone(),
                controller_id: StableId::new("controller:evaluator").unwrap(),
                verifying_key: evaluator_key.verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Evaluator],
                revoked_at: None,
            },
        ],
    })?;
    let candidate = EvidenceCandidateV1 {
        candidate_id: "candidate:product-evaluation".to_string(),
        source_commit: "a".repeat(40),
        source_tree: "b".repeat(40),
    };
    let retained = Arc::new(Mutex::new(None));
    let retained_for_job = Arc::clone(&retained);
    let client = Arc::clone(&control);
    let runtime = tokio::runtime::Handle::current();
    let candidate_for_job = candidate.clone();
    let evidence_key = evaluator_key.clone();
    let product = tokio::task::spawn_blocking(move || {
        qualified::qualify_with_sink(
            qualified::QualificationCase {
                objective,
                dataset: Digest32::of_bytes(b"fixture-owner-dataset"),
                candidate: StableId::new(&candidate_for_job.candidate_id).unwrap(),
                baseline: StableId::new("baseline").unwrap(),
                snapshot_ids: vec![StableId::new("snapshot-1").unwrap()],
            },
            &verifier,
            generator,
            evaluator,
            (&generator_key, &evaluator_key),
            now,
            move |payload| {
                let envelope = base_evidence(
                    &evaluation_publication_evidence_id(&StableId::new("product-plan").unwrap())
                        .unwrap()
                        .to_string(),
                    candidate_for_job,
                    EvidenceClaimClassV1::Causal,
                    EvidenceIssuerRoleV1::Evaluator,
                    now,
                    Some(now + 300_000),
                    evaluation_publication_envelope_payload(payload),
                );
                let request = signed_request(EVALUATOR, &evidence_key, 1, &envelope).unwrap();
                // Model the existing operation owner's persisted intent; never make
                // a new message identity for an unknown result or restarted client.
                *retained_for_job.lock().unwrap() = Some((request.clone(), envelope));
                Box::new(
                    AgentdEvaluationEvidenceSinkV1::from_signed_intent(client, runtime, request)
                        .unwrap(),
                )
            },
        )
    })
    .await?;
    let (request, envelope) = retained.lock().unwrap().take().unwrap();
    ensure!(
        product.receipt.publication_digest
            == Digest32::of_bytes(&qualification_envelope_bytes(&envelope)?)
    );
    let refs = control
        .query_kernel_evidence(KernelEvidenceQueryV1 {
            candidate: wire_candidate(&candidate),
            claim_class: "causal".to_string(),
        })
        .await?;
    ensure!(refs.len() == 1 && refs[0].evidence_id == envelope.evidence_id);

    // The same signed ingress can reconcile a previously committed write after
    // process restart. The normal daemon reconstructs its actual SQLite owner.
    fleet
        .supervisor
        .restart(&agent.agent_id, std::time::Instant::now())?;
    let (restarted, _) = fleet.wait_new_spawn(&agent, 1).await?;
    let restarted = Arc::new(restarted);
    let runtime = tokio::runtime::Handle::current();
    let client = Arc::clone(&restarted);
    let original = product.receipt.clone();
    let retry = request.clone();
    let repeated = tokio::task::spawn_blocking(move || {
        let mut sink =
            AgentdEvaluationEvidenceSinkV1::from_signed_intent(client, runtime, retry).unwrap();
        let result = sink
            .persist(original.temporal_execution_digest, &original.decision)
            .unwrap();
        let mut modified = original.decision.clone();
        modified.decision.disposition = IndependentEvaluationDispositionV1::Ineligible;
        assert!(
            sink.persist(original.temporal_execution_digest, &modified)
                .is_err()
        );
        result
    })
    .await?;
    ensure!(repeated == product.receipt.publication_digest);
    let refs = restarted
        .query_kernel_evidence(KernelEvidenceQueryV1 {
            candidate: wire_candidate(&candidate),
            claim_class: "causal".to_string(),
        })
        .await?;
    ensure!(
        refs.len() == 1,
        "exact reconciliation appended duplicate evidence"
    );

    // The ordinary evidence host reloads current trust for each physical append,
    // including an exact retry. A cached signed request cannot defeat revocation.
    write_trust(
        &trust_file,
        &agent.agent_id.to_string(),
        &[TrustEntry {
            issuer_id: EVALUATOR,
            key: &evidence_key_for_revocation(),
            revoked: true,
            roles: &["evaluator"],
        }],
    )?;
    let runtime = tokio::runtime::Handle::current();
    let original = product.receipt;
    let refused = tokio::task::spawn_blocking(move || {
        let mut sink =
            AgentdEvaluationEvidenceSinkV1::from_signed_intent(restarted, runtime, request)
                .unwrap();
        sink.persist(original.temporal_execution_digest, &original.decision)
    })
    .await?;
    ensure!(
        refused.is_err(),
        "revoked evidence writer returned publication success"
    );
    Ok(())
}

fn evidence_key_for_revocation() -> SigningKey {
    SigningKey::from_bytes(&[62; 32])
}
