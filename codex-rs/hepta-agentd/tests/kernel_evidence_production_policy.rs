use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_agentd::EvidenceProductionAdmissionFiles;
use codex_hepta_agentd::EvidenceRecoveryFrontierV2;
use codex_hepta_agentd::EvidenceRuntimeMode;
use codex_hepta_agentd::EvidenceRuntimePolicy;
use codex_hepta_agentd::configure_evidence_runtime_policy;
use codex_hepta_agentd::evidence_ledger_root;
use codex_hepta_agentd::evidence_recovery_frontier_v2_signing_bytes;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_evidence::EVIDENCE_DATABASE_LINEAGE;
use codex_hepta_evidence::EvidenceRecoverySnapshotV1;

fn snapshot() -> EvidenceRecoverySnapshotV1 {
    EvidenceRecoverySnapshotV1 {
        schema_version: 1,
        database_lineage: EVIDENCE_DATABASE_LINEAGE.to_string(),
        migration_set_sha256: Sha256Digest::for_bytes(b"migration-set"),
        qualification_max_seq: 7,
        qualification_frontier_sha256: Sha256Digest::for_bytes(b"qualification"),
        authbus_replay_frontier_sha256: Sha256Digest::for_bytes(b"replay"),
    }
}

fn current_time_millis() -> u64 {
    u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("test clock must be after Unix epoch")
            .as_millis(),
    )
    .expect("test clock must fit u64")
}

fn frontier() -> EvidenceRecoveryFrontierV2 {
    let snapshot = snapshot();
    EvidenceRecoveryFrontierV2 {
        schema_version: 2,
        store_id: "store:kernel-evidence-production".to_string(),
        frontier_generation: 9,
        ledger_root_sha256: evidence_ledger_root(
            "store:kernel-evidence-production",
            &snapshot,
        ),
        snapshot,
        evidence_trust_registry_sha256: Sha256Digest::for_bytes(b"evidence-trust"),
        recovery_signer_trust_sha256: Sha256Digest::for_bytes(b"signer-trust"),
        build_identity_sha256: Sha256Digest::for_bytes(b"build"),
        qualification_status_sha256: Sha256Digest::for_bytes(b"qualification-status"),
        backend_identity_sha256: Sha256Digest::for_bytes(b"backend"),
        source_commit: "a".repeat(40),
        source_tree: "b".repeat(40),
        created_at_unix_ms: current_time_millis(),
        signer_principal_id: "issuer:evidence-frontier".to_string(),
        signer_key_epoch: 3,
        signature_hex: "00".repeat(64),
    }
}

#[test]
fn production_frontier_signing_bytes_bind_every_security_digest() {
    let original = frontier();
    let original_bytes =
        evidence_recovery_frontier_v2_signing_bytes(&original).expect("signing bytes");

    let mutations: Vec<Box<dyn Fn(&mut EvidenceRecoveryFrontierV2)>> = vec![
        Box::new(|frontier| {
            frontier.ledger_root_sha256 = Sha256Digest::for_bytes(b"other-ledger")
        }),
        Box::new(|frontier| {
            frontier.evidence_trust_registry_sha256 = Sha256Digest::for_bytes(b"other-trust")
        }),
        Box::new(|frontier| {
            frontier.recovery_signer_trust_sha256 = Sha256Digest::for_bytes(b"other-signers")
        }),
        Box::new(|frontier| {
            frontier.build_identity_sha256 = Sha256Digest::for_bytes(b"other-build")
        }),
        Box::new(|frontier| {
            frontier.qualification_status_sha256 = Sha256Digest::for_bytes(b"other-status")
        }),
        Box::new(|frontier| {
            frontier.backend_identity_sha256 = Sha256Digest::for_bytes(b"other-backend")
        }),
        Box::new(|frontier| frontier.frontier_generation += 1),
        Box::new(|frontier| frontier.source_tree = "c".repeat(40)),
    ];

    for mutate in mutations {
        let mut changed = original.clone();
        mutate(&mut changed);
        assert_ne!(
            evidence_recovery_frontier_v2_signing_bytes(&changed).expect("changed signing bytes"),
            original_bytes
        );
    }
}

#[test]
fn ledger_root_binds_store_identity_and_all_snapshot_frontiers() {
    let original = snapshot();
    let root = evidence_ledger_root("store:kernel-evidence-production", &original);
    assert_ne!(
        root,
        evidence_ledger_root("store:other-kernel-evidence", &original)
    );

    let mut changed = original.clone();
    changed.qualification_max_seq += 1;
    assert_ne!(
        root,
        evidence_ledger_root("store:kernel-evidence-production", &changed)
    );
}

#[test]
fn production_policy_rejects_missing_or_relative_external_admission() {
    assert!(
        EvidenceRuntimePolicy {
            mode: EvidenceRuntimeMode::Production,
            production: None,
        }
        .validate()
        .is_err()
    );

    assert!(
        EvidenceRuntimePolicy::production(EvidenceProductionAdmissionFiles {
            backend_identity_file: PathBuf::from("relative-backend.json"),
            build_identity_file: PathBuf::from("/external/build.json"),
            qualification_status_file: PathBuf::from("/external/status.json"),
            backup_publication_file: PathBuf::from("/external/backup.json"),
            local_rollback_domain_id: "rollback:local-evidence".to_string(),
        })
        .is_err()
    );
}

#[test]
fn syntactically_complete_files_cannot_claim_live_production_authority() {
    let home = tempfile::tempdir().expect("absolute test directory");
    let policy = EvidenceRuntimePolicy::production(EvidenceProductionAdmissionFiles {
        backend_identity_file: home.path().join("backend.json"),
        build_identity_file: home.path().join("build.json"),
        qualification_status_file: home.path().join("status.json"),
        backup_publication_file: home.path().join("backup.json"),
        local_rollback_domain_id: "rollback:local-evidence".to_string(),
    })
    .expect("file syntax is valid, but does not confer runtime authority");
    assert!(policy.validate().is_ok());
    let error = policy.validate_startup().expect_err("no live backend is installed");
    assert!(error.to_string().contains("live authenticated frontier backend"));
    assert!(error.to_string().contains("durable append/publication fence"));
}

#[test]
fn explicit_development_remains_available() {
    EvidenceRuntimePolicy::development().validate_startup().expect("development");
}

#[test]
fn rejected_production_policy_cannot_be_replaced_with_development() {
    let home = tempfile::tempdir().expect("absolute test directory");
    let policy = EvidenceRuntimePolicy::production(EvidenceProductionAdmissionFiles {
        backend_identity_file: home.path().join("backend.json"),
        build_identity_file: home.path().join("build.json"),
        qualification_status_file: home.path().join("status.json"),
        backup_publication_file: home.path().join("backup.json"),
        local_rollback_domain_id: "rollback:local-evidence".to_string(),
    })
    .expect("file syntax");
    let error = configure_evidence_runtime_policy(policy)
        .expect_err("missing live backend must reject production");
    assert!(error.to_string().contains("live authenticated frontier backend"));
    let downgrade = configure_evidence_runtime_policy(EvidenceRuntimePolicy::development())
        .expect_err("rejected production request must remain latched");
    assert!(downgrade.to_string().contains("already configured"));
}
