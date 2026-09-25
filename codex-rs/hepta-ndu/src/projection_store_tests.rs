use std::fmt::Debug;
use std::fs;
use std::fs::File;
use std::io;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

#[cfg(unix)]
use std::os::unix::fs::symlink;

use codex_hepta_types::Digest32;

use super::FsProjectionPersistenceV1;
use super::JOURNAL_FILE;
use super::LOCK_FILE;
use super::MAX_BACKUP_BYTES;
use super::NduProjectionStoreError;
use super::NduProjectionStoreV1;
use super::ProjectionPersistenceV1;
use super::TEMP_FILE;
use crate::NduProjectionJournalError;
use crate::NduProjectionJournalV1;
use crate::NduProjectionKindV1;
use crate::projection_journal::MAX_RECORDS;

static NONCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum FaultStage {
    Write,
    FileSync,
    Rename,
    RenameAfterCommit,
    DirectorySync,
}

struct FaultPersistence {
    stage: FaultStage,
    real: FsProjectionPersistenceV1,
}

impl ProjectionPersistenceV1 for FaultPersistence {
    fn write_temp(&self, path: &Path, bytes: &[u8]) -> io::Result<()> {
        if self.stage == FaultStage::Write {
            return Err(io::Error::other("injected NDU temp-write failure"));
        }
        self.real.write_temp(path, bytes)
    }

    fn sync_temp(&self, path: &Path) -> io::Result<()> {
        if self.stage == FaultStage::FileSync {
            return Err(io::Error::other("injected NDU file-sync failure"));
        }
        self.real.sync_temp(path)
    }

    fn rename(&self, from: &Path, to: &Path) -> io::Result<()> {
        if self.stage == FaultStage::Rename {
            return Err(io::Error::other("injected NDU rename failure"));
        }
        self.real.rename(from, to)?;
        if self.stage == FaultStage::RenameAfterCommit {
            return Err(io::Error::other("injected lost rename acknowledgement"));
        }
        Ok(())
    }

    fn sync_parent(&self, root: &Path) -> io::Result<()> {
        if self.stage == FaultStage::DirectorySync {
            return Err(io::Error::other(
                "injected NDU parent-directory-sync failure",
            ));
        }
        self.real.sync_parent(root)
    }
}

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

struct TempRoot(PathBuf);

impl TempRoot {
    fn new(label: &str) -> Self {
        let nonce = NONCE.fetch_add(1, Ordering::Relaxed);
        let path =
            std::env::temp_dir().join(format!("hepta-ndu-{label}-{}-{nonce}", std::process::id()));
        fs::create_dir(&path).expect("create temp NDU root");
        Self(path)
    }
}

impl Drop for TempRoot {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn durable_writer_round_trips_selected_and_revoked_state() {
    let root = TempRoot::new("roundtrip");
    let objective = digest("objective");
    let subject = digest("subject");
    let projection = digest("projection");

    {
        let mut store = must(NduProjectionStoreV1::open(&root.0));
        must(store.append_projection(
            NduProjectionKindV1::Preference,
            digest("projection-id"),
            objective,
            subject,
            projection,
        ));
        must(store.select_projection_if_current(
            digest("selection-id"),
            objective,
            subject,
            None,
            projection,
        ));
        assert_eq!(
            must(store.selected_projection_digest(objective, subject)),
            Some(projection)
        );
    }

    {
        let mut store = must(NduProjectionStoreV1::open(&root.0));
        assert_eq!(
            must(store.selected_projection_digest(objective, subject)),
            Some(projection)
        );
        must(store.revoke_projection(digest("revocation-id"), objective, subject, projection));
        assert_eq!(
            must(store.selected_projection_digest(objective, subject)),
            None
        );
    }

    let store = must(NduProjectionStoreV1::open(&root.0));
    assert_eq!(
        must(store.selected_projection_digest(objective, subject)),
        None
    );
    assert_eq!(must(store.entries()).len(), 3);
}

#[test]
fn backup_restore_is_validated_before_replacing_live_state() {
    let source_root = TempRoot::new("backup-source");
    let target_root = TempRoot::new("backup-target");
    let objective = digest("objective");
    let subject = digest("subject");
    let projection = digest("projection");

    let backup = {
        let mut source = must(NduProjectionStoreV1::open(&source_root.0));
        must(source.append_projection(
            NduProjectionKindV1::Utility,
            digest("projection-id"),
            objective,
            subject,
            projection,
        ));
        must(source.select_projection_if_current(
            digest("selection-id"),
            objective,
            subject,
            None,
            projection,
        ));
        must(source.backup_bytes())
    };

    let mut target = must(NduProjectionStoreV1::open(&target_root.0));
    must(target.restore_backup(&backup));
    assert_eq!(
        must(target.selected_projection_digest(objective, subject)),
        Some(projection)
    );

    let mut tampered = backup;
    let last = tampered.len() - 1;
    tampered[last] ^= 1;
    assert_eq!(
        target
            .restore_backup(&tampered)
            .expect_err("tampered backup must not replace live state"),
        NduProjectionStoreError::Journal(NduProjectionJournalError::CorruptEntryDigest)
    );
    assert_eq!(
        must(target.selected_projection_digest(objective, subject)),
        Some(projection)
    );
}

#[test]
fn older_valid_backup_cannot_remove_a_later_revocation() {
    let root = TempRoot::new("backup-regression");
    let objective = digest("objective");
    let subject = digest("subject");
    let projection = digest("projection");
    let mut store = must(NduProjectionStoreV1::open(&root.0));
    must(store.append_projection(
        NduProjectionKindV1::Preference,
        digest("projection-id"),
        objective,
        subject,
        projection,
    ));
    must(store.select_projection_if_current(
        digest("selection-id"),
        objective,
        subject,
        None,
        projection,
    ));
    let old_backup = must(store.backup_bytes());
    must(store.revoke_projection(digest("revocation-id"), objective, subject, projection));
    assert_eq!(
        must(store.selected_projection_digest(objective, subject)),
        None
    );

    assert_eq!(
        store
            .restore_backup(&old_backup)
            .expect_err("backup rollback must not resurrect selection"),
        NduProjectionStoreError::BackupRegression
    );
    assert_eq!(
        must(store.selected_projection_digest(objective, subject)),
        None
    );
}

#[test]
fn oversized_sparse_image_is_rejected_before_unbounded_read() {
    let root = TempRoot::new("oversized-image");
    let file = File::create(root.0.join(JOURNAL_FILE)).expect("create oversized fixture");
    let oversized = u64::try_from(MAX_BACKUP_BYTES)
        .expect("backup bound fits u64")
        .saturating_add(1);
    file.set_len(oversized).expect("extend sparse fixture");
    drop(file);

    assert_eq!(
        NduProjectionStoreV1::open(&root.0)
            .err()
            .expect("oversized image must reject"),
        NduProjectionStoreError::BackupTooLarge
    );
}

#[test]
fn full_capacity_envelope_preserves_revocation_and_restart_recovery() {
    let root = TempRoot::new("revocation-capacity");
    let objective = digest("capacity-objective");
    let subject = digest("capacity-subject");
    let mut journal = NduProjectionJournalV1::new();

    for index in 0..(MAX_RECORDS / 2) {
        must(journal.append_projection(
            NduProjectionKindV1::Preference,
            digest(&format!("capacity-identity-{index}")),
            objective,
            subject,
            digest(&format!("capacity-projection-{index}")),
        ));
    }
    let mut file = File::create(root.0.join(JOURNAL_FILE)).expect("create capacity fixture");
    file.write_all(&journal.export_bytes())
        .expect("write capacity fixture");
    file.sync_all().expect("sync capacity fixture");
    drop(file);

    let first_projection = digest("capacity-projection-0");
    {
        let mut store = must(NduProjectionStoreV1::open(&root.0));
        assert_eq!(must(store.entries()).len(), MAX_RECORDS / 2);
        assert_eq!(
            store
                .select_projection_if_current(
                    digest("capacity-selection"),
                    objective,
                    subject,
                    None,
                    first_projection,
                )
                .expect_err("ordinary selection cannot consume reserved revocation capacity"),
            NduProjectionStoreError::Journal(
                NduProjectionJournalError::RevocationCapacityExhausted
            )
        );
        must(store.revoke_projection(
            digest("capacity-revocation"),
            objective,
            subject,
            first_projection,
        ));
    }

    let mut reopened = must(NduProjectionStoreV1::open(&root.0));
    assert_eq!(must(reopened.entries()).len(), MAX_RECORDS / 2 + 1);
    must(journal.revoke_projection(
        digest("capacity-revocation"),
        objective,
        subject,
        first_projection,
    ));
    for index in 1..(MAX_RECORDS / 2 - 2) {
        must(journal.revoke_projection(
            digest(&format!("capacity-revocation-{index}")),
            objective,
            subject,
            digest(&format!("capacity-projection-{index}")),
        ));
    }
    // The prefix fixture is semantic history, not a claim of 2048 disk writes.
    must(reopened.restore_backup(&journal.export_bytes()));
    drop(reopened);
    for index in (MAX_RECORDS / 2 - 2)..(MAX_RECORDS / 2) {
        let mut store = must(NduProjectionStoreV1::open(&root.0));
        let identity = digest(&format!("capacity-revocation-{index}"));
        let projection = digest(&format!("capacity-projection-{index}"));
        let expected = must(journal.revoke_projection(identity, objective, subject, projection));
        assert_eq!(
            must(store.revoke_projection(identity, objective, subject, projection)),
            expected
        );
        // Exact retry is idempotent even after the last available slot is used.
        assert_eq!(
            must(store.revoke_projection(identity, objective, subject, projection)),
            expected
        );
    }
    let reopened = must(NduProjectionStoreV1::open(&root.0));
    assert_eq!(must(reopened.entries()).len(), MAX_RECORDS);
    assert_eq!(must(reopened.entries()), journal.entries());
    assert_eq!(
        must(reopened.selected_projection_digest(objective, subject)),
        None
    );
}

#[test]
fn stale_uncommitted_temp_image_is_discarded_before_recovery() {
    let root = TempRoot::new("stale-temp");
    let mut temp = File::create(root.0.join(TEMP_FILE)).expect("create stale temp image");
    temp.write_all(b"uncommitted garbage")
        .expect("write stale temp image");
    temp.sync_all().expect("sync stale temp fixture");
    drop(temp);

    let store = must(NduProjectionStoreV1::open(&root.0));
    assert!(must(store.entries()).is_empty());
    assert!(!root.0.join(TEMP_FILE).exists());
}

#[test]
fn concurrent_writer_is_rejected_while_owner_lock_is_live() {
    let root = TempRoot::new("writer-lock");
    let owner = must(NduProjectionStoreV1::open(&root.0));
    let error = NduProjectionStoreV1::open(&root.0)
        .err()
        .expect("second writer must reject");
    assert_eq!(error, NduProjectionStoreError::Busy);
    drop(owner);
    must(NduProjectionStoreV1::open(&root.0));
}

#[test]
fn persistence_failpoints_reconcile_at_real_durability_boundaries() {
    for stage in [
        FaultStage::Write,
        FaultStage::FileSync,
        FaultStage::Rename,
        FaultStage::RenameAfterCommit,
        FaultStage::DirectorySync,
    ] {
        let root = TempRoot::new(match stage {
            FaultStage::Write => "fail-write",
            FaultStage::FileSync => "fail-file-sync",
            FaultStage::Rename => "fail-rename",
            FaultStage::RenameAfterCommit => "fail-rename-after-commit",
            FaultStage::DirectorySync => "fail-directory-sync",
        });
        {
            let store = must(NduProjectionStoreV1::open(&root.0));
            drop(store);
        }

        let persistence = Arc::new(FaultPersistence {
            stage,
            real: FsProjectionPersistenceV1,
        });
        let mut store = must(NduProjectionStoreV1::open_with_persistence(
            &root.0,
            persistence,
        ));
        let objective = digest("objective");
        let subject = digest("subject");
        let projection = digest("projection");

        let error = store
            .append_projection(
                NduProjectionKindV1::Preference,
                digest("projection-id"),
                objective,
                subject,
                projection,
            )
            .expect_err("injected persistence failure must surface");

        if matches!(
            stage,
            FaultStage::Rename | FaultStage::RenameAfterCommit | FaultStage::DirectorySync
        ) {
            assert_eq!(error, NduProjectionStoreError::Indeterminate);
            assert!(store.is_indeterminate());
            assert_eq!(
                store
                    .entries()
                    .expect_err("indeterminate handle must fail closed"),
                NduProjectionStoreError::Indeterminate
            );
        } else {
            assert_eq!(error, NduProjectionStoreError::Io(io::ErrorKind::Other));
            assert!(!store.is_indeterminate());
            assert!(must(store.entries()).is_empty());
        }

        drop(store);
        let reopened = must(NduProjectionStoreV1::open(&root.0));
        assert!(!reopened.is_indeterminate());
        if matches!(
            stage,
            FaultStage::RenameAfterCommit | FaultStage::DirectorySync
        ) {
            assert_eq!(must(reopened.entries()).len(), 1);
        } else {
            assert!(must(reopened.entries()).is_empty());
        }
    }
}

#[cfg(unix)]
#[test]
fn symlinked_root_lock_and_journal_paths_fail_closed() {
    let target_root = TempRoot::new("symlink-target");
    let target_file = target_root.0.join("outside-file");
    File::create(&target_file).expect("create symlink target");

    let root_link = std::env::temp_dir().join(format!(
        "hepta-ndu-root-link-{}-{}",
        std::process::id(),
        NONCE.fetch_add(1, Ordering::Relaxed)
    ));
    symlink(&target_root.0, &root_link).expect("create root symlink");
    assert_eq!(
        NduProjectionStoreV1::open(&root_link)
            .err()
            .expect("symlinked root must reject"),
        NduProjectionStoreError::Symlink
    );
    fs::remove_file(&root_link).expect("remove root symlink");

    let lock_root = TempRoot::new("symlink-lock");
    symlink(&target_file, lock_root.0.join(LOCK_FILE)).expect("create lock symlink");
    assert_eq!(
        NduProjectionStoreV1::open(&lock_root.0)
            .err()
            .expect("symlinked lock must reject"),
        NduProjectionStoreError::Symlink
    );

    let journal_root = TempRoot::new("symlink-journal");
    {
        let store = must(NduProjectionStoreV1::open(&journal_root.0));
        drop(store);
    }
    fs::remove_file(journal_root.0.join(JOURNAL_FILE)).expect("remove journal fixture");
    symlink(&target_file, journal_root.0.join(JOURNAL_FILE)).expect("create journal symlink");
    assert_eq!(
        NduProjectionStoreV1::open(&journal_root.0)
            .err()
            .expect("symlinked journal must reject"),
        NduProjectionStoreError::Symlink
    );
}
