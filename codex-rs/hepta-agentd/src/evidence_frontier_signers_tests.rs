use codex_hepta_contracts::Sha256Digest;
use codex_hepta_evidence::EVIDENCE_DATABASE_LINEAGE;
use codex_hepta_evidence::EVIDENCE_RECOVERY_FRONTIER_V2_SCHEMA_VERSION;
use codex_hepta_evidence::EvidenceRecoveryFrontierSignatureV2;
use codex_hepta_evidence::EvidenceRecoveryFrontierV2;
use codex_hepta_evidence::EvidenceRecoverySnapshotV1;
use codex_hepta_evidence::evidence_recovery_frontier_v2_signing_bytes;
use codex_hepta_evidence::evidence_recovery_ledger_root_v2;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::json;

use super::EvidenceFrontierSignerTrustV2;

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn snapshot() -> EvidenceRecoverySnapshotV1 {
    EvidenceRecoverySnapshotV1 {
        schema_version: 1,
        database_lineage: EVIDENCE_DATABASE_LINEAGE.to_string(),
        migration_set_sha256: Sha256Digest::for_bytes(b"migrations"),
        qualification_max_seq: 9,
        qualification_frontier_sha256: Sha256Digest::for_bytes(b"qualification"),
        authbus_replay_frontier_sha256: Sha256Digest::for_bytes(b"replay"),
    }
}

fn unsigned_frontier(bindings: &[(&str, u64)]) -> EvidenceRecoveryFrontierV2 {
    let snapshot = snapshot();
    EvidenceRecoveryFrontierV2 {
        schema_version: EVIDENCE_RECOVERY_FRONTIER_V2_SCHEMA_VERSION,
        store_id: "store:kernel-evidence".to_string(),
        frontier_generation: 8,
        ledger_root_sha256: evidence_recovery_ledger_root_v2(&snapshot),
        snapshot,
        issuer_trust_registry_sha256: Sha256Digest::for_bytes(b"issuer-trust"),
        frontier_signer_registry_sha256: Sha256Digest::for_bytes(b"signer-trust"),
        backend_identity_sha256: Sha256Digest::for_bytes(b"backend"),
        build_artifact_sha256: Sha256Digest::for_bytes(b"build"),
        qualification_receipt_sha256: Sha256Digest::for_bytes(b"qualification-receipt"),
        backup_publication_sha256: Sha256Digest::for_bytes(b"backup"),
        source_commit: "a".repeat(40),
        source_tree: "b".repeat(40),
        created_at_unix_ms: 1_900_000_000_000,
        signer_policy_generation: 4,
        signatures: bindings
            .iter()
            .map(|(principal, epoch)| EvidenceRecoveryFrontierSignatureV2 {
                signer_principal_id: (*principal).to_string(),
                signer_key_epoch: *epoch,
                signature_hex: "00".repeat(64),
            })
            .collect(),
    }
}

fn signed_frontier(bindings: &[(&str, u64, &SigningKey)]) -> EvidenceRecoveryFrontierV2 {
    let binding_ids = bindings
        .iter()
        .map(|(principal, epoch, _)| (*principal, *epoch))
        .collect::<Vec<_>>();
    let mut frontier = unsigned_frontier(&binding_ids);
    let bytes = evidence_recovery_frontier_v2_signing_bytes(&frontier)
        .expect("frontier signing bytes");
    for (signature, (_, _, key)) in frontier.signatures.iter_mut().zip(bindings) {
        signature.signature_hex = hex(&key.sign(&bytes).to_bytes());
    }
    frontier
}

fn trust(
    threshold: usize,
    signers: &[(&str, u64, &SigningKey, bool)],
) -> EvidenceFrontierSignerTrustV2 {
    let bytes = serde_json::to_vec(&json!({
        "schemaVersion": 2,
        "policyGeneration": 4,
        "threshold": threshold,
        "signers": signers.iter().map(|(principal, epoch, key, revoked)| json!({
            "principalId": principal,
            "keyEpoch": epoch,
            "publicKeyHex": hex(key.verifying_key().as_bytes()),
            "revoked": revoked,
        })).collect::<Vec<_>>(),
    }))
    .expect("serialize signer trust");
    EvidenceFrontierSignerTrustV2::parse(&bytes).expect("parse signer trust")
}

#[test]
fn threshold_requires_distinct_verified_principals() {
    let alpha = SigningKey::from_bytes(&[1; 32]);
    let beta = SigningKey::from_bytes(&[2; 32]);
    let trust = trust(
        2,
        &[
            ("issuer:alpha", 1, &alpha, false),
            ("issuer:beta", 1, &beta, false),
        ],
    );
    let frontier = signed_frontier(&[
        ("issuer:alpha", 1, &alpha),
        ("issuer:beta", 1, &beta),
    ]);
    trust.verify(&frontier).expect("two-principal threshold");
}

#[test]
fn key_rotation_overlap_does_not_double_count_one_principal() {
    let old = SigningKey::from_bytes(&[3; 32]);
    let current = SigningKey::from_bytes(&[4; 32]);
    let trust = trust(
        1,
        &[
            ("issuer:alpha", 1, &old, false),
            ("issuer:alpha", 2, &current, false),
        ],
    );
    let frontier = signed_frontier(&[
        ("issuer:alpha", 1, &old),
        ("issuer:alpha", 2, &current),
    ]);
    trust.verify(&frontier).expect("rotation overlap");

    let bytes = serde_json::to_vec(&json!({
        "schemaVersion": 2,
        "policyGeneration": 4,
        "threshold": 2,
        "signers": [
            {
                "principalId": "issuer:alpha",
                "keyEpoch": 1,
                "publicKeyHex": hex(old.verifying_key().as_bytes()),
                "revoked": false
            },
            {
                "principalId": "issuer:alpha",
                "keyEpoch": 2,
                "publicKeyHex": hex(current.verifying_key().as_bytes()),
                "revoked": false
            }
        ]
    }))
    .expect("serialize invalid threshold policy");
    assert!(EvidenceFrontierSignerTrustV2::parse(&bytes).is_err());
}

#[test]
fn revoked_unknown_and_tampered_signatures_fail_closed() {
    let alpha = SigningKey::from_bytes(&[5; 32]);
    let beta = SigningKey::from_bytes(&[6; 32]);
    let revoked = trust(1, &[("issuer:alpha", 1, &alpha, true), ("issuer:beta", 1, &beta, false)]);
    let alpha_frontier = signed_frontier(&[("issuer:alpha", 1, &alpha)]);
    assert!(revoked.verify(&alpha_frontier).is_err());

    let beta_only = trust(1, &[("issuer:beta", 1, &beta, false)]);
    assert!(beta_only.verify(&alpha_frontier).is_err());

    let alpha_trust = trust(1, &[("issuer:alpha", 1, &alpha, false)]);
    let mut tampered = alpha_frontier;
    tampered.source_tree = "c".repeat(40);
    assert!(alpha_trust.verify(&tampered).is_err());
}
