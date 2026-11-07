use super::*;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use codex_hepta_memory::H7PqArtifactSigner;
use codex_hepta_memory::H7QualificationRuntime;
use codex_hepta_memory::H7SignedArtifactTransition;
use codex_hepta_memory::H7TrajectoryEvent;
use pretty_assertions::assert_eq;

pub(crate) struct AuthorityFixture {
    pub(crate) policy: Vec<u8>,
    pub(crate) verifier: H7H89ProductionGrantVerifier,
    pub(crate) grant: H7PqProductionGrantSigner,
    pub(crate) recovery: H7PqProductionRecoverySigner,
    pub(crate) envelope: H7SignedArtifactEnvelope,
}

pub(crate) fn key(seed: u8) -> PqNativeSigningKey {
    let seed = zeroize::Zeroizing::new([seed; 32]);
    let spki = PqNativeSigningKey::public_spki_from_seed(&seed);
    let pin = ml_dsa_65_key_id_from_spki(&spki).unwrap();
    PqNativeSigningKey::from_owned_seed(seed, pin).unwrap()
}

pub(crate) fn fixture_at(issued: u64, expires: u64) -> AuthorityFixture {
    let role = |name: &str, seed| {
        let key = key(seed);
        ProductionAuthorityRoleV1 {
            signer_id: name.to_string(),
            signer_epoch: 7,
            public_key_id: key.public_key_id(),
            public_spki_base64: STANDARD.encode(key.public_spki()),
        }
    };
    let policy = serde_json::to_vec(&ProductionAuthorityPolicyV1 {
        schema_version: 1,
        algorithm: "ml_dsa65_v2".to_string(),
        grant: role("grant-role", 101),
        artifact: role("artifact-role", 102),
        recovery: role("recovery-role", 103),
    })
    .unwrap();
    let mut runtime = H7QualificationRuntime::new();
    let event = H7TrajectoryEvent::new(
        "h7-pq-production",
        /*event_seq*/ 1,
        "reload",
        /*reward_bps*/ 100,
        /*safety_ok*/ true,
        /*authority_epoch*/ 1,
        /*owner_epoch*/ 1,
        /*generation*/ 1,
        Sha256Digest::for_bytes(b"authority-fixture"),
    )
    .unwrap();
    runtime.append_trajectory_event(event).unwrap();
    runtime.evaluate_trajectory("h7-pq-production").unwrap();
    let artifact = runtime
        .propose_artifact(
            "h7-pq-product-v1",
            "h7-pq-production",
            /*generation*/ 1,
        )
        .unwrap();
    let signer =
        H7PqArtifactSigner::new("artifact-role", /*signer_epoch*/ 7, key(/*seed*/ 102)).unwrap();
    let envelope = signer
        .sign(
            &artifact,
            /*ope*/ None,
            H7SignedArtifactTransition::Reload,
            /*expected_runtime_generation*/ 0,
            /*predecessor_artifact_sha256*/ None,
            issued,
            expires,
        )
        .unwrap();
    AuthorityFixture {
        verifier: H7H89ProductionGrantVerifier::from_pq_policy_bytes(&policy).unwrap(),
        grant: H7PqProductionGrantSigner::new(&policy, key(/*seed*/ 101)).unwrap(),
        recovery: H7PqProductionRecoverySigner::new(&policy, key(/*seed*/ 103)).unwrap(),
        policy,
        envelope,
    }
}

fn signed(fixture: &AuthorityFixture) -> H7H89ProductionGrant {
    fixture
        .grant
        .sign(
            &AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap(),
            "v1",
            "v2",
            H7H89ProductionTransition::Upgrade,
            &fixture.envelope,
            /*expected_control_revision*/ 3,
            /*expected_lifecycle_generation*/ 5,
            /*authority_epoch*/ 7,
            /*issued_at_unix_seconds*/ 100,
            /*expires_at_unix_seconds*/ 400,
        )
        .unwrap()
}

#[test]
fn policy_requires_three_explicit_distinct_canonical_pq_roles() {
    let fixture = fixture_at(/*issued*/ 100, /*expires*/ 500);
    let policy: ProductionAuthorityPolicyV1 = serde_json::from_slice(&fixture.policy).unwrap();
    assert_eq!(
        fixture.verifier.policy_sha256(),
        Some(&Sha256Digest::for_bytes(&fixture.policy))
    );
    let mut duplicate = policy.clone();
    duplicate.recovery = duplicate.grant.clone();
    assert!(
        H7H89ProductionGrantVerifier::from_pq_policy_bytes(
            &serde_json::to_vec(&duplicate).unwrap()
        )
        .is_err()
    );
    let mut wrong = policy.clone();
    wrong.grant.public_key_id[0] ^= 1;
    assert!(
        H7H89ProductionGrantVerifier::from_pq_policy_bytes(&serde_json::to_vec(&wrong).unwrap())
            .is_err()
    );
    let mut classical = policy.clone();
    classical.algorithm = "ed25519_v1".to_string();
    assert!(
        H7H89ProductionGrantVerifier::from_pq_policy_bytes(
            &serde_json::to_vec(&classical).unwrap()
        )
        .is_err()
    );
    let mut absent = serde_json::to_value(&policy).unwrap();
    absent.as_object_mut().unwrap().remove("recovery");
    assert!(
        H7H89ProductionGrantVerifier::from_pq_policy_bytes(&serde_json::to_vec(&absent).unwrap())
            .is_err()
    );
    assert!(H7PqProductionRecoverySigner::new(&fixture.policy, key(/*seed*/ 101)).is_err());
    assert!(H7PqProductionGrantSigner::new(&fixture.policy, key(/*seed*/ 103)).is_err());
    let mut whitespace = fixture.policy.clone();
    whitespace.push(b' ');
    let other = H7H89ProductionGrantVerifier::from_pq_policy_bytes(&whitespace).unwrap();
    assert_ne!(fixture.verifier.policy_sha256(), other.policy_sha256());
}

#[test]
fn pq_grant_binds_full_message_and_refuses_legacy_or_recomputed_digest() {
    let fixture = fixture_at(/*issued*/ 100, /*expires*/ 500);
    let grant = signed(&fixture);
    fixture
        .verifier
        .verify(
            &grant,
            &fixture.envelope,
            &AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap(),
            "v1",
            "v2",
            /*expected_control_revision*/ 3,
            /*expected_lifecycle_generation*/ 5,
            /*expected_authority_epoch*/ 7,
            /*now_unix_seconds*/ 200,
        )
        .unwrap();
    let original = serde_json::to_value(&grant).unwrap();
    for (field, value) in [
        ("source_release", serde_json::json!("v0")),
        ("target_release", serde_json::json!("v3")),
        ("agent_id", serde_json::json!("other-agent")),
        ("expected_control_revision", serde_json::json!(4)),
        ("expected_lifecycle_generation", serde_json::json!(6)),
        ("authority_epoch", serde_json::json!(8)),
        ("expires_at_unix_seconds", serde_json::json!(450)),
        ("production_authority", serde_json::json!(false)),
    ] {
        let mut wire = original.clone();
        wire[field] = value;
        let mut changed: H7H89ProductionGrant = serde_json::from_value(wire).unwrap();
        changed.grant_sha256 = changed.payload_digest();
        assert!(
            fixture.verifier.keys.verify_grant(&changed).is_err(),
            "{field}"
        );
    }
    let legacy =
        H7H89ProductionGrantSigner::from_seed("grant-role", /*signer_epoch*/ 7, [101; 32]).unwrap();
    let classical = legacy
        .sign(
            &AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap(),
            "v1",
            "v2",
            H7H89ProductionTransition::Upgrade,
            &fixture.envelope,
            /*expected_control_revision*/ 3,
            /*expected_lifecycle_generation*/ 5,
            /*authority_epoch*/ 7,
            /*issued_at_unix_seconds*/ 100,
            /*expires_at_unix_seconds*/ 400,
        )
        .unwrap();
    assert!(
        serde_json::to_value(&classical)
            .unwrap()
            .get("pq_authority")
            .is_none()
    );
    assert!(fixture.verifier.keys.verify_grant(&classical).is_err());
    let mut downgraded = grant;
    downgraded.pq_authority = None;
    assert!(downgraded.validate_shape(&fixture.envelope).is_err());
}

#[test]
fn pq_recovery_uses_its_own_current_role_and_preserves_observed_bindings() {
    let fixture = fixture_at(/*issued*/ 100, /*expires*/ 500);
    let grant = signed(&fixture);
    let intent = Sha256Digest::for_bytes(b"intent");
    let transaction = Sha256Digest::for_bytes(b"transaction");
    let manifest = Sha256Digest::for_bytes(b"manifest");
    let program = Sha256Digest::for_bytes(b"program");
    let mut decision = fixture
        .recovery
        .sign_recovery(
            &AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap(),
            grant.grant_sha256.clone(),
            intent.clone(),
            transaction.clone(),
            "v2",
            manifest.clone(),
            program.clone(),
            /*observed_matrixd_sha256*/ None,
            ProductionRecoveryOutcome::Committed,
            /*expected_lifecycle_generation*/ 5,
            /*authority_epoch*/ 7,
            /*issued_at_unix_seconds*/ 100,
            /*expires_at_unix_seconds*/ 400,
        )
        .unwrap();
    fixture
        .verifier
        .verify_recovery(
            &decision,
            &AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap(),
            &grant.grant_sha256,
            &intent,
            &transaction,
            "v2",
            &manifest,
            &program,
            /*expected_matrixd_sha256*/ None,
            /*expected_lifecycle_generation*/ 5,
            /*expected_authority_epoch*/ 7,
            /*now_unix_seconds*/ 200,
        )
        .unwrap();
    decision.signature_base64 = STANDARD.encode(
        key(/*seed*/ 101)
            .sign_exact_message(&decision.signing_bytes())
            .unwrap(),
    );
    assert!(fixture.verifier.keys.verify_recovery(&decision).is_err());
    let mut unknown = decision;
    unknown.outcome = ProductionRecoveryOutcome::AbandonUnknown;
    unknown.decision_sha256 = unknown.payload_digest();
    assert!(unknown.validate_shape().is_err());
}
