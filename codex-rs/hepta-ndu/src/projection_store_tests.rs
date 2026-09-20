use std::fmt::Debug;
use std::fs;
use std::fs::File;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

#[cfg(unix)]
use std::os::unix::fs::symlink;

use codex_hepta_types::Digest32;

use super::JOURNAL_FILE;
use super::LOCK_FILE;
use super::NduProjectionStoreError;
use super::NduProjectionStoreV1;
use super::TEMP_FILE;
use crate::NduProjectionJournalError;
use crate::NduProjectionKindV1;

static NONCE: AtomicU64 = AtomicU64::new(1);

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
        must(store.select_projection(digest("selection-id"), objective, subject, projection));
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
        must(source.select_projection(digest("selection-id"), objective, subject, projection));
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
    must(store.select_projection(digest("selection-id"), objective, subject, projection));
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
fn indeterminate_handle_fails_closed_until_reopen() {
    let root = TempRoot::new("indeterminate");
    let objective = digest("objective");
    let subject = digest("subject");
    let projection = digest("projection");
    let mut store = must(NduProjectionStoreV1::open(&root.0));

    store.indeterminate = true;
    assert!(store.is_indeterminate());
    assert_eq!(
        store
            .entries()
            .expect_err("poisoned entries must fail closed"),
        NduProjectionStoreError::Indeterminate
    );
    assert_eq!(
        store
            .selected_projection_digest(objective, subject)
            .expect_err("poisoned selection read must fail closed"),
        NduProjectionStoreError::Indeterminate
    );
    assert_eq!(
        store
            .backup_bytes()
            .expect_err("poisoned backup export must fail closed"),
        NduProjectionStoreError::Indeterminate
    );
    assert_eq!(
        store
            .append_projection(
                NduProjectionKindV1::Preference,
                digest("projection-id"),
                objective,
                subject,
                projection,
            )
            .expect_err("poisoned mutation must fail closed"),
        NduProjectionStoreError::Indeterminate
    );

    drop(store);
    let reopened = must(NduProjectionStoreV1::open(&root.0));
    assert!(!reopened.is_indeterminate());
    assert!(must(reopened.entries()).is_empty());
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
