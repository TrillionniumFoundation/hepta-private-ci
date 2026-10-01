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
use super::NduProjectionStoreError;
use super::NduProjectionStoreV1;
use super::ProjectionPersistenceV1;
use super::TEMP_FILE;
use crate::NduProjectionJournalError;
use crate::NduProjectionKindV1;

static NONCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum FaultStage {
    Write,
    FileSync,
    Rename,
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
        self.real.rename(from, to)
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

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

struct TempRoot(PathBuf);

impl TempRoot {
    fn new(label: &str) -> io::Result<Self> {
        let nonce = NONCE.fetch_add(1, Ordering::Relaxed);
        let path =
            std::env::temp_dir().join(format!("hepta-ndu-{label}-{}-{nonce}", std::process::id()));
        fs::create_dir(&path)?;
        Ok(Self(path))
    }
}

impl Drop for TempRoot {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn durable_writer_round_trips_selected_and_revoked_state() -> Result<(), Box<dyn std::error::Error>>
{
    let root = TempRoot::new("roundtrip")?;
    let objective = digest("objective");
    let subject = digest("subject");
    let projection = digest("projection");

    {
        let mut store = (NduProjectionStoreV1::open(&root.0))?;
        (store.append_projection(
            NduProjectionKindV1::Preference,
            digest("projection-id"),
            objective,
            subject,
            projection,
        ))?;
        (store.select_projection(digest("selection-id"), objective, subject, projection))?;
        assert_eq!(
            (store.selected_projection_digest(objective, subject))?,
            Some(projection)
        );
    }

    {
        let mut store = (NduProjectionStoreV1::open(&root.0))?;
        assert_eq!(
            (store.selected_projection_digest(objective, subject))?,
            Some(projection)
        );
        (store.revoke_projection(digest("revocation-id"), objective, subject, projection))?;
        assert_eq!(
            (store.selected_projection_digest(objective, subject))?,
            None
        );
    }

    let store = (NduProjectionStoreV1::open(&root.0))?;
    assert_eq!(
        (store.selected_projection_digest(objective, subject))?,
        None
    );
    assert_eq!((store.entries())?.len(), 3);
    Ok(())
}

#[test]
fn backup_restore_is_validated_before_replacing_live_state()
-> Result<(), Box<dyn std::error::Error>> {
    let source_root = TempRoot::new("backup-source")?;
    let target_root = TempRoot::new("backup-target")?;
    let objective = digest("objective");
    let subject = digest("subject");
    let projection = digest("projection");

    let backup = {
        let mut source = (NduProjectionStoreV1::open(&source_root.0))?;
        (source.append_projection(
            NduProjectionKindV1::Utility,
            digest("projection-id"),
            objective,
            subject,
            projection,
        ))?;
        (source.select_projection(digest("selection-id"), objective, subject, projection))?;
        (source.backup_bytes())?
    };

    let mut target = (NduProjectionStoreV1::open(&target_root.0))?;
    (target.restore_backup(&backup))?;
    assert_eq!(
        (target.selected_projection_digest(objective, subject))?,
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
        (target.selected_projection_digest(objective, subject))?,
        Some(projection)
    );
    Ok(())
}

#[test]
fn older_valid_backup_cannot_remove_a_later_revocation() -> Result<(), Box<dyn std::error::Error>> {
    let root = TempRoot::new("backup-regression")?;
    let objective = digest("objective");
    let subject = digest("subject");
    let projection = digest("projection");
    let mut store = (NduProjectionStoreV1::open(&root.0))?;
    (store.append_projection(
        NduProjectionKindV1::Preference,
        digest("projection-id"),
        objective,
        subject,
        projection,
    ))?;
    (store.select_projection(digest("selection-id"), objective, subject, projection))?;
    let old_backup = (store.backup_bytes())?;
    (store.revoke_projection(digest("revocation-id"), objective, subject, projection))?;
    assert_eq!(
        (store.selected_projection_digest(objective, subject))?,
        None
    );

    assert_eq!(
        store
            .restore_backup(&old_backup)
            .expect_err("backup rollback must not resurrect selection"),
        NduProjectionStoreError::BackupRegression
    );
    assert_eq!(
        (store.selected_projection_digest(objective, subject))?,
        None
    );
    Ok(())
}

#[test]
fn stale_uncommitted_temp_image_is_discarded_before_recovery()
-> Result<(), Box<dyn std::error::Error>> {
    let root = TempRoot::new("stale-temp")?;
    let mut temp = File::create(root.0.join(TEMP_FILE)).expect("create stale temp image");
    temp.write_all(b"uncommitted garbage")
        .expect("write stale temp image");
    temp.sync_all().expect("sync stale temp fixture");
    drop(temp);

    let store = (NduProjectionStoreV1::open(&root.0))?;
    assert!((store.entries())?.is_empty());
    assert!(!root.0.join(TEMP_FILE).exists());
    Ok(())
}

#[test]
fn concurrent_writer_is_rejected_while_owner_lock_is_live() -> Result<(), Box<dyn std::error::Error>>
{
    let root = TempRoot::new("writer-lock")?;
    let owner = (NduProjectionStoreV1::open(&root.0))?;
    let error = NduProjectionStoreV1::open(&root.0)
        .err()
        .expect("second writer must reject");
    assert_eq!(error, NduProjectionStoreError::Busy);
    drop(owner);
    (NduProjectionStoreV1::open(&root.0))?;
    Ok(())
}

#[test]
fn persistence_failpoints_reconcile_at_real_durability_boundaries()
-> Result<(), Box<dyn std::error::Error>> {
    for stage in [
        FaultStage::Write,
        FaultStage::FileSync,
        FaultStage::Rename,
        FaultStage::DirectorySync,
    ] {
        let root = TempRoot::new(match stage {
            FaultStage::Write => "fail-write",
            FaultStage::FileSync => "fail-file-sync",
            FaultStage::Rename => "fail-rename",
            FaultStage::DirectorySync => "fail-directory-sync",
        })?;
        {
            let store = (NduProjectionStoreV1::open(&root.0))?;
            drop(store);
        }

        let persistence = Arc::new(FaultPersistence {
            stage,
            real: FsProjectionPersistenceV1,
        });
        let mut store = (NduProjectionStoreV1::open_with_persistence(&root.0, persistence))?;
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

        if stage == FaultStage::DirectorySync {
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
            assert!((store.entries())?.is_empty());
        }

        drop(store);
        let reopened = (NduProjectionStoreV1::open(&root.0))?;
        assert!(!reopened.is_indeterminate());
        if stage == FaultStage::DirectorySync {
            assert_eq!((reopened.entries())?.len(), 1);
        } else {
            assert!((reopened.entries())?.is_empty());
        }
    }
    Ok(())
}

#[cfg(unix)]
#[test]
fn symlinked_root_lock_and_journal_paths_fail_closed() -> Result<(), Box<dyn std::error::Error>> {
    let target_root = TempRoot::new("symlink-target")?;
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

    let lock_root = TempRoot::new("symlink-lock")?;
    symlink(&target_file, lock_root.0.join(LOCK_FILE)).expect("create lock symlink");
    assert_eq!(
        NduProjectionStoreV1::open(&lock_root.0)
            .err()
            .expect("symlinked lock must reject"),
        NduProjectionStoreError::Symlink
    );

    let journal_root = TempRoot::new("symlink-journal")?;
    {
        let store = (NduProjectionStoreV1::open(&journal_root.0))?;
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
    Ok(())
}
