#![cfg(all(unix, feature = "offline-authority-tools"))]

use std::os::unix::fs::PermissionsExt;
use std::process::Command;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_supervisor::H7H89ProductionGrantVerifier;
use codex_hepta_supervisor::ProductionRecoveryDecision;
use codex_hepta_supervisor::ProductionRecoveryOutcome;
use codex_hepta_supervisor::SignRequest;
use codex_hepta_supervisor::SignResponse;
use codex_hepta_supervisor::load_signing_key_from_path;
use codex_hepta_supervisor::sign_request;
use ed25519_dalek::SigningKey;
use serde_json::Value;
use serde_json::json;

const AGENT: &str = "00000000-0000-4000-8000-000000000001";
// Public deterministic fixture material, never a deployment trust anchor.
const TEST_SEED: [u8; 32] = [113; 32];

fn digest(label: &str) -> Sha256Digest {
    Sha256Digest::for_bytes(label.as_bytes())
}

fn request_json() -> Value {
    json!({
        "operation": "production_recovery",
        "signer_id": "external-recovery",
        "signer_epoch": 9,
        "agent_id": AGENT,
        "grant_sha256": digest("grant"),
        "intent_sha256": digest("intent"),
        "release_transaction_sha256": digest("transaction"),
        "observed_release": "release-b",
        "observed_manifest_sha256": digest("manifest"),
        "observed_agentd_sha256": digest("agentd"),
        "observed_matrixd_sha256": digest("matrixd"),
        "outcome": "committed",
        "expected_lifecycle_generation": 12,
        "authority_epoch": 81,
        "issued_at_unix_seconds": 100,
        "expires_at_unix_seconds": 200
    })
}

#[expect(
    clippy::expect_used,
    reason = "Test requests are deliberately valid and must sign before contextual rejection is tested."
)]
fn sign(value: Value) -> ProductionRecoveryDecision {
    let request: SignRequest = serde_json::from_value(value).expect("typed request");
    let response =
        sign_request(&request, &SigningKey::from_bytes(&TEST_SEED)).expect("sign recovery request");
    let SignResponse::ProductionRecovery { decision } = response else {
        panic!("wrong signing response variant");
    };
    decision
}

#[expect(
    clippy::expect_used,
    reason = "Deterministic test key material must create a verifier."
)]
fn verifier(seed: &[u8; 32]) -> H7H89ProductionGrantVerifier {
    H7H89ProductionGrantVerifier::from_bytes(
        "external-recovery",
        9,
        SigningKey::from_bytes(seed).verifying_key().to_bytes(),
    )
    .expect("pinned verifier")
}

#[expect(
    clippy::expect_used,
    reason = "The fixed test AgentId must parse before verification is exercised."
)]
fn verifies(
    verifier: &H7H89ProductionGrantVerifier,
    decision: &ProductionRecoveryDecision,
    now: u64,
) -> bool {
    verifier
        .verify_recovery(
            decision,
            &AgentId::parse(AGENT).expect("agent"),
            &digest("grant"),
            &digest("intent"),
            &digest("transaction"),
            "release-b",
            &digest("manifest"),
            &digest("agentd"),
            Some(&digest("matrixd")),
            12,
            81,
            now,
        )
        .is_ok()
}

#[test]
fn recovery_request_signs_both_explicit_outcomes_and_round_trips() {
    for outcome in ["committed", "rolled_back"] {
        let mut value = request_json();
        value["outcome"] = json!(outcome);
        let decision = sign(value);
        assert!(verifies(&verifier(&TEST_SEED), &decision, 150));
        let response = SignResponse::ProductionRecovery {
            decision: decision.clone(),
        };
        let encoded = serde_json::to_vec(&response).expect("encode");
        let decoded: SignResponse = serde_json::from_slice(&encoded).expect("decode");
        let SignResponse::ProductionRecovery { decision: actual } = decoded else {
            panic!("wrong response variant");
        };
        assert_eq!(actual, decision);
    }
}

#[test]
fn correctly_signed_substitutions_do_not_match_the_observed_recovery_context() {
    let substitutions = [
        ("agent_id", json!("00000000-0000-4000-8000-000000000002")),
        ("grant_sha256", json!(digest("other-grant"))),
        ("intent_sha256", json!(digest("other-intent"))),
        (
            "release_transaction_sha256",
            json!(digest("other-transaction")),
        ),
        ("observed_release", json!("release-c")),
        ("observed_manifest_sha256", json!(digest("other-manifest"))),
        ("observed_agentd_sha256", json!(digest("other-agentd"))),
        ("observed_matrixd_sha256", json!(digest("other-matrixd"))),
        ("observed_matrixd_sha256", Value::Null),
        ("expected_lifecycle_generation", json!(13)),
        ("authority_epoch", json!(82)),
        ("signer_id", json!("other-authority")),
        ("signer_epoch", json!(10)),
    ];
    let verifier = verifier(&TEST_SEED);
    for (field, replacement) in substitutions {
        let mut value = request_json();
        value[field] = replacement;
        // Re-sign each substitution: this must fail contextual binding, not
        // merely a stale payload checksum on otherwise invalid test data.
        let decision = sign(value);
        assert!(!verifies(&verifier, &decision, 150), "accepted {field}");
    }
}

#[test]
fn recovery_verification_rejects_wrong_key_expiry_and_future_issuance() {
    let decision = sign(request_json());
    assert!(!verifies(&verifier(&[114; 32]), &decision, 150));
    let verifier = verifier(&TEST_SEED);
    assert!(!verifies(&verifier, &decision, 99));
    assert!(verifies(&verifier, &decision, 100));
    assert!(verifies(&verifier, &decision, 199));
    assert!(!verifies(&verifier, &decision, 200));
}

#[test]
fn recomputing_the_checksum_cannot_forge_a_different_outcome() {
    let mut decision = sign(request_json());
    decision.outcome = ProductionRecoveryOutcome::RolledBack;
    decision.decision_sha256 = decision.payload_digest();
    assert!(!verifies(&verifier(&TEST_SEED), &decision, 150));
}

#[test]
fn recovery_json_rejects_missing_bindings_unknown_fields_and_operation_confusion() {
    for field in [
        "grant_sha256",
        "intent_sha256",
        "release_transaction_sha256",
        "observed_manifest_sha256",
        "observed_agentd_sha256",
        "expected_lifecycle_generation",
        "authority_epoch",
        "outcome",
    ] {
        let mut value = request_json();
        value.as_object_mut().expect("object").remove(field);
        assert!(
            serde_json::from_value::<SignRequest>(value).is_err(),
            "missing {field}"
        );
    }
    let mut value = request_json();
    value["governance_bypass"] = json!(true);
    assert!(serde_json::from_value::<SignRequest>(value).is_err());
    let mut value = request_json();
    value["operation"] = json!("production_grant");
    assert!(serde_json::from_value::<SignRequest>(value).is_err());
}

#[test]
fn recovery_signing_rejects_invalid_epochs_generations_and_time_windows() {
    for (field, replacement) in [
        ("signer_epoch", json!(0)),
        ("authority_epoch", json!(0)),
        ("expected_lifecycle_generation", json!(0)),
        ("expires_at_unix_seconds", json!(100)),
        ("expires_at_unix_seconds", json!(86_501)),
        ("agent_id", json!("invalid-agent")),
        ("observed_release", json!("../other-release")),
    ] {
        let mut value = request_json();
        value[field] = replacement;
        let request: SignRequest = serde_json::from_value(value).expect("request shape");
        assert!(
            sign_request(&request, &SigningKey::from_bytes(&TEST_SEED)).is_err(),
            "signed invalid {field}"
        );
    }
}

#[test]
fn real_offline_signer_binary_emits_a_verifiable_recovery_decision() {
    let temp = tempfile::tempdir().expect("tempdir");
    let key = temp.path().join("fixture.key");
    let request = temp.path().join("request.json");
    std::fs::write(&key, TEST_SEED).expect("fixture key");
    std::fs::set_permissions(&key, std::fs::Permissions::from_mode(0o600))
        .expect("private key mode");
    std::fs::write(&request, serde_json::to_vec(&request_json()).expect("json"))
        .expect("fixture request");
    let output = Command::new(env!("CARGO_BIN_EXE_hepta-authority-signer"))
        .arg("--sign")
        .arg("--key-file")
        .arg(&key)
        .arg("--request")
        .arg(&request)
        .output()
        .expect("run signer");
    assert!(output.status.success(), "{:?}", output.stderr);
    let response: SignResponse = serde_json::from_slice(&output.stdout).expect("signed response");
    let SignResponse::ProductionRecovery { decision } = response else {
        panic!("wrong response variant");
    };
    assert!(verifies(&verifier(&TEST_SEED), &decision, 150));
    assert_eq!(std::fs::read(&key).expect("unchanged key"), TEST_SEED);
}

#[test]
fn signer_binary_never_signs_without_explicit_acknowledgement() {
    let output = Command::new(env!("CARGO_BIN_EXE_hepta-authority-signer"))
        .output()
        .expect("run signer without acknowledgement");
    assert!(!output.status.success());
    assert!(output.stdout.is_empty());
}

#[test]
fn key_file_boundary_rejects_symlinks_permissions_and_non_regular_inputs() {
    let temp = tempfile::tempdir().expect("tempdir");
    let key = temp.path().join("fixture.key");
    let link = temp.path().join("linked.key");
    std::fs::write(&key, TEST_SEED).expect("fixture key");
    std::fs::set_permissions(&key, std::fs::Permissions::from_mode(0o644)).expect("public mode");
    assert!(load_signing_key_from_path(&key).is_err());
    std::fs::set_permissions(&key, std::fs::Permissions::from_mode(0o600)).expect("private mode");
    std::os::unix::fs::symlink(&key, &link).expect("symlink fixture");
    assert!(load_signing_key_from_path(&link).is_err());
    assert!(load_signing_key_from_path(temp.path()).is_err());
    assert!(load_signing_key_from_path(std::path::Path::new("fixture.key")).is_err());
    std::fs::write(&key, [1_u8; 4097]).expect("oversized fixture");
    assert!(load_signing_key_from_path(&key).is_err());
}
