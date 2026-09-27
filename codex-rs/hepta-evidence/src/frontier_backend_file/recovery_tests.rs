#![cfg(unix)]

use std::os::unix::fs::PermissionsExt;

use super::*;
use crate::EVIDENCE_DATABASE_LINEAGE;
use crate::EvidenceRecoveryFrontierSignatureV2;
use crate::EvidenceRecoverySnapshotV1;
use crate::evidence_recovery_ledger_root_v2;
use crate::frontier_backend::EVIDENCE_FRONTIER_BACKEND_IDENTITY_SCHEMA_VERSION;
use crate::frontier_backend::EVIDENCE_FRONTIER_BACKEND_STORAGE_CLASS;

struct Fixture {
    _external: tempfile::TempDir,
    local: tempfile::TempDir,
    root: PathBuf,
    identity_sha256: Sha256Digest,
}

impl Fixture {
    fn new() -> Self {
        let external = tempfile::tempdir().expect("external root");
        let local = tempfile::tempdir().expect("local root");
        let root = external.path().join("backend");
        let journals = root.join(EVIDENCE_FRONTIER_BACKEND_JOURNAL_DIRECTORY);
        std::fs::create_dir(&root).unwrap();
        std::fs::create_dir(&journals).unwrap();
        for directory in [&root, &journals, &local.path().to_path_buf()] {
            std::fs::set_permissions(directory, std::fs::Permissions::from_mode(0o700)).unwrap();
        }
        let identity = EvidenceFrontierBackendIdentityV1 {
            schema_version: EVIDENCE_FRONTIER_BACKEND_IDENTITY_SCHEMA_VERSION,
            backend_id: "backend:recovery-test".to_string(),
            authority_id: "authority:recovery-test".to_string(),
            authority_generation: 1,
            storage_class: EVIDENCE_FRONTIER_BACKEND_STORAGE_CLASS.to_string(),
        };
        let bytes = serde_json::to_vec(&identity).unwrap();
        let identity_path = root.join(EVIDENCE_FRONTIER_BACKEND_IDENTITY_FILENAME);
        std::fs::write(&identity_path, &bytes).unwrap();
        std::fs::set_permissions(&identity_path, std::fs::Permissions::from_mode(0o600)).unwrap();
        Self {
            _external: external,
            local,
            root: root.canonicalize().unwrap(),
            identity_sha256: Sha256Digest::for_bytes(&bytes),
        }
    }

    fn open(&self) -> LockedFileEvidenceFrontierBackend {
        LockedFileEvidenceFrontierBackend::open_same_filesystem_for_testing(
            &self.root,
            self.identity_sha256.clone(),
            self.local.path(),
        )
        .unwrap()
    }

    fn frontier(&self, generation: u64) -> EvidenceRecoveryFrontierV2 {
        let snapshot = EvidenceRecoverySnapshotV1 {
            schema_version: 1,
            database_lineage: EVIDENCE_DATABASE_LINEAGE.to_string(),
            migration_set_sha256: Sha256Digest::for_bytes(b"migrations"),
            qualification_max_seq: generation,
            qualification_frontier_sha256: Sha256Digest::for_bytes(&generation.to_be_bytes()),
            authbus_replay_frontier_sha256: Sha256Digest::for_bytes(b"replay"),
        };
        EvidenceRecoveryFrontierV2 {
            schema_version: 2,
            store_id: "store:recovery-test".to_string(),
            frontier_generation: generation,
            ledger_root_sha256: evidence_recovery_ledger_root_v2(&snapshot),
            snapshot,
            issuer_trust_registry_sha256: Sha256Digest::for_bytes(b"issuer"),
            frontier_signer_registry_sha256: Sha256Digest::for_bytes(b"signer"),
            backend_identity_sha256: self.identity_sha256.clone(),
            build_artifact_sha256: Sha256Digest::for_bytes(b"build"),
            qualification_receipt_sha256: Sha256Digest::for_bytes(b"qualification"),
            backup_publication_sha256: Sha256Digest::for_bytes(b"backup"),
            source_commit: "a".repeat(40),
            source_tree: "b".repeat(40),
            created_at_unix_ms: 1_900_000_000_000 + generation,
            signer_policy_generation: 1,
            // Storage fixtures do not confer production signature authority.
            signatures: vec![EvidenceRecoveryFrontierSignatureV2 {
                signer_principal_id: "signer:fixture".to_string(),
                signer_key_epoch: 1,
                signature_hex: "11".repeat(64),
            }],
        }
    }

    fn publish(&self, backend: &mut LockedFileEvidenceFrontierBackend) -> EvidenceFrontierDurableAckV1 {
        let frontier = self.frontier(1);
        backend.compare_and_swap(&frontier.store_id, None, &frontier).unwrap()
    }
}

#[test]
fn recovery_reissues_the_original_ack_without_appending() {
    let fixture = Fixture::new();
    let mut backend = fixture.open();
    let original = fixture.publish(&mut backend);
    let path = backend.journal_path(&original.store_id).unwrap();
    let before = std::fs::read(&path).unwrap();
    drop(backend);
    let mut reopened = fixture.open();
    assert_eq!(
        reopened.recover_durable_acknowledgement(&original.store_id, 1, &original.frontier_sha256).unwrap(),
        Some(original)
    );
    assert_eq!(std::fs::read(path).unwrap(), before);
}

#[test]
fn recovery_never_creates_an_absent_journal() {
    let fixture = Fixture::new();
    let mut backend = fixture.open();
    let proposed = fixture.frontier(1);
    let path = backend.journal_path(&proposed.store_id).unwrap();
    let digest = evidence_recovery_frontier_v2_sha256(&proposed).unwrap();
    assert_eq!(backend.recover_durable_acknowledgement(&proposed.store_id, 1, &digest).unwrap(), None);
    assert!(!path.exists());
}

#[test]
fn recovery_rejects_a_substituted_digest() {
    let fixture = Fixture::new();
    let mut backend = fixture.open();
    let original = fixture.publish(&mut backend);
    assert!(matches!(
        backend.recover_durable_acknowledgement(&original.store_id, 1, &Sha256Digest::for_bytes(b"wrong")),
        Err(EvidenceFrontierBackendError::Invalid(_))
    ));
}

#[test]
fn recovery_can_find_the_exact_ack_after_a_later_generation() {
    let fixture = Fixture::new();
    let mut backend = fixture.open();
    let original = fixture.publish(&mut backend);
    let second = fixture.frontier(2);
    backend.compare_and_swap(&second.store_id, Some(1), &second).unwrap();
    assert_eq!(backend.recover_durable_acknowledgement(&original.store_id, 1, &original.frontier_sha256).unwrap(), Some(original));
    assert_eq!(backend.get_latest(&second.store_id).unwrap(), Some(second));
}

#[test]
fn failed_resynchronization_poison_is_not_cleared_by_retry() {
    let fixture = Fixture::new();
    let mut backend = fixture.open();
    let original = fixture.publish(&mut backend);
    let recovered = backend.recover_ack_with_sync(&original.store_id, 1, &original.frontier_sha256, |_, _| {
        Err(io::Error::other("injected directory fsync failure"))
    });
    assert!(matches!(recovered, Err(EvidenceFrontierBackendError::Indeterminate(_))));
    assert!(matches!(backend.recover_durable_acknowledgement(&original.store_id, 1, &original.frontier_sha256), Err(EvidenceFrontierBackendError::Indeterminate(_))));
    let mut reopened = fixture.open();
    assert_eq!(reopened.recover_durable_acknowledgement(&original.store_id, 1, &original.frontier_sha256).unwrap(), Some(original));
}

#[test]
fn replacement_during_resynchronization_cannot_produce_an_ack() {
    let fixture = Fixture::new();
    let mut backend = fixture.open();
    let original = fixture.publish(&mut backend);
    let path = backend.journal_path(&original.store_id).unwrap();
    let replacement = path.with_extension("replacement");
    std::fs::copy(&path, &replacement).unwrap();
    let recovered = backend.recover_ack_with_sync(&original.store_id, 1, &original.frontier_sha256, |file, directory| {
        file.sync_all()?;
        std::fs::rename(&replacement, &path)?;
        directory.sync_all()
    });
    assert!(matches!(recovered, Err(EvidenceFrontierBackendError::Indeterminate(_))));
}

#[test]
fn torn_tail_prevents_recovery_even_of_an_earlier_record() {
    let fixture = Fixture::new();
    let mut backend = fixture.open();
    let original = fixture.publish(&mut backend);
    let path = backend.journal_path(&original.store_id).unwrap();
    OpenOptions::new().append(true).open(path).unwrap().write_all(b"{torn").unwrap();
    assert!(matches!(backend.recover_durable_acknowledgement(&original.store_id, 1, &original.frontier_sha256), Err(EvidenceFrontierBackendError::Corrupt(_))));
}

#[test]
fn recovery_lock_contention_is_bounded_and_does_not_append() {
    let fixture = Fixture::new();
    let mut backend = fixture.open();
    let original = fixture.publish(&mut backend);
    let path = backend.journal_path(&original.store_id).unwrap();
    let held = OpenOptions::new().read(true).write(true).open(path).unwrap();
    held.lock().unwrap();
    assert!(matches!(backend.recover_durable_acknowledgement(&original.store_id, 1, &original.frontier_sha256), Err(EvidenceFrontierBackendError::Unavailable(_))));
}
