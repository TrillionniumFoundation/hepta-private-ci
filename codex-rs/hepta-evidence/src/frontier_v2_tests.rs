use codex_hepta_contracts::Sha256Digest;

use super::EVIDENCE_RECOVERY_FRONTIER_V2_SCHEMA_VERSION;
use super::EvidenceRecoveryFrontierSignatureV2;
use super::EvidenceRecoveryFrontierV2;
use super::evidence_recovery_frontier_v2_sha256;
use super::evidence_recovery_frontier_v2_signing_bytes;
use super::evidence_recovery_ledger_root_v2;
use crate::EVIDENCE_DATABASE_LINEAGE;
use crate::EvidenceRecoverySnapshotV1;

fn snapshot() -> EvidenceRecoverySnapshotV1 {
    EvidenceRecoverySnapshotV1 {
        schema_version: 1,
        database_lineage: EVIDENCE_DATABASE_LINEAGE.to_string(),
        migration_set_sha256: Sha256Digest::for_bytes(b"migrations"),
        qualification_max_seq: 17,
        qualification_frontier_sha256: Sha256Digest::for_bytes(b"qualification"),
        authbus_replay_frontier_sha256: Sha256Digest::for_bytes(b"replay"),
    }
}

fn signature(principal: &str, epoch: u64, byte: u8) -> EvidenceRecoveryFrontierSignatureV2 {
    EvidenceRecoveryFrontierSignatureV2 {
        signer_principal_id: principal.to_string(),
        signer_key_epoch: epoch,
        signature_hex: format!("{byte:02x}").repeat(64),
    }
}

fn frontier() -> EvidenceRecoveryFrontierV2 {
    let snapshot = snapshot();
    EvidenceRecoveryFrontierV2 {
        schema_version: EVIDENCE_RECOVERY_FRONTIER_V2_SCHEMA_VERSION,
        store_id: "store:kernel-evidence".to_string(),
        frontier_generation: 3,
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
        signer_policy_generation: 7,
        signatures: vec![
            signature("issuer:recovery-a", 1, 0x11),
            signature("issuer:recovery-b", 2, 0x22),
        ],
    }
}

#[test]
fn v2_frontier_binds_every_production_identity_into_the_signing_domain() {
    let original = frontier();
    original.validate_structure().expect("valid frontier");
    let original_bytes = evidence_recovery_frontier_v2_signing_bytes(&original)
        .expect("serialize frontier signing bytes");
    let original_digest =
        evidence_recovery_frontier_v2_sha256(&original).expect("hash complete frontier");

    let mutations: [fn(&mut EvidenceRecoveryFrontierV2); 6] = [
        |frontier| {
            frontier.issuer_trust_registry_sha256 = Sha256Digest::for_bytes(b"other-issuer-trust");
        },
        |frontier| {
            frontier.frontier_signer_registry_sha256 =
                Sha256Digest::for_bytes(b"other-signer-trust");
        },
        |frontier| {
            frontier.backend_identity_sha256 = Sha256Digest::for_bytes(b"other-backend");
        },
        |frontier| {
            frontier.build_artifact_sha256 = Sha256Digest::for_bytes(b"other-build");
        },
        |frontier| {
            frontier.qualification_receipt_sha256 =
                Sha256Digest::for_bytes(b"other-qualification-receipt");
        },
        |frontier| {
            frontier.backup_publication_sha256 = Sha256Digest::for_bytes(b"other-backup");
        },
    ];

    for mutate in mutations {
        let mut changed = original.clone();
        mutate(&mut changed);
        assert_ne!(
            evidence_recovery_frontier_v2_signing_bytes(&changed)
                .expect("serialize changed frontier"),
            original_bytes
        );
        assert_ne!(
            evidence_recovery_frontier_v2_sha256(&changed).expect("hash changed frontier"),
            original_digest
        );
    }
}

#[test]
fn ledger_root_binds_migrations_qualification_and_replay_frontiers() {
    let original = snapshot();
    let original_root = evidence_recovery_ledger_root_v2(&original);

    let mut changed = original.clone();
    changed.migration_set_sha256 = Sha256Digest::for_bytes(b"changed-migrations");
    assert_ne!(evidence_recovery_ledger_root_v2(&changed), original_root);

    changed = original.clone();
    changed.qualification_frontier_sha256 = Sha256Digest::for_bytes(b"changed-qualification");
    assert_ne!(evidence_recovery_ledger_root_v2(&changed), original_root);

    changed = original;
    changed.authbus_replay_frontier_sha256 = Sha256Digest::for_bytes(b"changed-replay");
    assert_ne!(evidence_recovery_ledger_root_v2(&changed), original_root);
}

#[test]
fn v2_frontier_rejects_noncanonical_or_duplicate_signers() {
    let mut unordered = frontier();
    unordered.signatures.swap(0, 1);
    assert!(unordered.validate_structure().is_err());

    let mut duplicate = frontier();
    duplicate.signatures[1] = duplicate.signatures[0].clone();
    assert!(duplicate.validate_structure().is_err());

    let mut uppercase = frontier();
    uppercase.signatures[0].signature_hex = "AA".repeat(64);
    assert!(uppercase.validate_structure().is_err());
}

#[test]
fn v2_frontier_rejects_a_ledger_root_or_source_identity_mismatch() {
    let mut wrong_root = frontier();
    wrong_root.ledger_root_sha256 = Sha256Digest::for_bytes(b"wrong-root");
    assert!(wrong_root.validate_structure().is_err());

    let mut wrong_source = frontier();
    wrong_source.source_commit = "not-a-git-id".to_string();
    assert!(wrong_source.validate_structure().is_err());
}

#[test]
fn v2_frontier_deterministic_mutation_corpus_never_silently_preserves_identity() {
    let original = frontier();
    original.validate_structure().expect("valid frontier");
    let encoded = serde_json::to_vec(&original).expect("serialize frontier");
    let original_digest =
        evidence_recovery_frontier_v2_sha256(&original).expect("hash original frontier");
    let mut structurally_valid_mutations = 0_u64;

    for seed in 0_u64..2048 {
        let mut mutated = encoded.clone();
        let index = seed
            .wrapping_mul(1_103_515_245)
            .wrapping_add(12_345) as usize
            % mutated.len();
        mutated[index] ^= u8::try_from(seed % 251 + 1).expect("bounded mutation byte");
        let Ok(candidate) = serde_json::from_slice::<EvidenceRecoveryFrontierV2>(&mutated) else {
            continue;
        };
        if candidate.validate_structure().is_err() {
            continue;
        }
        structurally_valid_mutations += 1;
        assert_ne!(candidate, original);
        assert_ne!(
            evidence_recovery_frontier_v2_sha256(&candidate)
                .expect("hash structurally valid mutation"),
            original_digest
        );
    }

    assert!(
        structurally_valid_mutations >= 32,
        "mutation corpus did not exercise enough structurally valid variants"
    );
}
