use super::*;
use crate::signed_authority::*;
use codex_hepta_contracts::AgentId;
use pretty_assertions::assert_eq;

#[test]
fn v1_intent_wire_and_digest_remain_unchanged() {
    let intent = SignedSupervisorIntent::new(
        Sha256Digest::for_bytes(b"grant"),
        "agent",
        H7H89ProductionTransition::Upgrade,
        "v1",
        "v2",
        /*expected_control_revision*/ 0,
        /*expected_lifecycle_generation*/ 1,
        /*authority_epoch*/ 1,
        SignedIntentStatus::Queued,
    )
    .unwrap();
    // Frozen pre-v2 digest, independently calculated from the original v1 domain.
    assert_eq!(
        intent.intent_sha256.as_str(),
        "f297398f80d6b4ed473f206983e6568b03b29cf29c3e7c33389848992879cfb6"
    );
    let json = serde_json::to_string(&intent).unwrap();
    assert!(!json.contains("unknown_effects"));
    assert_eq!(
        serde_json::from_str::<SignedSupervisorIntent>(&json).unwrap(),
        intent
    );
}

#[test]
fn v1_recovery_signature_remains_valid_and_rejects_v2_observation() {
    let signer =
        H7H89ProductionGrantSigner::from_seed("operator", /*signer_epoch*/ 4, [9; 32]).unwrap();
    let agent = AgentId::parse("00000000-0000-4000-8000-000000000001").unwrap();
    let decision = signer
        .sign_recovery(
            &agent,
            Sha256Digest::for_bytes(b"grant"),
            Sha256Digest::for_bytes(b"intent"),
            Sha256Digest::for_bytes(b"txn"),
            "v1",
            Sha256Digest::for_bytes(b"manifest"),
            Sha256Digest::for_bytes(b"agentd"),
            /*observed_matrixd_sha256*/ None,
            ProductionRecoveryOutcome::RolledBack,
            /*expected_lifecycle_generation*/ 1,
            /*authority_epoch*/ 3,
            /*issued_at_unix_seconds*/ 100,
            /*expires_at_unix_seconds*/ 200,
        )
        .unwrap();
    // Golden values are produced independently with the original v1 framing.
    assert_eq!(
        decision.decision_sha256.as_str(),
        "50c87de5fc31876ebcdea3058697143775e446cfc4afcaf7034f854b3cffc522"
    );
    assert_eq!(
        decision.signature_base64,
        "VxwMNLLl3vumifPulouQWzRi8ANL2YULf2uV46+XX+0PGZZbZTInRCTuvPDBDMVa4/H4GuOaBdTxZj27UR59BQ=="
    );
    let json = serde_json::to_string(&decision).unwrap();
    assert!(!json.contains("unknown_observation"));
    let mut decoded: ProductionRecoveryDecision = serde_json::from_str(&json).unwrap();
    assert_eq!(decoded, decision);
    decoded.unknown_observation = Some(UnknownRecoveryObservation {
        release_state_generation: 1,
        admission_frontier_sha256: Sha256Digest::for_bytes(b"frontier"),
    });
    assert!(decoded.validate_shape().is_err());
}

#[test]
fn oversized_intent_is_refused_before_publication_and_bounded_on_read() {
    let dir = tempfile::tempdir().unwrap();
    let first = SignedSupervisorIntent::new(
        Sha256Digest::for_bytes(b"grant"),
        "agent",
        H7H89ProductionTransition::Upgrade,
        "v1",
        "v2",
        /*expected_control_revision*/ 0,
        /*expected_lifecycle_generation*/ 1,
        /*authority_epoch*/ 1,
        SignedIntentStatus::RecoveryRequired,
    )
    .unwrap();
    write_intent(dir.path(), &first).unwrap();
    let mut oversized = first.clone();
    oversized.target_release = "x".repeat(MAX_INTENT_BYTES as usize);
    oversized.intent_sha256 = oversized.compute_digest().unwrap();
    assert!(write_intent(dir.path(), &oversized).is_err());
    assert_eq!(read_intent(dir.path()).unwrap(), Some(first));
    std::fs::write(
        dir.path().join(SIGNED_INTENT_FILE),
        vec![b' '; MAX_INTENT_BYTES as usize + 1],
    )
    .unwrap();
    assert!(read_intent(dir.path()).is_err());
}
