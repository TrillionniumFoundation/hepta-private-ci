//! Adversarial prepare/commit tests using the existing signed, durable fixture.
//! These exercise the product host, not a live Agentd process or operator approval.
// Reuse the exact trust/ledger fixture and retain its crash/reopen regression.
include!("intuition_policy_product_v3.rs");

use std::sync::Condvar;
use std::sync::Mutex as StdMutex;
use std::sync::mpsc;
use std::thread;

#[derive(Debug)]
struct SequencedBlockingClock {
    state: StdMutex<BlockingClockState>,
    changed: Condvar,
}

#[derive(Debug)]
struct BlockingClockState {
    now: u64,
    entered: usize,
    released: usize,
}

impl SequencedBlockingClock {
    fn new(now: u64) -> Self {
        Self {
            state: StdMutex::new(BlockingClockState {
                now,
                entered: 0,
                released: 0,
            }),
            changed: Condvar::new(),
        }
    }

    fn set_now(&self, now: u64) {
        self.state.lock().expect("clock state").now = now;
    }

    fn wait_for_entered(&self, count: usize) {
        let mut state = self.state.lock().expect("clock state");
        while state.entered < count {
            state = self.changed.wait(state).expect("clock wait");
        }
    }

    fn entered(&self) -> usize {
        self.state.lock().expect("clock state").entered
    }

    fn release_through(&self, count: usize) {
        let mut state = self.state.lock().expect("clock state");
        state.released = state.released.max(count);
        self.changed.notify_all();
    }
}

impl IntuitionPolicyClock for SequencedBlockingClock {
    fn now(&self) -> Result<u64, AgentdIntuitionPolicyError> {
        let mut state = self.state.lock().expect("clock state");
        state.entered += 1;
        let call = state.entered;
        self.changed.notify_all();
        while state.released < call {
            state = self.changed.wait(state).expect("clock release");
        }
        Ok(state.now)
    }
}

#[test]
fn prepared_decision_rejects_every_changed_host_pin_before_writing() {
    let agent_id = AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dde").expect("agent");
    let (request, profile) = request_and_profile();
    let (scoring, assignment) = commitments(&request, &profile);
    let (activated, verifier, keys, principals) = trust_material();
    let directory = tempdir().expect("ledger directory");
    let ledger_path = directory.path().join("ledger");
    let witness_path = directory.path().join("witness");
    File::create(&ledger_path).expect("ledger file");
    File::create(&witness_path).expect("witness file");
    let binding = digest("binding:commit-boundary");
    let ledger = DurableLedger::create(open_rw(&ledger_path), binding, 64).expect("ledger");
    let witness = LedgerWitnessStore::create(open_rw(&witness_path), binding).expect("witness");
    let parent = File::open(directory.path()).expect("parent");
    let writer =
        LedgerWriter::from_durable(ledger, witness, activated, &parent, &parent).expect("writer");
    let clock = Arc::new(TestIntuitionClock::new(NOW));
    let learning = Arc::new(IntuitionPolicyLearningSink::new_with_clock(
        writer,
        clock.clone(),
    ));
    let pins = AgentdIntuitionPolicyPinsV2 {
        policy_profile_digest: canonical_policy_profile_digest_v1(&profile).expect("profile"),
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
    let host = AgentdIntuitionPolicyHostV1::new_product(
        agent_id.clone(),
        SPAWN_GENERATION,
        verifier.clone(),
        pins.clone(),
        learning.clone(),
    )
    .expect("host");
    let completeness = sign_evidence(
        &verifier,
        &principals[0],
        &keys[0],
        LearningEvidenceRoleV1::Generator,
        "evidence:commit-boundary:completeness",
        &canonical_completeness_evidence_payload_v1(&request).expect("completeness"),
    );
    let profile_evidence = sign_evidence(
        &verifier,
        &principals[1],
        &keys[1],
        LearningEvidenceRoleV1::Evaluator,
        "evidence:commit-boundary:profile",
        &canonical_profile_qualification_payload_v1(&profile).expect("profile"),
    );
    let runtime_evidence = sign_evidence(
        &verifier,
        &principals[2],
        &keys[2],
        LearningEvidenceRoleV1::Observer,
        "evidence:commit-boundary:runtime",
        &canonical_runtime_commitment_payload_v2(&request, &profile, &scoring, &assignment)
            .expect("runtime"),
    );
    let prepared = host
        .prepare_v3(
            &agent_id,
            SPAWN_GENERATION,
            request,
            profile,
            scoring,
            assignment,
            IntuitionQualificationEvidenceV2 {
                completeness: &completeness,
                profile_qualification: &profile_evidence,
                runtime: &runtime_evidence,
            },
            id("episode:commit-boundary"),
            digest("snapshot:commit-boundary"),
            NOW,
        )
        .expect("prepared");
    let payload = prepared
        .decision_signing_payload()
        .expect("payload")
        .expect("selected");
    let mut decision_evidence = sign_evidence(
        &verifier,
        &principals[0],
        &keys[0],
        LearningEvidenceRoleV1::Generator,
        "evidence:commit-boundary:decision",
        &payload,
    );
    // A later-valid Decision signature must not extend the original three-party
    // qualification, whose earliest expiry is 200.
    decision_evidence.expires_at = 400;
    decision_evidence.signature = keys[0].sign(&decision_evidence.signing_bytes()).to_bytes();

    for field in 0..10 {
        let mut changed = pins.clone();
        match field {
            0 => changed.policy_profile_digest = digest("changed:profile"),
            1 => changed.policy_digest = digest("changed:policy"),
            2 => changed.policy_generation = PolicyGeneration::new(5).expect("generation"),
            3 => changed.objective_class_digest = digest("changed:class"),
            4 => changed.model_artifact_digest = digest("changed:model"),
            5 => changed.scorer_contract_digest = digest("changed:scorer"),
            6 => changed.calibration_artifact_digest = digest("changed:calibration"),
            7 => changed.ood_artifact_digest = digest("changed:ood"),
            8 => changed.risk_rule_digest = digest("changed:risk"),
            9 => changed.rng_owner_digest = Some(digest("changed:rng")),
            _ => unreachable!(),
        }
        let other = AgentdIntuitionPolicyHostV1::new_product(
            agent_id.clone(),
            SPAWN_GENERATION,
            verifier.clone(),
            changed,
            learning.clone(),
        )
        .expect("other host with same identity, generation and trust");
        assert!(matches!(
            other.commit_v4(
                &agent_id,
                SPAWN_GENERATION,
                prepared.clone(),
                Digest32::ZERO,
                Some(decision_evidence.clone()),
            ),
            Err(AgentdIntuitionPolicyError::PreparedProfileMismatch)
        ));
    }
    clock.set(NOW - 1);
    assert!(matches!(
        host.commit_v4(
            &agent_id,
            SPAWN_GENERATION,
            prepared.clone(),
            Digest32::ZERO,
            Some(decision_evidence.clone()),
        ),
        Err(AgentdIntuitionPolicyError::PreparedClockReversed)
    ));
    for now in [200, 201, 399] {
        clock.set(now);
        assert!(matches!(
            host.commit_v4(
                &agent_id,
                SPAWN_GENERATION,
                prepared.clone(),
                Digest32::ZERO,
                Some(decision_evidence.clone()),
            ),
            Err(AgentdIntuitionPolicyError::PreparedEvidenceExpired)
        ));
    }
    clock.set(NOW);
    // Missing/forged evidence and stale daemon generation are rejected before
    // any append. The final receipt's sequence below proves no rejected attempt
    // created a hidden Decision.
    assert!(matches!(
        host.commit_v4(
            &agent_id,
            SPAWN_GENERATION,
            prepared.clone(),
            Digest32::ZERO,
            None,
        ),
        Err(AgentdIntuitionPolicyError::MissingDecisionEvidence)
    ));
    assert!(matches!(
        host.commit_v4(
            &agent_id,
            SPAWN_GENERATION + 1,
            prepared.clone(),
            Digest32::ZERO,
            Some(decision_evidence.clone()),
        ),
        Err(AgentdIntuitionPolicyError::GenerationFence)
    ));
    let mut forged = decision_evidence.clone();
    forged.signature[0] ^= 1;
    assert!(matches!(
        host.commit_v4(
            &agent_id,
            SPAWN_GENERATION,
            prepared.clone(),
            Digest32::ZERO,
            Some(forged),
        ),
        Err(AgentdIntuitionPolicyError::Learning(_))
    ));
    let wrong_role = sign_evidence(
        &verifier,
        &principals[1],
        &keys[1],
        LearningEvidenceRoleV1::Evaluator,
        "evidence:commit-boundary:wrong-role",
        &payload,
    );
    assert!(matches!(
        host.commit_v4(
            &agent_id,
            SPAWN_GENERATION,
            prepared.clone(),
            Digest32::ZERO,
            Some(wrong_role),
        ),
        Err(AgentdIntuitionPolicyError::Learning(_))
    ));
    let replay_prepared = prepared.clone();
    let post_rotation_prepared = prepared.clone();
    let post_rotation_evidence = decision_evidence.clone();
    clock.set(199);
    let committed = host
        .commit_v4(
            &agent_id,
            SPAWN_GENERATION,
            prepared,
            Digest32::ZERO,
            Some(decision_evidence.clone()),
        )
        .expect("unchanged host and valid evidence lifetime");
    let first = committed.learning.expect("durable receipt");
    assert_eq!(
        first.sequence.get(),
        1,
        "a rejected prepare/commit attempt must not append a Decision"
    );
    let replay = host
        .commit_v4(
            &agent_id,
            SPAWN_GENERATION,
            replay_prepared,
            Digest32::ZERO,
            Some(decision_evidence),
        )
        .expect("exact retry after all rejected attempts");
    let replay = replay.learning.expect("replay receipt");
    assert_eq!(replay.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(replay.sequence, first.sequence);
    assert_eq!(replay.event_digest, first.event_digest);
    assert_eq!(replay.chain_digest, first.chain_digest);

    let (root, successor) =
        successor_trust_distribution(&keys, &principals, 2, Some(175));
    learning
        .rotate_trust(&root, successor, 199)
        .expect("rotate to revoked-generator trust generation");
    assert!(matches!(
        host.commit_v4(
            &agent_id,
            SPAWN_GENERATION,
            post_rotation_prepared,
            Digest32::ZERO,
            Some(post_rotation_evidence),
        ),
        Err(AgentdIntuitionPolicyError::PreparedOwnerMismatch)
    ));
}

#[test]
fn writer_wait_samples_fresh_clock_and_expires_before_any_ledger_mutation() {
    let agent_id = AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dde").expect("agent");
    let (request, profile) = request_and_profile();
    let (scoring, assignment) = commitments(&request, &profile);
    let (activated, verifier, keys, principals) = trust_material();
    let directory = tempdir().expect("ledger directory");
    let ledger_path = directory.path().join("ledger");
    let witness_path = directory.path().join("witness");
    File::create(&ledger_path).expect("ledger file");
    File::create(&witness_path).expect("witness file");
    let binding = digest("binding:writer-wait-expiry");
    let ledger = DurableLedger::create(open_rw(&ledger_path), binding, 64).expect("ledger");
    let witness = LedgerWitnessStore::create(open_rw(&witness_path), binding).expect("witness");
    let parent = File::open(directory.path()).expect("parent");
    let writer =
        LedgerWriter::from_durable(ledger, witness, activated, &parent, &parent).expect("writer");
    let clock = Arc::new(SequencedBlockingClock::new(NOW));
    let learning = Arc::new(IntuitionPolicyLearningSink::new_with_clock(
        writer,
        clock.clone(),
    ));
    let pins = AgentdIntuitionPolicyPinsV2 {
        policy_profile_digest: canonical_policy_profile_digest_v1(&profile).expect("profile"),
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
            agent_id.clone(),
            SPAWN_GENERATION,
            verifier.clone(),
            pins,
            learning,
        )
        .expect("host"),
    );
    let completeness = sign_evidence(
        &verifier,
        &principals[0],
        &keys[0],
        LearningEvidenceRoleV1::Generator,
        "evidence:writer-wait:completeness",
        &canonical_completeness_evidence_payload_v1(&request).expect("completeness"),
    );
    let profile_evidence = sign_evidence(
        &verifier,
        &principals[1],
        &keys[1],
        LearningEvidenceRoleV1::Evaluator,
        "evidence:writer-wait:profile",
        &canonical_profile_qualification_payload_v1(&profile).expect("profile"),
    );
    let runtime_evidence = sign_evidence(
        &verifier,
        &principals[2],
        &keys[2],
        LearningEvidenceRoleV1::Observer,
        "evidence:writer-wait:runtime",
        &canonical_runtime_commitment_payload_v2(&request, &profile, &scoring, &assignment)
            .expect("runtime"),
    );
    let prepared = host
        .prepare_v3(
            &agent_id,
            SPAWN_GENERATION,
            request,
            profile,
            scoring,
            assignment,
            IntuitionQualificationEvidenceV2 {
                completeness: &completeness,
                profile_qualification: &profile_evidence,
                runtime: &runtime_evidence,
            },
            id("episode:writer-wait"),
            digest("snapshot:writer-wait"),
            NOW,
        )
        .expect("prepared");
    let payload = prepared
        .decision_signing_payload()
        .expect("payload")
        .expect("selected");
    let decision_evidence = sign_evidence(
        &verifier,
        &principals[0],
        &keys[0],
        LearningEvidenceRoleV1::Generator,
        "evidence:writer-wait:decision",
        &payload,
    );

    let first_host = host.clone();
    let first_agent = agent_id.clone();
    let first_prepared = prepared.clone();
    let first_evidence = decision_evidence.clone();
    let first = thread::spawn(move || {
        first_host.commit_v4(
            &first_agent,
            SPAWN_GENERATION,
            first_prepared,
            Digest32::ZERO,
            Some(first_evidence),
        )
    });
    clock.wait_for_entered(1);

    let second_host = host.clone();
    let second_agent = agent_id.clone();
    let second_prepared = prepared.clone();
    let second_evidence = decision_evidence.clone();
    let (attempted_tx, attempted_rx) = mpsc::channel();
    let second = thread::spawn(move || {
        attempted_tx.send(()).expect("attempt signal");
        second_host.commit_v4(
            &second_agent,
            SPAWN_GENERATION,
            second_prepared,
            Digest32::ZERO,
            Some(second_evidence),
        )
    });
    attempted_rx.recv().expect("second attempt started");
    assert_eq!(clock.entered(), 1, "second commit must wait for writer lock");

    clock.set_now(200);
    clock.release_through(1);
    assert!(matches!(
        first.join().expect("first thread"),
        Err(AgentdIntuitionPolicyError::PreparedEvidenceExpired)
    ));
    clock.wait_for_entered(2);
    clock.release_through(2);
    assert!(matches!(
        second.join().expect("second thread"),
        Err(AgentdIntuitionPolicyError::PreparedEvidenceExpired)
    ));

    clock.set_now(199);
    clock.release_through(3);
    let committed = host
        .commit_v4(
            &agent_id,
            SPAWN_GENERATION,
            prepared,
            Digest32::ZERO,
            Some(decision_evidence),
        )
        .expect("fresh final-use time commits once");
    assert_eq!(committed.learning.expect("receipt").sequence.get(), 1);
}
