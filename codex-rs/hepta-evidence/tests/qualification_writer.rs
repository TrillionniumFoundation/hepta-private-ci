use std::fs;
use std::path::Path;
use std::process::Command;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_evidence::EvidenceCandidate;
use codex_hepta_evidence::EvidenceCheckpoint;
use codex_hepta_evidence::EvidenceClaimClass;
use codex_hepta_evidence::EvidenceIssuerProof;
use codex_hepta_evidence::EvidenceIssuerRegistration;
use codex_hepta_evidence::EvidenceTrustPolicy;
use codex_hepta_evidence::IndependentDecision;
use codex_hepta_evidence::IndependentDecisionInput;
use codex_hepta_evidence::PreparedIndependentDecision;
use codex_hepta_evidence::QualificationEvidenceEnvelope;
use codex_hepta_evidence::QUALIFICATION_EVIDENCE_SCHEMA_VERSION;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde::Serialize;
use serde::de::DeserializeOwned;
use tempfile::TempDir;

const NOW: u64 = 1_000_000;
const EXPIRES: u64 = 2_000_000;

fn writer() -> String {
    std::env::var("CARGO_BIN_EXE_hepta-evidence-writer")
        .expect("writer binary must be exposed to integration tests")
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn candidate() -> EvidenceCandidate {
    EvidenceCandidate {
        candidate_id: "product-candidate".to_string(),
        source_commit: "a".repeat(40),
        source_tree: "b".repeat(40),
    }
}

fn policy(key: &SigningKey) -> EvidenceTrustPolicy {
    EvidenceTrustPolicy {
        schema_version: 1,
        policy_id: "product-qualification-policy".to_string(),
        revision: 1,
        registrations: vec![EvidenceIssuerRegistration {
            principal_id: "external-reviewer".to_string(),
            verifying_key_hex: hex(&key.verifying_key().to_bytes()),
            roles: vec!["evaluator".to_string(), "independent-review".to_string()],
            not_before_ms: NOW - 100,
            expires_at_ms: EXPIRES,
        }],
        revoked_signing_identity_sha256: Vec::new(),
    }
}

fn envelope(id: &str, payload: &[u8]) -> QualificationEvidenceEnvelope {
    QualificationEvidenceEnvelope {
        schema_version: QUALIFICATION_EVIDENCE_SCHEMA_VERSION,
        receipt_id: id.to_string(),
        candidate: candidate(),
        claim_class: EvidenceClaimClass::ExactSource,
        issuer_role: "evaluator".to_string(),
        payload_sha256: Sha256Digest::for_bytes(payload),
        predecessor_receipt_id: None,
        revokes_receipt_id: None,
        revokes_issuer_key_sha256: None,
        observed_at_ms: NOW,
        expires_at_ms: Some(NOW + 100_000),
        asset_refs: Vec::new(),
    }
}

fn proof(
    key: &SigningKey,
    principal: &str,
    envelope: &QualificationEvidenceEnvelope,
) -> EvidenceIssuerProof {
    let signature = key.sign(&envelope.signing_bytes().expect("signing bytes"));
    EvidenceIssuerProof {
        principal_id: principal.to_string(),
        verifying_key_hex: hex(&key.verifying_key().to_bytes()),
        signature_hex: hex(&signature.to_bytes()),
        signed_at_ms: NOW,
    }
}

fn write_json<T: Serialize>(path: &Path, value: &T) {
    fs::write(path, serde_json::to_vec(value).expect("serialize")).expect("write json");
}

fn read_json<T: DeserializeOwned>(path: &Path) -> T {
    serde_json::from_slice(&fs::read(path).expect("read json")).expect("decode json")
}

fn run(args: &[&str]) -> std::process::Output {
    Command::new(writer())
        .args(args)
        .output()
        .expect("run hepta-evidence-writer")
}

#[test]
fn checkpoint_guarded_writer_executes_end_to_end_and_rejects_stale_generation() {
    let temp = TempDir::new().expect("temp dir");
    let root = temp.path();
    let sqlite_home = root.join("sqlite");
    fs::create_dir(&sqlite_home).expect("create sqlite home");

    let key = SigningKey::from_bytes(&[42; 32]);
    let trust = policy(&key);
    let policy_path = root.join("trust-policy.json");
    write_json(&policy_path, &trust);

    let checkpoint0 = root.join("checkpoint-0.json");
    let bootstrap = run(&[
        "bootstrap-trust-policy",
        sqlite_home.to_str().expect("sqlite path"),
        policy_path.to_str().expect("policy path"),
        checkpoint0.to_str().expect("checkpoint path"),
    ]);
    assert!(
        bootstrap.status.success(),
        "bootstrap stderr: {}",
        String::from_utf8_lossy(&bootstrap.stderr)
    );
    let first_checkpoint: EvidenceCheckpoint = read_json(&checkpoint0);
    assert!(first_checkpoint.trust_policy_sha256.is_some());
    assert_eq!(first_checkpoint.receipt_count, 0);

    let receipt = envelope("product-receipt-1", b"product-payload-1");
    let envelope_path = root.join("envelope-1.json");
    let proof_path = root.join("proof-1.json");
    write_json(&envelope_path, &receipt);
    write_json(&proof_path, &proof(&key, "external-reviewer", &receipt));
    let checkpoint1 = root.join("checkpoint-1.json");
    let terminal1 = root.join("terminal-1.json");
    let admit = run(&[
        "admit",
        sqlite_home.to_str().expect("sqlite path"),
        policy_path.to_str().expect("policy path"),
        envelope_path.to_str().expect("envelope path"),
        proof_path.to_str().expect("proof path"),
        checkpoint0.to_str().expect("checkpoint path"),
        checkpoint1.to_str().expect("next checkpoint path"),
        terminal1.to_str().expect("terminal path"),
    ]);
    assert!(
        admit.status.success(),
        "admit stderr: {}",
        String::from_utf8_lossy(&admit.stderr)
    );
    let second_checkpoint: EvidenceCheckpoint = read_json(&checkpoint1);
    assert_eq!(second_checkpoint.receipt_count, 1);
    assert_eq!(
        second_checkpoint.trust_policy_sha256,
        first_checkpoint.trust_policy_sha256
    );
    let terminal: serde_json::Value = read_json(&terminal1);
    assert_eq!(terminal["receiptId"], "product-receipt-1");
    assert_eq!(terminal["disposition"], "inserted");

    let verify = run(&[
        "verify-checkpoint",
        sqlite_home.to_str().expect("sqlite path"),
        checkpoint1.to_str().expect("checkpoint path"),
    ]);
    assert!(
        verify.status.success(),
        "verify stderr: {}",
        String::from_utf8_lossy(&verify.stderr)
    );

    let input = IndependentDecisionInput {
        decision_id: "independent-decision-1".to_string(),
        candidate: candidate(),
        role: "independent-review".to_string(),
        principal_id: "external-reviewer".to_string(),
        evidence_set_digest: Sha256Digest::for_bytes(b"exact-ci-evidence-set"),
        decision: IndependentDecision::Accept,
        conditions: vec!["exact_candidate_only".to_string()],
        observed_at_ms: NOW,
        expires_at_ms: NOW + 100_000,
        predecessor_receipt_id: None,
    };
    let input_path = root.join("independent-input.json");
    let prepared_path = root.join("independent-prepared.json");
    let signing_path = root.join("independent-signing.bin");
    write_json(&input_path, &input);
    let prepare = run(&[
        "prepare-independent",
        sqlite_home.to_str().expect("sqlite path"),
        policy_path.to_str().expect("policy path"),
        input_path.to_str().expect("input path"),
        checkpoint1.to_str().expect("checkpoint path"),
        prepared_path.to_str().expect("prepared path"),
        signing_path.to_str().expect("signing path"),
    ]);
    assert!(
        prepare.status.success(),
        "prepare stderr: {}",
        String::from_utf8_lossy(&prepare.stderr)
    );
    let prepared: PreparedIndependentDecision = read_json(&prepared_path);
    assert_eq!(
        fs::read(&signing_path).expect("signing bytes"),
        prepared.signing_bytes().expect("expected signing bytes")
    );
    let independent_signature = key.sign(&prepared.signing_bytes().expect("signing bytes"));
    let independent_proof = EvidenceIssuerProof {
        principal_id: "external-reviewer".to_string(),
        verifying_key_hex: hex(&key.verifying_key().to_bytes()),
        signature_hex: hex(&independent_signature.to_bytes()),
        signed_at_ms: NOW,
    };
    let independent_proof_path = root.join("independent-proof.json");
    write_json(&independent_proof_path, &independent_proof);
    let checkpoint2 = root.join("checkpoint-2.json");
    let terminal2 = root.join("terminal-2.json");
    let append_independent = run(&[
        "append-independent",
        sqlite_home.to_str().expect("sqlite path"),
        policy_path.to_str().expect("policy path"),
        prepared_path.to_str().expect("prepared path"),
        independent_proof_path.to_str().expect("proof path"),
        checkpoint1.to_str().expect("checkpoint path"),
        checkpoint2.to_str().expect("next checkpoint path"),
        terminal2.to_str().expect("terminal path"),
    ]);
    assert!(
        append_independent.status.success(),
        "append independent stderr: {}",
        String::from_utf8_lossy(&append_independent.stderr)
    );
    let third_checkpoint: EvidenceCheckpoint = read_json(&checkpoint2);
    assert_eq!(third_checkpoint.receipt_count, 2);
    let independent_terminal: serde_json::Value = read_json(&terminal2);
    assert_eq!(independent_terminal["decisionId"], "independent-decision-1");

    let stale = envelope("product-receipt-stale", b"stale");
    let stale_envelope_path = root.join("stale-envelope.json");
    let stale_proof_path = root.join("stale-proof.json");
    write_json(&stale_envelope_path, &stale);
    write_json(
        &stale_proof_path,
        &proof(&key, "external-reviewer", &stale),
    );
    let stale_output = run(&[
        "admit",
        sqlite_home.to_str().expect("sqlite path"),
        policy_path.to_str().expect("policy path"),
        stale_envelope_path.to_str().expect("envelope path"),
        stale_proof_path.to_str().expect("proof path"),
        checkpoint1.to_str().expect("stale checkpoint path"),
        root.join("stale-checkpoint.json")
            .to_str()
            .expect("stale output"),
        root.join("stale-terminal.json")
            .to_str()
            .expect("stale terminal"),
    ]);
    assert!(!stale_output.status.success());
    assert!(
        String::from_utf8_lossy(&stale_output.stderr)
            .contains("stale or divergent qualification evidence writer checkpoint")
    );
    assert!(!root.join("stale-checkpoint.json").exists());
    assert!(!root.join("stale-terminal.json").exists());
}
