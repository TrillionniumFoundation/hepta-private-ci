use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::H7ArtifactSigner;
use codex_hepta_memory::H7ArtifactVerifier;
use codex_hepta_memory::H7QualificationRuntime;
use codex_hepta_memory::H7SignedArtifactEnvelope;
use codex_hepta_memory::H7SignedArtifactTransition;
use codex_hepta_supervisor::H7H89ProductionGrantSigner;
use codex_hepta_supervisor::H7H89ProductionGrantVerifier;
use codex_hepta_supervisor::H7H89ProductionTransition;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

#[test]
fn signer_rotation_rejects_previous_epoch_and_accepts_current_epoch() {
    let envelope = h7_envelope();
    let agent = agent();
    let previous =
        H7H89ProductionGrantSigner::from_seed("release-policy", 4, [9; 32]).expect("previous");
    let current =
        H7H89ProductionGrantSigner::from_seed("release-policy", 5, [10; 32]).expect("current");
    let previous_grant = sign(&previous, &agent, &envelope, 3, 100, 200);
    let current_grant = sign(&current, &agent, &envelope, 3, 100, 200);
    let verifier = H7H89ProductionGrantVerifier::new_with_h7_verifier(
        "release-policy",
        5,
        current.verifying_key(),
        h7_verifier(),
    )
    .expect("current verifier");

    assert!(
        verify(&verifier, &previous_grant, &envelope, &agent, 3, 150).is_err(),
        "a verifier pinned to the rotated signer epoch accepted an old grant"
    );
    verify(&verifier, &current_grant, &envelope, &agent, 3, 150)
        .expect("current signer grant");
}

#[test]
fn wrong_signer_and_expired_grant_fail_closed() {
    let envelope = h7_envelope();
    let agent = agent();
    let signer =
        H7H89ProductionGrantSigner::from_seed("release-policy", 7, [11; 32]).expect("signer");
    let grant = sign(&signer, &agent, &envelope, 8, 100, 200);
    let wrong_identity = H7H89ProductionGrantVerifier::new_with_h7_verifier(
        "different-policy",
        7,
        signer.verifying_key(),
        h7_verifier(),
    )
    .expect("wrong identity verifier");
    let correct = H7H89ProductionGrantVerifier::new_with_h7_verifier(
        "release-policy",
        7,
        signer.verifying_key(),
        h7_verifier(),
    )
    .expect("correct verifier");

    assert!(
        verify(&wrong_identity, &grant, &envelope, &agent, 8, 150).is_err(),
        "a grant crossed the pinned release-policy signer identity"
    );
    assert!(
        verify(&correct, &grant, &envelope, &agent, 8, 200).is_err(),
        "an expired grant remained usable at its exclusive expiry boundary"
    );
}

#[test]
fn authority_epoch_rollover_requires_a_fresh_grant() {
    let envelope = h7_envelope();
    let agent = agent();
    let signer =
        H7H89ProductionGrantSigner::from_seed("release-policy", 9, [12; 32]).expect("signer");
    let stale_epoch_grant = sign(&signer, &agent, &envelope, 12, 100, 200);
    let fresh_epoch_grant = sign(&signer, &agent, &envelope, 13, 100, 200);
    let verifier = H7H89ProductionGrantVerifier::new_with_h7_verifier(
        "release-policy",
        9,
        signer.verifying_key(),
        h7_verifier(),
    )
    .expect("verifier");

    assert!(
        verify(
            &verifier,
            &stale_epoch_grant,
            &envelope,
            &agent,
            13,
            150,
        )
        .is_err(),
        "a grant survived daemon authority-epoch rollover"
    );
    verify(
        &verifier,
        &fresh_epoch_grant,
        &envelope,
        &agent,
        13,
        150,
    )
    .expect("fresh epoch grant");
}

fn agent() -> AgentId {
    AgentId::parse(AGENT_ID).expect("fixed AgentId")
}

fn sign(
    signer: &H7H89ProductionGrantSigner,
    agent: &AgentId,
    envelope: &H7SignedArtifactEnvelope,
    authority_epoch: u64,
    issued_at: u64,
    expires_at: u64,
) -> codex_hepta_supervisor::H7H89ProductionGrant {
    signer
        .sign(
            agent,
            "release-v2",
            "release-v3",
            H7H89ProductionTransition::Upgrade,
            envelope,
            8,
            11,
            authority_epoch,
            issued_at,
            expires_at,
        )
        .expect("grant")
}

fn verify(
    verifier: &H7H89ProductionGrantVerifier,
    grant: &codex_hepta_supervisor::H7H89ProductionGrant,
    envelope: &H7SignedArtifactEnvelope,
    agent: &AgentId,
    authority_epoch: u64,
    now: u64,
) -> Result<(), impl std::fmt::Debug> {
    verifier.verify(
        grant,
        envelope,
        agent,
        "release-v2",
        "release-v3",
        8,
        11,
        authority_epoch,
        now,
    )
}

fn h7_envelope() -> H7SignedArtifactEnvelope {
    let mut runtime = H7QualificationRuntime::new();
    let event = codex_hepta_memory::H7TrajectoryEvent::new(
        "production-trajectory",
        1,
        "reload",
        100,
        true,
        1,
        1,
        1,
        Sha256Digest::for_bytes(b"fence"),
    )
    .expect("event");
    runtime.append_trajectory_event(event).expect("append");
    runtime
        .evaluate_trajectory("production-trajectory")
        .expect("evaluate");
    let artifact = runtime
        .propose_artifact("artifact-production", "production-trajectory", 1)
        .expect("artifact");
    H7ArtifactSigner::from_seed("h7-signer", 1, [7; 32])
        .expect("H7 signer")
        .sign(
            &artifact,
            None,
            H7SignedArtifactTransition::Reload,
            0,
            None,
            100,
            200,
        )
        .expect("H7 envelope")
}

fn h7_verifier() -> H7ArtifactVerifier {
    H7ArtifactSigner::from_seed("h7-signer", 1, [7; 32])
        .expect("H7 signer")
        .verifier()
}
