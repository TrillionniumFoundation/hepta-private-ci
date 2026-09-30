use std::fmt::Write as _;

use codex_hepta_contracts::Sha256Digest;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::FRONTIER_REPAIR_AUTHORIZATION_SCHEMA_VERSION;
use super::FRONTIER_REPAIR_AUTHORITY_SCHEMA_VERSION;
use super::FrontierMergeDecision;
use super::FrontierRepairAlgorithmV1;
use super::FrontierRepairAuthorityV1;
use super::FrontierRepairAuthorizationV1;
use super::FrontierRepairReasonV1;
use super::classify_frontier_merge;
use super::frontier_repair_authorization_signing_bytes;
use super::verify_frontier_repair_authorization;
use crate::EVIDENCE_DATABASE_LINEAGE;
use crate::EVIDENCE_RECOVERY_FRONTIER_V2_SCHEMA_VERSION;
use crate::EvidenceRecoveryFrontierSignatureV2;
use crate::EvidenceRecoveryFrontierV2;
use crate::EvidenceRecoverySnapshotV1;
use crate::evidence_recovery_frontier_v2_sha256;
use crate::evidence_recovery_ledger_root_v2;

fn digest(label: &str) -> Sha256Digest {
    Sha256Digest::for_bytes(label.as_bytes())
}

fn frontier(generation: u64, artifact: &str) -> EvidenceRecoveryFrontierV2 {
    let snapshot = EvidenceRecoverySnapshotV1 {
        schema_version: 2,
        database_lineage: EVIDENCE_DATABASE_LINEAGE.to_string(),
        migration_set_sha256: digest("migrations"),
        qualification_max_seq: generation,
        qualification_frontier_sha256: digest(&format!("qualification:{generation}")),
        authbus_replay_frontier_sha256: digest(&format!("replay:{generation}")),
    };
    EvidenceRecoveryFrontierV2 {
        schema_version: EVIDENCE_RECOVERY_FRONTIER_V2_SCHEMA_VERSION,
        store_id: "store:kernel-evidence".to_string(),
        frontier_generation: generation,
        ledger_root_sha256: evidence_recovery_ledger_root_v2(&snapshot),
        snapshot,
        issuer_trust_registry_sha256: digest("issuer-registry"),
        frontier_signer_registry_sha256: digest("signer-registry"),
        backend_identity_sha256: digest("backend"),
        build_artifact_sha256: digest(artifact),
        qualification_receipt_sha256: digest("qualification-receipts"),
        backup_publication_sha256: digest(&format!("backup:{generation}")),
        source_commit: "a".repeat(40),
        source_tree: "b".repeat(40),
        created_at_unix_ms: 1_900_000_000_000 + generation,
        signer_policy_generation: 3,
        signatures: vec![EvidenceRecoveryFrontierSignatureV2 {
            signer_principal_id: "issuer:recovery".to_string(),
            signer_key_epoch: 1,
            signature_hex: "11".repeat(64),
        }],
    }
}

fn automatic_successor(current: &EvidenceRecoveryFrontierV2) -> EvidenceRecoveryFrontierV2 {
    let mut next = current.clone();
    next.frontier_generation += 1;
    next.snapshot.qualification_max_seq += 1;
    next.snapshot.qualification_frontier_sha256 =
        digest(&format!("qualification:{}", next.frontier_generation));
    next.snapshot.authbus_replay_frontier_sha256 =
        digest(&format!("replay:{}", next.frontier_generation));
    next.ledger_root_sha256 = evidence_recovery_ledger_root_v2(&next.snapshot);
    next.backup_publication_sha256 = digest(&format!("backup:{}", next.frontier_generation));
    next.created_at_unix_ms += 1;
    next
}

#[test]
fn exact_duplicate_stale_and_strict_successor_are_distinct() {
    let current = frontier(7, "artifact-a");
    assert_eq!(
        classify_frontier_merge(&current, &current),
        FrontierMergeDecision::ExactDuplicate
    );

    let stale = frontier(6, "artifact-a");
    assert_eq!(
        classify_frontier_merge(&current, &stale),
        FrontierMergeDecision::IncomingStale
    );

    let next = automatic_successor(&current);
    assert_eq!(
        classify_frontier_merge(&current, &next),
        FrontierMergeDecision::IncomingWins
    );
    assert_eq!(
        classify_frontier_merge(&next, &current),
        FrontierMergeDecision::IncomingStale
    );
}

#[test]
fn artifact_a_artifact_b_same_order_is_a_conflict_in_both_directions() {
    let artifact_a = frontier(7, "artifact-a");
    let artifact_b = frontier(7, "artifact-b");
    assert_eq!(
        classify_frontier_merge(&artifact_a, &artifact_b),
        FrontierMergeDecision::ConflictSameOrderDifferentIdentity
    );
    assert_eq!(
        classify_frontier_merge(&artifact_b, &artifact_a),
        FrontierMergeDecision::ConflictSameOrderDifferentIdentity
    );
}

#[test]
fn jumps_and_authority_identity_changes_require_explicit_repair() {
    let current = frontier(7, "artifact-a");

    let mut jumped = automatic_successor(&current);
    jumped.frontier_generation += 1;
    jumped.snapshot.qualification_max_seq += 1;
    jumped.snapshot.qualification_frontier_sha256 = digest("qualification:9");
    jumped.ledger_root_sha256 = evidence_recovery_ledger_root_v2(&jumped.snapshot);
    assert_eq!(
        classify_frontier_merge(&current, &jumped),
        FrontierMergeDecision::RepairRequired
    );

    let mut changed_source = automatic_successor(&current);
    changed_source.source_commit = "c".repeat(40);
    assert_eq!(
        classify_frontier_merge(&current, &changed_source),
        FrontierMergeDecision::RepairRequired
    );

    let mut changed_backend = automatic_successor(&current);
    changed_backend.backend_identity_sha256 = digest("other-backend");
    assert_eq!(
        classify_frontier_merge(&current, &changed_backend),
        FrontierMergeDecision::RepairRequired
    );
}

#[test]
fn signer_rotation_requires_a_strict_policy_generation_advance() {
    let current = frontier(7, "artifact-a");
    let mut rotated = automatic_successor(&current);
    rotated.frontier_signer_registry_sha256 = digest("rotated-signers");
    assert_eq!(
        classify_frontier_merge(&current, &rotated),
        FrontierMergeDecision::RepairRequired
    );
    rotated.signer_policy_generation += 1;
    assert_eq!(
        classify_frontier_merge(&current, &rotated),
        FrontierMergeDecision::IncomingWins
    );
}

#[test]
fn invalid_current_and_incoming_fail_closed() {
    let valid = frontier(7, "artifact-a");
    let mut invalid = valid.clone();
    invalid.frontier_generation = 0;
    assert_eq!(
        classify_frontier_merge(&invalid, &valid),
        FrontierMergeDecision::InvalidCurrent
    );
    assert_eq!(
        classify_frontier_merge(&valid, &invalid),
        FrontierMergeDecision::InvalidIncoming
    );
}

#[test]
fn repeated_and_permuted_automatic_merges_converge_without_extra_winners() {
    let current = frontier(7, "artifact-a");
    let next = automatic_successor(&current);
    for sequence in [
        vec![current.clone(), current.clone(), next.clone(), next.clone()],
        vec![next.clone(), current.clone(), next.clone(), current.clone()],
    ] {
        let mut accepted = sequence[0].clone();
        let mut wins = 0;
        for incoming in sequence.iter().skip(1) {
            match classify_frontier_merge(&accepted, incoming) {
                FrontierMergeDecision::IncomingWins => {
                    accepted = incoming.clone();
                    wins += 1;
                }
                FrontierMergeDecision::ExactDuplicate | FrontierMergeDecision::IncomingStale => {}
                decision => panic!("unexpected merge decision: {decision:?}"),
            }
        }
        assert_eq!(accepted, next);
        assert!(wins <= 1);
    }
}

#[test]
fn exact_signed_repair_authorization_binds_one_transition() {
    let current = frontier(7, "artifact-a");
    let mut target = automatic_successor(&current);
    target.source_commit = "c".repeat(40);
    assert_eq!(
        classify_frontier_merge(&current, &target),
        FrontierMergeDecision::RepairRequired
    );

    let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
    let now = 1_900_000_010_000;
    let authority = FrontierRepairAuthorityV1 {
        schema_version: FRONTIER_REPAIR_AUTHORITY_SCHEMA_VERSION,
        authority_key_id: "key:frontier-repair:primary".to_string(),
        authority_key_epoch: 4,
        trust_root_generation: 9,
        algorithm: FrontierRepairAlgorithmV1::Ed25519,
        public_key_hex: encode_hex(signing_key.verifying_key().as_bytes()),
        not_before_unix_ms: now - 1_000,
        not_after_unix_ms: now + 100_000,
        revoked: false,
    };
    let mut authorization = FrontierRepairAuthorizationV1 {
        schema_version: FRONTIER_REPAIR_AUTHORIZATION_SCHEMA_VERSION,
        store_id: current.store_id.clone(),
        current_frontier_sha256: evidence_recovery_frontier_v2_sha256(&current).unwrap(),
        target_frontier_sha256: evidence_recovery_frontier_v2_sha256(&target).unwrap(),
        current_generation: current.frontier_generation,
        target_generation: target.frontier_generation,
        reason_code: FrontierRepairReasonV1::OperatorDisasterRecovery,
        operator_principal_id: "operator:recovery:primary".to_string(),
        issued_at_unix_ms: now - 100,
        expires_at_unix_ms: now + 10_000,
        nonce_hex: "ab".repeat(32),
        authority_key_id: authority.authority_key_id.clone(),
        authority_key_epoch: authority.authority_key_epoch,
        authority_algorithm: authority.algorithm,
        trust_root_generation: authority.trust_root_generation,
        authority_signature_hex: String::new(),
    };
    let bytes = frontier_repair_authorization_signing_bytes(&authorization).unwrap();
    authorization.authority_signature_hex = encode_hex(&signing_key.sign(&bytes).to_bytes());
    verify_frontier_repair_authorization(&authorization, &authority, &current, &target, now)
        .expect("exact signed transition is authorized");

    let mut tampered = target.clone();
    tampered.source_tree = "d".repeat(40);
    assert!(
        verify_frontier_repair_authorization(&authorization, &authority, &current, &tampered, now)
            .is_err()
    );

    let mut revoked = authority.clone();
    revoked.revoked = true;
    assert!(
        verify_frontier_repair_authorization(&authorization, &revoked, &current, &target, now)
            .is_err()
    );
}

fn encode_hex(bytes: &[u8]) -> String {
    let mut encoded = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        write!(&mut encoded, "{byte:02x}").expect("writing to a string cannot fail");
    }
    encoded
}
