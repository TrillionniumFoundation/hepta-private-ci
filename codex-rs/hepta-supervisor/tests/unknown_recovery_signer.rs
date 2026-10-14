//! Exercise the actual external signer process and its existing verifier.
#![cfg(feature = "production-authority")]
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_supervisor::H7H89ProductionGrantVerifier;
use codex_hepta_supervisor::H7H89ProductionTransition;
use codex_hepta_supervisor::SignResponse;
use codex_hepta_supervisor::SignedIntentStatus;
use codex_hepta_supervisor::SignedSupervisorIntent;
use codex_hepta_supervisor::absent_release_transaction_digest;
use ed25519_dalek::SigningKey;
use std::process::Command;

#[test]
fn explicit_external_signer_emits_bound_unknown_decision_and_refuses_implicit_signing() {
    let temp = tempfile::tempdir().unwrap();
    let agent = AgentId::parse("00000000-0000-4000-8000-000000000001").unwrap();
    let intent = SignedSupervisorIntent::new(
        Sha256Digest::for_bytes(b"prepared grant"),
        agent.to_string(),
        H7H89ProductionTransition::Upgrade,
        "source",
        "target",
        /*expected_control_revision*/ 0,
        /*expected_lifecycle_generation*/ 5,
        /*authority_epoch*/ 3,
        SignedIntentStatus::RecoveryRequired,
    )
    .unwrap();
    let manifest = Sha256Digest::for_bytes(b"manifest");
    let agentd = Sha256Digest::for_bytes(b"agentd");
    let request = serde_json::json!({
        "operation": "abandon_unknown", "signer_id": "operator", "signer_epoch": 4,
        "intent": intent,
        "source": { "release_id": "source", "manifest_sha256": manifest,
            "agentd_program_sha256": agentd, "matrixd_program_sha256": null,
            "admission_frontier_sha256": Sha256Digest::for_bytes(b"frontier") },
        "release_state_generation": 2, "lifecycle_generation": 5, "authority_epoch": 3,
        "issued_at_unix_seconds": 100, "expires_at_unix_seconds": 200,
    });
    let request_path = temp.path().join("request.json");
    std::fs::write(&request_path, serde_json::to_vec(&request).unwrap()).unwrap();
    let key = SigningKey::from_bytes(&[9; 32]);
    let key_path = temp.path().join("external-test-key");
    std::fs::write(&key_path, key.to_bytes()).unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&key_path, std::fs::Permissions::from_mode(/*mode*/ 0o600))
            .unwrap();
    }
    let mut command = Command::new(env!("CARGO_BIN_EXE_hepta-authority-signer"));
    command
        .arg("--key-file")
        .arg(&key_path)
        .arg("--request")
        .arg(&request_path);
    let refused = command.output().unwrap();
    assert!(!refused.status.success());
    assert!(refused.stdout.is_empty());
    let signed = command.arg("--sign").output().unwrap();
    assert!(
        signed.status.success(),
        "{}",
        String::from_utf8_lossy(&signed.stderr)
    );
    let SignResponse::ProductionRecovery { decision } =
        serde_json::from_slice(&signed.stdout).unwrap()
    else {
        panic!("wrong signer response");
    };
    let verifier =
        H7H89ProductionGrantVerifier::new("operator", /*signer_epoch*/ 4, key.verifying_key())
            .unwrap();
    verifier
        .verify_recovery(
            &decision,
            &agent,
            &intent.grant_sha256,
            &intent.intent_sha256,
            &absent_release_transaction_digest(),
            "source",
            &manifest,
            &agentd,
            /*expected_matrixd_sha256*/ None,
            /*expected_lifecycle_generation*/ 5,
            /*expected_authority_epoch*/ 3,
            /*now_unix_seconds*/ 150,
        )
        .unwrap();
    let mut tampered = decision;
    tampered
        .unknown_observation
        .as_mut()
        .unwrap()
        .release_state_generation += 1;
    assert!(
        verifier
            .verify_recovery(
                &tampered,
                &agent,
                &intent.grant_sha256,
                &intent.intent_sha256,
                &absent_release_transaction_digest(),
                "source",
                &manifest,
                &agentd,
                /*expected_matrixd_sha256*/ None,
                /*expected_lifecycle_generation*/ 5,
                /*expected_authority_epoch*/ 3,
                /*now_unix_seconds*/ 150
            )
            .is_err()
    );
}
