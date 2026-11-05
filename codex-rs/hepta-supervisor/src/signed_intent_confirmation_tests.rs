use super::*;
use crate::signed_authority::CompletionPublicationObservationV1;
use crate::signed_authority::H7H89ProductionTransition;
use crate::signed_authority::H7PqProductionRecoverySigner;
use crate::signed_authority::UnknownRecoveryPredecessorV1;
use crate::signed_authority::pq_tests::AuthorityFixture;
use crate::signed_authority::pq_tests::fixture_at;
use crate::signed_authority::pq_tests::key;
use codex_hepta_fleet::ReleaseBinding;
use codex_hepta_fleet::ReleaseId;
use pretty_assertions::assert_eq;

struct Fixture {
    authority: AuthorityFixture,
    intent: SignedSupervisorIntent,
    source: ReleaseBinding,
    predecessor: UnknownRecoveryPredecessorV1,
}

impl Fixture {
    fn new() -> Self {
        let authority = fixture_at(/*issued*/ 100, /*expires*/ 500);
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap();
        let grant = authority
            .grant
            .sign(
                &agent,
                "v1",
                "v2",
                H7H89ProductionTransition::Upgrade,
                &authority.envelope,
                /*expected_control_revision*/ 3,
                /*expected_lifecycle_generation*/ 5,
                /*authority_epoch*/ 7,
                /*issued_at_unix_seconds*/ 100,
                /*expires_at_unix_seconds*/ 400,
            )
            .unwrap();
        let intent = SignedSupervisorIntent::new(
            grant.grant_sha256.clone(),
            agent.to_string(),
            H7H89ProductionTransition::Upgrade,
            "v1",
            "v2",
            /*expected_control_revision*/ 3,
            /*expected_lifecycle_generation*/ 5,
            /*authority_epoch*/ 7,
            SignedIntentStatus::RecoveryRequired,
        )
        .unwrap()
        .bind_authority(&grant, &authority.envelope, &authority.verifier)
        .unwrap();
        let digest = |value: &[u8]| Sha256Digest::for_bytes(value).as_str().to_string();
        let source = ReleaseBinding {
            release_id: ReleaseId::parse("v1").unwrap(),
            manifest_sha256: digest(b"manifest"),
            agentd_program_sha256: digest(b"agentd"),
            matrixd_program_sha256: None,
            admission_frontier_sha256: digest(b"permission"),
        };
        let decision = authority
            .recovery
            .sign_abandon_unknown(
                &intent, &source, /*release_state_generation*/ 3,
                /*lifecycle_generation*/ 6, /*authority_epoch*/ 8,
                /*issued_at_unix_seconds*/ 120, /*expires_at_unix_seconds*/ 400,
            )
            .unwrap();
        let intent = intent.abandon_unknown(&decision).unwrap();
        let predecessor = UnknownRecoveryPredecessorV1 {
            schema_version: 1,
            anchor_generation: 3,
            anchor_sha256: Sha256Digest::for_bytes(b"external-predecessor-fixture"),
        };
        Self {
            authority,
            intent,
            source,
            predecessor,
        }
    }

    fn confirmation(&self, issued: u64) -> SignedIntentPublicationConfirmation {
        self.confirmation_with_policy(&self.authority.policy, issued)
    }

    fn confirmation_with_policy(
        &self,
        policy: &[u8],
        issued: u64,
    ) -> SignedIntentPublicationConfirmation {
        let signer = H7PqProductionRecoverySigner::new(policy, key(/*seed*/ 103)).unwrap();
        let decision = signer
            .sign_confirm_unknown_publication(
                &self.intent,
                &self.source,
                &self.predecessor,
                crate::absent_release_transaction_digest(),
                /*release_state_generation*/ 3,
                /*lifecycle_generation*/ 6,
                /*authority_epoch*/ 9,
                issued,
                /*expires_at_unix_seconds*/ 500,
            )
            .unwrap();
        SignedIntentPublicationConfirmation::new(&self.intent, policy, decision).unwrap()
    }
}

#[test]
fn exact_confirmation_updates_retain_predecessor_and_do_not_rewrite_unknown_history() {
    let fixture = Fixture::new();
    let original_intent = serde_json::to_vec(&fixture.intent).unwrap();
    let first = fixture.confirmation(/*issued*/ 200);
    let second = fixture.confirmation(/*issued*/ 201);
    assert_ne!(first.digest().unwrap(), second.digest().unwrap());
    let root = tempfile::tempdir().unwrap();
    write_current(root.path(), None, Some(&first)).unwrap();
    assert_eq!(read_current(root.path()).unwrap(), Some(first.clone()));
    let raw = std::fs::read(root.path().join(CURRENT_FILE)).unwrap();
    assert!(write_current(root.path(), None, Some(&second)).is_err());
    assert_eq!(std::fs::read(root.path().join(CURRENT_FILE)).unwrap(), raw);
    write_predecessor(root.path(), None, Some(&first)).unwrap();
    write_current(root.path(), Some(&first), Some(&second)).unwrap();
    assert_eq!(read_current(root.path()).unwrap(), Some(second.clone()));
    assert_eq!(read_predecessor(root.path()).unwrap(), Some(first.clone()));
    write_current(root.path(), Some(&second), None).unwrap();
    assert_eq!(read_current(root.path()).unwrap(), None);
    assert_eq!(read_predecessor(root.path()).unwrap(), Some(first.clone()));
    write_predecessor(root.path(), Some(&first), None).unwrap();
    assert_eq!(read_predecessor(root.path()).unwrap(), None);
    assert_eq!(
        serde_json::to_vec(&fixture.intent).unwrap(),
        original_intent
    );
}

#[test]
fn retained_confirmation_verifies_original_pq_bytes_without_reviving_live_authority() {
    let fixture = Fixture::new();
    let material = fixture.confirmation(/*issued*/ 200);
    material.validate_for(&fixture.intent).unwrap();
    let decision = &material.decision;
    assert!(
        fixture
            .authority
            .verifier
            .verify_recovery(
                decision,
                &AgentId::parse(fixture.intent.agent_id.clone()).unwrap(),
                &fixture.intent.grant_sha256,
                &fixture.intent.intent_sha256,
                &decision.release_transaction_sha256,
                "v1",
                &decision.observed_manifest_sha256,
                &decision.observed_agentd_sha256,
                decision.observed_matrixd_sha256.as_ref(),
                /*expected_lifecycle_generation*/ 6,
                /*expected_authority_epoch*/ 9,
                /*now_unix_seconds*/ 500
            )
            .is_err()
    );
    // Historical evidence remains verifiable after that live refusal.
    material.validate_for(&fixture.intent).unwrap();
    let mut wrong_policy = material.clone();
    wrong_policy.policy_json.push(' ');
    assert!(wrong_policy.validate_for(&fixture.intent).is_err());
    let mut forged = material.clone();
    forged.decision.release_transaction_sha256 = Sha256Digest::for_bytes(b"forged transaction");
    forged.decision.decision_sha256 = forged.decision.payload_digest();
    assert!(forged.validate_for(&fixture.intent).is_err());
    let mut wrong_intent = fixture.intent.clone();
    wrong_intent.authority_epoch += 1;
    wrong_intent.intent_sha256 = wrong_intent.compute_digest().unwrap();
    assert!(material.validate_for(&wrong_intent).is_err());
    let mut legacy = material;
    legacy.decision.pq_authority = None;
    assert!(legacy.validate_for(&fixture.intent).is_err());
}

#[test]
fn canonical_material_and_policy_bounds_are_checked_before_replacement() {
    let fixture = Fixture::new();
    let mut policy = fixture.authority.policy.clone();
    policy.resize(MAX_POLICY_BYTES, b' ');
    let material = fixture.confirmation_with_policy(&policy, /*issued*/ 200);
    let root = tempfile::tempdir().unwrap();
    write_current(root.path(), None, Some(&material)).unwrap();
    let original = std::fs::read(root.path().join(CURRENT_FILE)).unwrap();
    let mut oversized_policy = material.clone();
    oversized_policy.policy_json.push(' ');
    assert!(write_current(root.path(), Some(&material), Some(&oversized_policy)).is_err());
    assert_eq!(
        std::fs::read(root.path().join(CURRENT_FILE)).unwrap(),
        original
    );

    let mut noncanonical = original.clone();
    noncanonical.push(b'\n');
    std::fs::write(root.path().join(CURRENT_FILE), &noncanonical).unwrap();
    assert!(read_current(root.path()).is_err());
    assert!(write_current(root.path(), None, Some(&material)).is_err());
    assert_eq!(
        std::fs::read(root.path().join(CURRENT_FILE)).unwrap(),
        noncanonical
    );
    std::fs::write(
        root.path().join(CURRENT_FILE),
        vec![b' '; MAX_CONFIRMATION_BYTES as usize + 1],
    )
    .unwrap();
    assert!(read_current(root.path()).is_err());
    std::fs::write(root.path().join(CURRENT_FILE), &original).unwrap();
    assert_eq!(read_current(root.path()).unwrap(), Some(material));
}

#[test]
fn pq_confirmation_retains_the_real_legacy_origin_of_an_explicit_pq_unknown_disposition() {
    let fixture = Fixture::new();
    let legacy = SignedSupervisorIntent::new(
        Sha256Digest::for_bytes(b"legacy unresolved grant"),
        fixture.intent.agent_id.clone(),
        H7H89ProductionTransition::Upgrade,
        "v1",
        "v2",
        3,
        5,
        7,
        SignedIntentStatus::RecoveryRequired,
    )
    .unwrap();
    let disposition = fixture
        .authority
        .recovery
        .sign_abandon_unknown(&legacy, &fixture.source, 3, 6, 8, 120, 400)
        .unwrap();
    let abandoned = legacy.abandon_unknown(&disposition).unwrap();
    assert!(abandoned.pq_authority.is_none());
    assert_eq!(
        abandoned
            .unknown_effects
            .last()
            .unwrap()
            .decision
            .schema_version,
        3
    );
    let original = serde_json::to_vec(&abandoned).unwrap();
    let decision = fixture
        .authority
        .recovery
        .sign_confirm_unknown_publication(
            &abandoned,
            &fixture.source,
            &fixture.predecessor,
            crate::absent_release_transaction_digest(),
            3,
            6,
            9,
            200,
            500,
        )
        .unwrap();
    let confirmation =
        SignedIntentPublicationConfirmation::new(&abandoned, &fixture.authority.policy, decision)
            .unwrap();
    confirmation.validate_for(&abandoned).unwrap();
    assert_eq!(serde_json::to_vec(&abandoned).unwrap(), original);
    let root = tempfile::tempdir().unwrap();
    write_current(root.path(), None, Some(&confirmation)).unwrap();
    assert_eq!(read_current(root.path()).unwrap(), Some(confirmation));
    assert!(
        SignedIntentPublicationConfirmation::new(
            &legacy,
            &fixture.authority.policy,
            fixture.confirmation(200).decision
        )
        .is_err()
    );
}

fn completion_fixture(
    fixture: &Fixture,
    transition: H7H89ProductionTransition,
    status: SignedIntentStatus,
) -> (SignedSupervisorIntent, SignedIntentPublicationConfirmation) {
    use codex_hepta_memory::H7PqArtifactSigner;
    use codex_hepta_memory::H7QualificationRuntime;
    use codex_hepta_memory::H7SignedArtifactTransition;
    use codex_hepta_memory::H7TrajectoryEvent;
    let envelope = if transition == H7H89ProductionTransition::Rollback {
        let mut runtime = H7QualificationRuntime::new();
        runtime
            .append_trajectory_event(
                H7TrajectoryEvent::new(
                    "confirmation",
                    1,
                    "reload",
                    100,
                    true,
                    1,
                    1,
                    1,
                    Sha256Digest::for_bytes(b"completion-fixture"),
                )
                .unwrap(),
            )
            .unwrap();
        runtime.evaluate_trajectory("confirmation").unwrap();
        let artifact = runtime
            .propose_artifact("rollback-fixture", "confirmation", 1)
            .unwrap();
        H7PqArtifactSigner::new("artifact-role", 7, key(102))
            .unwrap()
            .sign(
                &artifact,
                None,
                H7SignedArtifactTransition::Rollback,
                2,
                Some(Sha256Digest::for_bytes(b"prior-artifact")),
                100,
                500,
            )
            .unwrap()
    } else {
        fixture.authority.envelope.clone()
    };
    let agent = AgentId::parse(fixture.intent.agent_id.clone()).unwrap();
    let (source, target) = if transition == H7H89ProductionTransition::Rollback {
        ("v3", "v1")
    } else {
        ("v1", "v3")
    };
    let grant = fixture
        .authority
        .grant
        .sign(
            &agent, source, target, transition, &envelope, /*expected_control_revision*/ 4,
            /*expected_lifecycle_generation*/ 7, /*authority_epoch*/ 8, 100, 400,
        )
        .unwrap();
    let intent = SignedSupervisorIntent::new(
        grant.grant_sha256.clone(),
        agent.to_string(),
        transition,
        source,
        target,
        4,
        7,
        8,
        SignedIntentStatus::Queued,
    )
    .unwrap()
    .bind_authority(&grant, &envelope, &fixture.authority.verifier)
    .unwrap()
    .inherit_unknown_effects(Some(&fixture.intent))
    .unwrap()
    .with_status(status)
    .unwrap();
    let release = match (transition, status) {
        (H7H89ProductionTransition::Upgrade, SignedIntentStatus::RolledBack) => source,
        _ => target,
    };
    let observed = ReleaseBinding {
        release_id: ReleaseId::parse(release).unwrap(),
        ..fixture.source.clone()
    };
    let observation = CompletionPublicationObservationV1 {
        schema_version: 1,
        predecessor: fixture.predecessor.clone(),
        pending_publication_sha256: Sha256Digest::for_bytes(b"exact pending publication"),
        release_state_sha256: Sha256Digest::for_bytes(b"exact observed release CAS"),
        release_state_generation: 4,
        admission_frontier_sha256: Sha256Digest::parse(observed.admission_frontier_sha256.clone())
            .unwrap(),
    };
    let decision = fixture
        .authority
        .recovery
        .sign_confirm_completion_publication(
            &intent,
            &observed,
            &observation,
            Sha256Digest::for_bytes(b"exact completed transaction"),
            /*lifecycle_generation*/ 8,
            /*authority_epoch*/ 9,
            200,
            500,
        )
        .unwrap();
    let material =
        SignedIntentPublicationConfirmation::new(&intent, &fixture.authority.policy, decision)
            .unwrap();
    (intent, material)
}

#[test]
fn completion_confirmation_binds_each_signed_observation_and_preserves_the_original_history() {
    let fixture = Fixture::new();
    for (transition, status, outcome) in [
        (
            H7H89ProductionTransition::Upgrade,
            SignedIntentStatus::Committed,
            ProductionRecoveryOutcome::ConfirmCommittedPublication,
        ),
        (
            H7H89ProductionTransition::Upgrade,
            SignedIntentStatus::RolledBack,
            ProductionRecoveryOutcome::ConfirmRolledBackPublication,
        ),
        (
            H7H89ProductionTransition::Rollback,
            SignedIntentStatus::RolledBack,
            ProductionRecoveryOutcome::ConfirmRolledBackPublication,
        ),
    ] {
        let (intent, material) = completion_fixture(&fixture, transition, status);
        let before = serde_json::to_vec(&intent).unwrap();
        assert_eq!(material.decision.outcome, outcome);
        assert!(material.decision.unknown_observation.is_none());
        assert_eq!(intent.unknown_effects, fixture.intent.unknown_effects);
        material.validate_for(&intent).unwrap();
        let root = tempfile::tempdir().unwrap();
        write_current(root.path(), None, Some(&material)).unwrap();
        assert_eq!(read_current(root.path()).unwrap(), Some(material.clone()));
        for field in [
            "pending_publication_sha256",
            "release_state_sha256",
            "release_state_generation",
            "admission_frontier_sha256",
            "predecessor",
        ] {
            let mut value = serde_json::to_value(&material).unwrap();
            let observation = &mut value["decision"]["completion_observation"];
            if field == "release_state_generation" {
                observation[field] = 5.into();
            } else if field == "predecessor" {
                observation[field]["anchor_generation"] = 4.into();
            } else {
                observation[field] =
                    serde_json::to_value(Sha256Digest::for_bytes(b"substitution")).unwrap();
            }
            let mut changed: SignedIntentPublicationConfirmation =
                serde_json::from_value(value).unwrap();
            changed.decision.decision_sha256 = changed.decision.payload_digest();
            assert!(changed.validate_for(&intent).is_err(), "{field}");
        }
        let mut mixed = material.clone();
        mixed.decision.unknown_observation = fixture.confirmation(200).decision.unknown_observation;
        mixed.decision.decision_sha256 = mixed.decision.payload_digest();
        assert!(mixed.validate_for(&intent).is_err());
        let mut wrong_intent = intent.clone();
        wrong_intent.status = SignedIntentStatus::RecoveryRequired;
        wrong_intent.intent_sha256 = wrong_intent.compute_digest().unwrap();
        assert!(material.validate_for(&wrong_intent).is_err());
        assert!(material.validate_for(&fixture.intent).is_err());
        let decision = &material.decision;
        assert!(
            fixture
                .authority
                .verifier
                .verify_recovery(
                    decision,
                    &AgentId::parse(intent.agent_id.clone()).unwrap(),
                    &intent.grant_sha256,
                    &intent.intent_sha256,
                    &decision.release_transaction_sha256,
                    &decision.observed_release,
                    &decision.observed_manifest_sha256,
                    &decision.observed_agentd_sha256,
                    decision.observed_matrixd_sha256.as_ref(),
                    8,
                    9,
                    /*now_unix_seconds*/ 500
                )
                .is_err()
        );
        material.validate_for(&intent).unwrap();
        assert_eq!(serde_json::to_vec(&intent).unwrap(), before);
    }
}
