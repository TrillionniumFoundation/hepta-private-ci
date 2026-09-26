#![cfg(unix)]

use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::sync::Barrier;

use codex_hepta_contracts::Sha256Digest;
use tempfile::TempDir;

use super::LockedFileEvidenceFrontierBackend;
use super::checked_journal_length_after_append;
use crate::EVIDENCE_DATABASE_LINEAGE;
use crate::EVIDENCE_FRONTIER_BACKEND_IDENTITY_FILENAME;
use crate::EVIDENCE_FRONTIER_BACKEND_JOURNAL_DIRECTORY;
use crate::EVIDENCE_RECOVERY_FRONTIER_V2_SCHEMA_VERSION;
use crate::EvidenceFrontierBackend;
use crate::EvidenceFrontierBackendError;
use crate::EvidenceFrontierBackendIdentityV1;
use crate::EvidenceFrontierHistoryRangeV1;
use crate::EvidenceRecoveryFrontierSignatureV2;
use crate::EvidenceRecoveryFrontierV2;
use crate::EvidenceRecoverySnapshotV1;
use crate::evidence_recovery_ledger_root_v2;
use crate::frontier_backend::EVIDENCE_FRONTIER_BACKEND_IDENTITY_SCHEMA_VERSION;
use crate::frontier_backend::EVIDENCE_FRONTIER_BACKEND_STORAGE_CLASS;
use crate::frontier_backend::EVIDENCE_FRONTIER_MAX_AUDIT_RECORDS;
use crate::frontier_backend::EVIDENCE_FRONTIER_MAX_JOURNAL_BYTES;

struct Fixture {
    _external: TempDir,
    _local: TempDir,
    backend_root: std::path::PathBuf,
    local_root: std::path::PathBuf,
    identity_sha256: Sha256Digest,
}

impl Fixture {
    fn new() -> Self {
        let external = tempfile::tempdir().expect("external temporary root");
        let local = tempfile::tempdir().expect("local temporary root");
        let backend_root = external.path().join("backend");
        let journals = backend_root.join(EVIDENCE_FRONTIER_BACKEND_JOURNAL_DIRECTORY);
        std::fs::create_dir(&backend_root).expect("create backend root");
        std::fs::create_dir(&journals).expect("create journal root");
        std::fs::set_permissions(&backend_root, std::fs::Permissions::from_mode(0o700))
            .expect("protect backend root");
        std::fs::set_permissions(&journals, std::fs::Permissions::from_mode(0o700))
            .expect("protect journal root");
        std::fs::set_permissions(local.path(), std::fs::Permissions::from_mode(0o700))
            .expect("protect local root");

        let identity = EvidenceFrontierBackendIdentityV1 {
            schema_version: EVIDENCE_FRONTIER_BACKEND_IDENTITY_SCHEMA_VERSION,
            backend_id: "backend:kernel-evidence-test".to_string(),
            authority_id: "authority:kernel-evidence-test".to_string(),
            authority_generation: 4,
            storage_class: EVIDENCE_FRONTIER_BACKEND_STORAGE_CLASS.to_string(),
        };
        let identity_bytes = serde_json::to_vec(&identity).expect("serialize backend identity");
        let identity_path = backend_root.join(EVIDENCE_FRONTIER_BACKEND_IDENTITY_FILENAME);
        std::fs::write(&identity_path, &identity_bytes).expect("write backend identity");
        std::fs::set_permissions(&identity_path, std::fs::Permissions::from_mode(0o600))
            .expect("protect backend identity");

        let backend_root = backend_root.canonicalize().expect("canonical backend root");
        let local_root = local.path().canonicalize().expect("canonical local root");
        Self {
            _external: external,
            _local: local,
            backend_root,
            local_root,
            identity_sha256: Sha256Digest::for_bytes(&identity_bytes),
        }
    }

    fn open(&self) -> LockedFileEvidenceFrontierBackend {
        LockedFileEvidenceFrontierBackend::open_same_filesystem_for_testing(
            &self.backend_root,
            self.identity_sha256.clone(),
            &self.local_root,
        )
        .expect("open test backend")
    }
}

fn frontier(
    generation: u64,
    backend_identity_sha256: Sha256Digest,
) -> EvidenceRecoveryFrontierV2 {
    let snapshot = EvidenceRecoverySnapshotV1 {
        schema_version: 1,
        database_lineage: EVIDENCE_DATABASE_LINEAGE.to_string(),
        migration_set_sha256: Sha256Digest::for_bytes(b"migrations"),
        qualification_max_seq: generation,
        qualification_frontier_sha256: Sha256Digest::for_bytes(
            format!("qualification-{generation}").as_bytes(),
        ),
        authbus_replay_frontier_sha256: Sha256Digest::for_bytes(b"replay"),
    };
    EvidenceRecoveryFrontierV2 {
        schema_version: EVIDENCE_RECOVERY_FRONTIER_V2_SCHEMA_VERSION,
        store_id: "store:kernel-evidence".to_string(),
        frontier_generation: generation,
        ledger_root_sha256: evidence_recovery_ledger_root_v2(&snapshot),
        snapshot,
        issuer_trust_registry_sha256: Sha256Digest::for_bytes(b"issuer-trust"),
        frontier_signer_registry_sha256: Sha256Digest::for_bytes(b"signer-trust"),
        backend_identity_sha256,
        build_artifact_sha256: Sha256Digest::for_bytes(b"build"),
        qualification_receipt_sha256: Sha256Digest::for_bytes(b"qualification-receipt"),
        backup_publication_sha256: Sha256Digest::for_bytes(b"backup"),
        source_commit: "a".repeat(40),
        source_tree: "b".repeat(40),
        created_at_unix_ms: 1_900_000_000_000 + generation,
        signer_policy_generation: 2,
        signatures: vec![EvidenceRecoveryFrontierSignatureV2 {
            signer_principal_id: "issuer:recovery".to_string(),
            signer_key_epoch: 2,
            signature_hex: "11".repeat(64),
        }],
    }
}

#[test]
fn append_capacity_is_rejected_before_a_write_starts() {
    assert_eq!(
        checked_journal_length_after_append(7, 0, 5).expect("bounded append"),
        12
    );
    assert!(matches!(
        checked_journal_length_after_append(EVIDENCE_FRONTIER_MAX_JOURNAL_BYTES, 0, 1),
        Err(EvidenceFrontierBackendError::Invalid(message))
            if message.contains("byte capacity")
    ));
    assert!(matches!(
        checked_journal_length_after_append(0, EVIDENCE_FRONTIER_MAX_AUDIT_RECORDS, 1),
        Err(EvidenceFrontierBackendError::Invalid(message))
            if message.contains("record capacity")
    ));
}

#[test]
fn production_open_rejects_a_backend_in_the_local_rollback_device() {
    let fixture = Fixture::new();
    assert!(matches!(
        LockedFileEvidenceFrontierBackend::open_external(
            &fixture.backend_root,
            fixture.identity_sha256.clone(),
            &fixture.local_root,
        ),
        Err(EvidenceFrontierBackendError::Invalid(message))
            if message.contains("outside the local rollback domain")
    ));
}

#[test]
fn locked_backend_linearizes_cas_and_returns_durable_acknowledgements() {
    let fixture = Fixture::new();
    let mut backend = fixture.open();
    assert_eq!(backend.get_latest("store:kernel-evidence").unwrap(), None);

    let first = frontier(1, fixture.identity_sha256.clone());
    let first_ack = backend
        .compare_and_swap("store:kernel-evidence", None, &first)
        .expect("publish first frontier");
    assert_eq!(first_ack.frontier_generation, 1);
    assert_eq!(first_ack.audit_sequence, 1);
    assert_eq!(
        backend.get_latest("store:kernel-evidence").unwrap(),
        Some(first.clone())
    );

    let second = frontier(2, fixture.identity_sha256.clone());
    let second_ack = backend
        .compare_and_swap("store:kernel-evidence", Some(1), &second)
        .expect("publish second frontier");
    assert_eq!(second_ack.frontier_generation, 2);
    assert_eq!(second_ack.audit_sequence, 2);
    assert_eq!(
        backend
            .get_history(
                "store:kernel-evidence",
                EvidenceFrontierHistoryRangeV1::new(1, 2).unwrap(),
            )
            .unwrap(),
        vec![first, second]
    );
}

#[test]
fn locked_backend_rejects_stale_or_skipped_generations() {
    let fixture = Fixture::new();
    let mut backend = fixture.open();
    backend
        .compare_and_swap(
            "store:kernel-evidence",
            None,
            &frontier(1, fixture.identity_sha256.clone()),
        )
        .expect("publish first frontier");

    assert!(matches!(
        backend.compare_and_swap(
            "store:kernel-evidence",
            None,
            &frontier(1, fixture.identity_sha256.clone()),
        ),
        Err(EvidenceFrontierBackendError::Conflict {
            expected: None,
            actual: Some(1)
        })
    ));
    assert!(matches!(
        backend.compare_and_swap(
            "store:kernel-evidence",
            Some(1),
            &frontier(3, fixture.identity_sha256.clone()),
        ),
        Err(EvidenceFrontierBackendError::Invalid(_))
    ));
}

#[test]
fn locked_backend_rejects_torn_audit_tails() {
    let fixture = Fixture::new();
    let mut backend = fixture.open();
    backend
        .compare_and_swap(
            "store:kernel-evidence",
            None,
            &frontier(1, fixture.identity_sha256.clone()),
        )
        .expect("publish first frontier");
    let journal = backend
        .journal_path("store:kernel-evidence")
        .expect("journal path");
    OpenOptions::new()
        .append(true)
        .open(journal)
        .and_then(|mut file| file.write_all(b"{\"torn\":"))
        .expect("append torn tail");

    assert!(matches!(
        backend.get_latest("store:kernel-evidence"),
        Err(EvidenceFrontierBackendError::Corrupt(message))
            if message.contains("torn tail")
    ));
}

#[test]
fn locked_backend_rejects_empty_audit_records() {
    let fixture = Fixture::new();
    let mut backend = fixture.open();
    backend
        .compare_and_swap(
            "store:kernel-evidence",
            None,
            &frontier(1, fixture.identity_sha256.clone()),
        )
        .expect("publish first frontier");
    let journal = backend
        .journal_path("store:kernel-evidence")
        .expect("journal path");
    OpenOptions::new()
        .append(true)
        .open(journal)
        .and_then(|mut file| file.write_all(b"\n"))
        .expect("append empty audit record");

    assert!(matches!(
        backend.get_latest("store:kernel-evidence"),
        Err(EvidenceFrontierBackendError::Corrupt(message))
            if message.contains("empty record")
    ));
}

#[test]
fn locked_backend_detects_identity_drift() {
    let fixture = Fixture::new();
    let mut backend = fixture.open();
    let identity_path = fixture
        .backend_root
        .join(EVIDENCE_FRONTIER_BACKEND_IDENTITY_FILENAME);
    let changed = EvidenceFrontierBackendIdentityV1 {
        schema_version: EVIDENCE_FRONTIER_BACKEND_IDENTITY_SCHEMA_VERSION,
        backend_id: "backend:kernel-evidence-test".to_string(),
        authority_id: "authority:kernel-evidence-test".to_string(),
        authority_generation: 5,
        storage_class: EVIDENCE_FRONTIER_BACKEND_STORAGE_CLASS.to_string(),
    };
    std::fs::write(
        &identity_path,
        serde_json::to_vec(&changed).expect("serialize changed identity"),
    )
    .expect("replace identity");
    std::fs::set_permissions(&identity_path, std::fs::Permissions::from_mode(0o600))
        .expect("protect changed identity");

    assert!(matches!(
        backend.verify_backend_identity(),
        Err(EvidenceFrontierBackendError::Invalid(message))
            if message.contains("changed after bootstrap")
    ));
}

#[test]
fn locked_backend_rejects_replaced_journal_directory() {
    let fixture = Fixture::new();
    let mut backend = fixture.open();
    let journals = fixture
        .backend_root
        .join(EVIDENCE_FRONTIER_BACKEND_JOURNAL_DIRECTORY);
    let retired = fixture.backend_root.join("frontiers-retired");
    std::fs::rename(&journals, &retired).expect("retire pinned journal directory");
    std::fs::create_dir(&journals).expect("replace journal directory");
    std::fs::set_permissions(&journals, std::fs::Permissions::from_mode(0o700))
        .expect("protect replacement journal directory");

    assert!(matches!(
        backend.get_latest("store:kernel-evidence"),
        Err(EvidenceFrontierBackendError::Invalid(message))
            if message.contains("directory identity changed")
    ));
}

#[test]
fn concurrent_first_generation_publish_has_exactly_one_winner() {
    let fixture = Fixture::new();
    let left_backend = fixture.open();
    let right_backend = fixture.open();
    let left_identity = fixture.identity_sha256.clone();
    let right_identity = fixture.identity_sha256.clone();
    let barrier = Arc::new(Barrier::new(3));
    let left_barrier = Arc::clone(&barrier);
    let right_barrier = Arc::clone(&barrier);

    let (left_result, right_result) = std::thread::scope(|scope| {
        let left = scope.spawn(move || {
            let mut backend = left_backend;
            left_barrier.wait();
            backend.compare_and_swap(
                "store:kernel-evidence",
                None,
                &frontier(1, left_identity),
            )
        });
        let right = scope.spawn(move || {
            let mut backend = right_backend;
            right_barrier.wait();
            backend.compare_and_swap(
                "store:kernel-evidence",
                None,
                &frontier(1, right_identity),
            )
        });
        barrier.wait();
        (
            left.join().expect("left publisher"),
            right.join().expect("right publisher"),
        )
    });

    let successes = left_result.is_ok() as usize + right_result.is_ok() as usize;
    let conflicts = matches!(
        left_result,
        Err(EvidenceFrontierBackendError::Conflict { .. })
    ) as usize
        + matches!(
            right_result,
            Err(EvidenceFrontierBackendError::Conflict { .. })
        ) as usize;
    assert_eq!((successes, conflicts), (1, 1));
}
