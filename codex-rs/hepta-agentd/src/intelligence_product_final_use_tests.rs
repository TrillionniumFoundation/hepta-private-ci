//! Product fences must run after the sole learning writer has been acquired.

use crate as codex_hepta_agentd;
include!("../tests/support/intuition_policy_fixture.rs");

use super::signed_fixture;
use super::write_authority_file;
use crate::AgentdError;
use crate::AgentdIntuitionServiceErrorV1;
use crate::PreparedAgentdIntuitionDecisionV3;
use crate::intelligence_product::AgentdIntelligenceProductOutcomeV1;
use crate::intelligence_product::AgentdIntelligenceProductRunnerV1;
use crate::intelligence_product::tests::authority_verifier;
use crate::intelligence_product::tests::product_test_coordinator;
use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_types::Generation;
use std::sync::Condvar;
use std::sync::Mutex;
use std::sync::mpsc;
use std::time::Duration;

#[derive(Debug)]
struct WaitingWriterClock {
    calls: AtomicU64,
    now: AtomicU64,
    first_entered: mpsc::Sender<()>,
    released: (Mutex<bool>, Condvar),
}

impl IntuitionPolicyClock for WaitingWriterClock {
    #[allow(
        clippy::expect_used,
        reason = "Race synchronization must not silently fail."
    )]
    fn now(&self) -> Result<u64, AgentdIntuitionPolicyError> {
        if self.calls.fetch_add(1, Ordering::AcqRel) == 0 {
            self.first_entered.send(()).expect("writer held");
            let (released, changed) = &self.released;
            let mut released = released.lock().expect("release lock");
            while !*released {
                released = changed.wait(released).expect("release wait");
            }
        }
        Ok(self.now.load(Ordering::Acquire))
    }
}

#[allow(
    clippy::expect_used,
    reason = "Signed fixture setup must fail on any contract drift."
)]
fn prepared_host(
    learning: Arc<IntuitionPolicyLearningSink>,
    request: CalibratedDecisionRequestV1,
    profile: CanonicalPolicyProfileV1,
) -> (
    Arc<AgentdIntuitionPolicyHostV1>,
    PreparedAgentdIntuitionDecisionV3,
    Option<SignedLearningEvidenceV1>,
) {
    let agent = AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dde").expect("agent");
    let (_, verifier, keys, principals) = trust_material();
    let (scoring, assignment) = commitments(&request, &profile);
    let pins = AgentdIntuitionPolicyPinsV2 {
        policy_profile_digest: canonical_policy_profile_digest_v1(&profile)
            .expect("profile digest"),
        policy_digest: profile.policy_digest,
        policy_generation: PolicyGeneration::new(GENERATION).expect("generation"),
        objective_class_digest: profile.objective_class_digest,
        model_artifact_digest: profile.scorer.model_digest,
        scorer_contract_digest: profile.scorer.scorer_contract_digest,
        calibration_artifact_digest: profile.calibration_artifact_digest,
        ood_artifact_digest: profile.ood_artifact_digest,
        risk_rule_digest: intuition_risk_rule_digest_v1(profile.risk_rule),
        rng_owner_digest: None,
    };
    let host = Arc::new(
        AgentdIntuitionPolicyHostV1::new_product(
            agent.clone(),
            SPAWN_GENERATION,
            verifier.clone(),
            pins,
            learning,
        )
        .expect("host"),
    );
    let signed = [
        (
            LearningEvidenceRoleV1::Generator,
            canonical_completeness_evidence_payload_v1(&request).expect("completeness"),
        ),
        (
            LearningEvidenceRoleV1::Evaluator,
            canonical_profile_qualification_payload_v1(&profile).expect("profile"),
        ),
        (
            LearningEvidenceRoleV1::Observer,
            canonical_runtime_commitment_payload_v2(&request, &profile, &scoring, &assignment)
                .expect("runtime"),
        ),
    ]
    .into_iter()
    .enumerate()
    .map(|(index, (role, payload))| {
        sign_evidence(
            &verifier,
            &principals[index],
            &keys[index],
            role,
            &format!("final-use-{index}"),
            &payload,
        )
    })
    .collect::<Vec<_>>();
    let prepared = host
        .prepare_v3(
            &agent,
            SPAWN_GENERATION,
            request,
            profile,
            scoring,
            assignment,
            IntuitionQualificationEvidenceV2 {
                completeness: &signed[0],
                profile_qualification: &signed[1],
                runtime: &signed[2],
            },
            id("episode:final-use"),
            digest("snapshot:final-use"),
            NOW,
        )
        .expect("prepare");
    let evidence = prepared
        .decision_signing_payload()
        .expect("payload")
        .map(|payload| {
            sign_evidence(
                &verifier,
                &principals[0],
                &keys[0],
                LearningEvidenceRoleV1::Generator,
                "decision:final-use",
                &payload,
            )
        });
    (host, prepared, evidence)
}

#[derive(Clone, Copy)]
enum Drift {
    SignedOwner,
    RunStartExpiry,
    QualificationDuringFence,
}

#[derive(Clone, Copy)]
enum PolicyOutcome {
    Selected,
    Abstained,
    SlowPath,
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[allow(
    clippy::expect_used,
    reason = "The real writer/fence race must fail the test on any lost handshake."
)]
async fn writer_wait_rechecks_signed_owner_and_run_start_before_append() {
    for (drift, policy_outcome) in [
        (Drift::SignedOwner, PolicyOutcome::Selected),
        (Drift::SignedOwner, PolicyOutcome::Abstained),
        (Drift::SignedOwner, PolicyOutcome::SlowPath),
        (Drift::RunStartExpiry, PolicyOutcome::Selected),
        (Drift::QualificationDuringFence, PolicyOutcome::Selected),
    ] {
        let (mut canonical, evaluation_trust) = signed_fixture();
        let directory = tempdir().expect("directory");
        let authority = directory.path().join("authority.json");
        write_authority_file(
            &authority,
            &canonical.owners,
            canonical.request.snapshot.revocation_frontier_digest(),
        );
        let canonical_snapshot = canonical.request.snapshot.clone();
        match policy_outcome {
            PolicyOutcome::Selected => {}
            PolicyOutcome::SlowPath => {
                canonical.inputs.intuition_request.risk_class = RiskClass::High
            }
            PolicyOutcome::Abstained => {
                canonical.inputs.intuition_request.candidates[0].hard_veto = true;
                canonical
                    .inputs
                    .intuition_request
                    .completeness
                    .candidate_set_digest = canonical_candidate_set_digest_v1(
                    &canonical.inputs.intuition_request.candidates,
                )
                .expect("abstained candidate set");
            }
        }
        let frontier = canonical.request.snapshot.revocation_frontier_digest();
        let mut owners = canonical.owners;
        let runner =
            AgentdIntelligenceProductRunnerV1::new(authority.clone(), authority_verifier())
                .expect("runner")
                .with_evaluation_trust(evaluation_trust)
                .expect("evaluation trust");
        let outcome = runner
            .prepare(
                &product_test_coordinator(),
                canonical.request,
                canonical.inputs,
            )
            .await
            .expect("canonical preparation");
        assert!(matches!(
            (policy_outcome, &outcome),
            (
                PolicyOutcome::Selected,
                AgentdIntelligenceProductOutcomeV1::Ready(_)
            ) | (
                PolicyOutcome::Abstained,
                AgentdIntelligenceProductOutcomeV1::Abstained
            ) | (
                PolicyOutcome::SlowPath,
                AgentdIntelligenceProductOutcomeV1::SlowPath
            )
        ));
        runner
            .require_current_snapshot(&canonical_snapshot)
            .expect("initial currentness");

        let issuer_key = SigningKey::from_bytes(&[88; 32]);
        let issuer = IssuerRegistration {
            issuer_id: id("run-start-issuer"),
            key_epoch: Generation::new(1).expect("epoch"),
            verifying_key: issuer_key.verifying_key(),
            revoked: false,
        };
        let claims = SignedMessageClaims {
            issuer_id: issuer.issuer_id.clone(),
            key_epoch: issuer.key_epoch,
            message_id: id("run-start-message"),
            subject_id: id("agent-subject"),
            scope_digest: digest("run-start-scope"),
            payload_digest: digest("run-start-body"),
            sequence: 1,
            expires_at_ms: 160,
        };
        let message = SignedMessage {
            signature: issuer_key.sign(&claims.signing_bytes()).to_bytes(),
            claims,
        };
        message
            .authenticate(
                &issuer,
                message.claims.scope_digest,
                message.claims.payload_digest,
                NOW,
            )
            .expect("initial run-start signature");

        let ledger_path = directory.path().join("ledger");
        let witness_path = directory.path().join("witness");
        File::create(&ledger_path).expect("ledger file");
        File::create(&witness_path).expect("witness file");
        let binding = digest("final-use-ledger");
        let parent = File::open(directory.path()).expect("parent");
        let writer = LedgerWriter::from_durable(
            DurableLedger::create(open_rw(&ledger_path), binding, 16).expect("ledger"),
            LedgerWitnessStore::create(open_rw(&witness_path), binding).expect("witness"),
            trust_material().0,
            &parent,
            &parent,
        )
        .expect("writer");
        let (entered, first_entered) = mpsc::channel();
        let clock = Arc::new(WaitingWriterClock {
            calls: AtomicU64::new(0),
            now: AtomicU64::new(NOW),
            first_entered: entered,
            released: (Mutex::new(false), Condvar::new()),
        });
        let learning = Arc::new(IntuitionPolicyLearningSink::new_with_clock(
            writer,
            clock.clone(),
        ));
        let (mut policy_request, mut profile) = request_and_profile();
        match policy_outcome {
            PolicyOutcome::Selected => {}
            PolicyOutcome::SlowPath => profile.risk_rule = CanonicalRiskRuleV1::AlwaysSlowPath,
            PolicyOutcome::Abstained => {
                policy_request.candidates[0].hard_veto = true;
                policy_request.completeness.candidate_set_digest =
                    canonical_candidate_set_digest_v1(&policy_request.candidates)
                        .expect("abstained policy candidate set");
            }
        }
        let (host, prepared, evidence) =
            prepared_host(learning.clone(), policy_request, profile.clone());
        let mut slow_profile = profile;
        slow_profile.risk_rule = CanonicalRiskRuleV1::AlwaysSlowPath;
        let (slow_host, slow_prepared, _) =
            prepared_host(learning.clone(), request_and_profile().0, slow_profile);
        let before_ledger = std::fs::read(&ledger_path).expect("initial ledger");
        let before_witness = std::fs::read(&witness_path).expect("initial witness");
        let agent = AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dde").expect("agent");
        let blocker_agent = agent.clone();
        let blocker = std::thread::spawn(move || {
            slow_host.commit_v4(
                &blocker_agent,
                SPAWN_GENERATION,
                slow_prepared,
                Digest32::ZERO,
                None,
            )
        });
        first_entered
            .recv_timeout(Duration::from_secs(5))
            .expect("first call owns writer");
        let (started, attempting) = mpsc::channel();
        let (fence_entered, observed_fence) = mpsc::channel();
        let clock_at_fence = clock.clone();
        let worker = std::thread::spawn(move || {
            started.send(()).expect("attempt acknowledged");
            host.commit_v4_checked(
                &agent,
                SPAWN_GENERATION,
                prepared,
                Digest32::ZERO,
                evidence,
                |owner_clock| {
                    fence_entered.send(()).expect("fence entered");
                    runner
                        .require_current_snapshot(&canonical_snapshot)
                        .map_err(|error| {
                            AgentdIntuitionServiceErrorV1::Agentd(AgentdError::Protocol(format!(
                                "currentness: {error}"
                            )))
                        })?;
                    let now = owner_clock.now()?;
                    message
                        .authenticate(
                            &issuer,
                            message.claims.scope_digest,
                            message.claims.payload_digest,
                            now,
                        )
                        .map_err(|error| {
                            AgentdIntuitionServiceErrorV1::Agentd(AgentdError::Invalid(format!(
                                "run-start: {error}"
                            )))
                        })?;
                    if matches!(drift, Drift::QualificationDuringFence) {
                        clock_at_fence.now.store(201, Ordering::Release);
                    }
                    Ok(())
                },
            )
        });
        attempting
            .recv_timeout(Duration::from_secs(5))
            .expect("second call attempted");
        assert!(
            matches!(
                observed_fence.recv_timeout(Duration::from_millis(50)),
                Err(mpsc::RecvTimeoutError::Timeout)
            ),
            "the product fence must wait for the writer lock"
        );
        match drift {
            Drift::SignedOwner => {
                let owner = owners
                    .iter_mut()
                    .find(|owner| owner.owner_id.as_str() == "utility.ndu")
                    .expect("utility owner");
                owner.generation =
                    Generation::new(owner.generation.get() + 1).expect("successor generation");
                write_authority_file(&authority, &owners, frontier);
            }
            Drift::RunStartExpiry => {
                clock.now.store(170, Ordering::Release);
            }
            Drift::QualificationDuringFence => {}
        }
        let (released, changed) = &clock.released;
        *released.lock().expect("release writer") = true;
        changed.notify_all();
        blocker
            .join()
            .expect("blocker thread")
            .expect("slow path succeeds without append");
        observed_fence
            .recv_timeout(Duration::from_secs(5))
            .expect("fence runs after writer acquisition");
        let error = worker
            .join()
            .expect("commit thread")
            .expect_err("changed qualification rejects before append");
        match (drift, error) {
            (
                Drift::SignedOwner,
                AgentdIntuitionServiceErrorV1::Agentd(AgentdError::Protocol(cause)),
            ) => assert!(cause.contains("StaleOwner")),
            (
                Drift::RunStartExpiry,
                AgentdIntuitionServiceErrorV1::Agentd(AgentdError::Invalid(cause)),
            ) => assert!(cause.contains("Expired")),
            (
                Drift::QualificationDuringFence,
                AgentdIntuitionServiceErrorV1::Policy(
                    AgentdIntuitionPolicyError::PreparedEvidenceExpired,
                ),
            ) => {}
            (_, error) => panic!("typed cause was lost: {error:?}"),
        }
        assert_eq!(
            std::fs::read(&ledger_path).expect("final ledger"),
            before_ledger
        );
        assert_eq!(
            std::fs::read(&witness_path).expect("final witness"),
            before_witness
        );
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[allow(
    clippy::expect_used,
    reason = "The prepared result must retain the actual signed evaluation lease."
)]
async fn evaluation_distribution_expiry_rejects_prepared_product_reuse() {
    let now = super::super::wall_clock_ms().expect("clock");
    let expires_at = now + 5_000;
    let (value, trust) = super::signed_fixture_with_distribution_expiry(now, Some(expires_at));
    let directory = tempdir().expect("directory");
    let authority = directory.path().join("authority.json");
    write_authority_file(
        &authority,
        &value.owners,
        value.request.snapshot.revocation_frontier_digest(),
    );
    let runner = AgentdIntelligenceProductRunnerV1::new(authority, authority_verifier())
        .expect("runner")
        .with_evaluation_trust(trust)
        .expect("signed evaluation trust");
    let outcome = runner
        .prepare(&product_test_coordinator(), value.request, value.inputs)
        .await
        .expect("prepare with current evaluation");
    assert!(matches!(
        outcome,
        AgentdIntelligenceProductOutcomeV1::Ready(_)
    ));
    runner
        .require_current_evaluation(expires_at)
        .expect("inclusive root distribution lease");
    assert!(matches!(
        runner.require_current_evaluation(expires_at + 1),
        Err(crate::intelligence_product::AgentdIntelligenceProductError::InvalidAuthorityVerifier)
    ));
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[allow(
    clippy::expect_used,
    reason = "Every retained signature must reject expiry independently of the root lease."
)]
async fn prepared_evaluation_retains_each_signed_expiry_after_consumption() {
    for part in 0..3 {
        let (mut value, trust) = signed_fixture();
        let now = super::super::wall_clock_ms().expect("clock");
        let expires_at = now + 5_000;
        let context = codex_hepta_context_compiler::compile(value.inputs.context_request.clone())
            .expect("context");
        let legal = codex_hepta_intelligence::build_legal_candidates(
            value.request.legal_candidates.clone(),
        )
        .expect("legal set");
        let binding = crate::AgentdEvaluationBindingV1 {
            run_id: value.request.run_id.clone(),
            objective_digest: value.request.snapshot.objective_digest(),
            snapshot_digest: value.request.snapshot.digest(),
            context_receipt_digest: context.context_digest,
            candidate_set_digest: legal.candidate_set_digest,
            selected_candidate_id: id("action.read"),
        };
        let signed = value
            .inputs
            .signed_evaluation
            .as_mut()
            .expect("signed evaluation");
        let (evidence, key) = match part {
            0 => (
                &mut signed.evidence.generator_plan,
                SigningKey::from_bytes(&[31; 32]),
            ),
            1 => (
                &mut signed.evidence.evaluator_bundle,
                SigningKey::from_bytes(&[47; 32]),
            ),
            _ => (
                &mut signed.use_attestation,
                SigningKey::from_bytes(&[47; 32]),
            ),
        };
        evidence.expires_at = expires_at;
        evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
        let payload = crate::intelligence_evaluation_binding_payload_v1(&binding, &signed.evidence)
            .expect("updated use binding");
        signed.use_attestation.payload_digest = Digest32::of_bytes(&payload);
        signed.use_attestation.signature = SigningKey::from_bytes(&[47; 32])
            .sign(&signed.use_attestation.signing_bytes())
            .to_bytes();
        let directory = tempdir().expect("directory");
        let authority = directory.path().join("authority.json");
        write_authority_file(
            &authority,
            &value.owners,
            value.request.snapshot.revocation_frontier_digest(),
        );
        let runner = AgentdIntelligenceProductRunnerV1::new(authority, authority_verifier())
            .expect("runner")
            .with_evaluation_trust(trust)
            .expect("root trust");
        let outcome = runner
            .prepare(&product_test_coordinator(), value.request, value.inputs)
            .await
            .expect("unexpired signed preparation");
        let AgentdIntelligenceProductOutcomeV1::Ready(prepared) = outcome else {
            panic!("selected signed preparation");
        };
        runner
            .require_current_evaluation(expires_at + 1)
            .expect("root distribution remains valid");
        prepared
            .revalidate_evaluation(expires_at)
            .expect("inclusive signed expiry");
        assert!(
            prepared.revalidate_evaluation(expires_at + 1).is_err(),
            "expired signature {part} must not survive in a digest-only prepared result"
        );
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[allow(
    clippy::expect_used,
    reason = "A scheduled signer revocation is independently authenticated fixture input."
)]
async fn prepared_evaluation_rechecks_scheduled_signer_revocation() {
    let now = super::super::wall_clock_ms().expect("clock");
    let revoked_at = now + 5_000;
    let (value, trust) = super::signed_fixture_with_trust_windows(now, None, Some(revoked_at));
    let directory = tempdir().expect("directory");
    let authority = directory.path().join("authority.json");
    write_authority_file(
        &authority,
        &value.owners,
        value.request.snapshot.revocation_frontier_digest(),
    );
    let runner = AgentdIntelligenceProductRunnerV1::new(authority, authority_verifier())
        .expect("runner")
        .with_evaluation_trust(trust)
        .expect("signed trust");
    let outcome = runner
        .prepare(&product_test_coordinator(), value.request, value.inputs)
        .await
        .expect("prepare before scheduled revocation");
    let AgentdIntelligenceProductOutcomeV1::Ready(prepared) = outcome else {
        panic!("ready");
    };
    runner
        .require_current_evaluation(revoked_at)
        .expect("root lease still valid");
    prepared
        .revalidate_evaluation(revoked_at - 1)
        .expect("signer valid before revocation");
    assert!(matches!(
        prepared.revalidate_evaluation(revoked_at),
        Err(crate::AgentdIntelligenceEvaluationError::Evidence(
            codex_hepta_learning_ledger::SignedEvidenceError::Revoked
        ))
    ));
}
