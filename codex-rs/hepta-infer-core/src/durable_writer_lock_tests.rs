use std::fs;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use crate::durable_control::DurableInferenceControl;
use crate::durable_control::Error;
use crate::durable_control::native::NativeMaintenanceStage;

struct Journal {
    directory: PathBuf,
    path: PathBuf,
}

impl Journal {
    fn new(name: &str) -> Self {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let directory =
            std::env::temp_dir().join(format!("hepta-writer-lock-{}-{nonce}", std::process::id()));
        fs::create_dir_all(&directory).unwrap();
        Self {
            path: directory.join(name),
            directory,
        }
    }
}

impl Drop for Journal {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.directory);
    }
}

#[test]
fn detached_generation_lock_does_not_replace_the_lifecycle_lock() {
    let journal = Journal::new("control.journal");
    let mut owner = DurableInferenceControl::open(&journal.path, /*capacity*/ 8).unwrap();
    // An opener can obtain the old descriptor before the generation rename,
    // then win its inode lock after compaction has dropped that descriptor.
    let stale = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&journal.path)
        .unwrap();
    owner.compact_native_journal().unwrap();
    stale.try_lock().unwrap();
    assert!(matches!(
        super::acquire(&journal.path),
        Err(Error::WriterUnavailable)
    ));
    assert!(matches!(
        DurableInferenceControl::open(&journal.path, /*capacity*/ 8),
        Err(Error::WriterUnavailable)
    ));
    drop(stale);
    drop(owner);
    let reopened = DurableInferenceControl::open(&journal.path, /*capacity*/ 8).unwrap();
    assert_eq!(
        reopened
            .native_metrics(/*now_unix_ms*/ 0)
            .checkpoint_generation,
        1
    );
}

#[test]
fn renamed_generation_failure_retains_ownership_until_the_owner_exits() {
    for stage in [
        NativeMaintenanceStage::AfterGenerationRename,
        NativeMaintenanceStage::AfterParentSync,
    ] {
        let journal = Journal::new("control.journal");
        let mut owner = DurableInferenceControl::open(&journal.path, /*capacity*/ 8).unwrap();
        let mut failpoint = |observed| {
            if observed == stage {
                Err(Error::InvalidTransition)
            } else {
                Ok(())
            }
        };
        assert_eq!(
            owner.compact_native_journal_with_failpoint(/*now_unix_ms*/ 1, &mut failpoint),
            Err(Error::InvalidTransition)
        );
        assert_eq!(
            owner.compact_native_journal(),
            Err(Error::WriterUnavailable)
        );
        assert!(matches!(
            DurableInferenceControl::open(&journal.path, /*capacity*/ 8),
            Err(Error::WriterUnavailable)
        ));
        drop(owner);
        let reopened = DurableInferenceControl::open(&journal.path, /*capacity*/ 8).unwrap();
        assert_eq!(
            reopened
                .native_metrics(/*now_unix_ms*/ 0)
                .checkpoint_generation,
            1
        );
    }
}

#[test]
fn compaction_rejects_journal_growth_and_fences_the_stale_owner() {
    let journal = Journal::new("control.journal");
    let mut owner = DurableInferenceControl::open(&journal.path, /*capacity*/ 8).unwrap();
    OpenOptions::new()
        .write(true)
        .open(&journal.path)
        .unwrap()
        .set_len(super::super::MAX_JOURNAL_BYTES + 1)
        .unwrap();
    assert_eq!(owner.compact_native_journal(), Err(Error::CapacityExceeded));
    assert_eq!(
        owner.compact_native_journal(),
        Err(Error::WriterUnavailable)
    );
}

#[cfg(unix)]
#[test]
fn long_journal_names_and_existing_symlink_aliases_share_a_short_lock() {
    let journal = Journal::new(&"j".repeat(250));
    let mut owner = DurableInferenceControl::open(&journal.path, /*capacity*/ 8).unwrap();
    owner.compact_native_journal().unwrap();
    let alias = journal.directory.join("alias.journal");
    std::os::unix::fs::symlink(&journal.path, &alias).unwrap();
    assert!(matches!(
        DurableInferenceControl::open(&alias, /*capacity*/ 8),
        Err(Error::WriterUnavailable)
    ));
    drop(owner);
    let reopened = DurableInferenceControl::open(&alias, /*capacity*/ 8).unwrap();
    assert_eq!(
        reopened
            .native_metrics(/*now_unix_ms*/ 0)
            .checkpoint_generation,
        1
    );
}

#[cfg(unix)]
#[test]
fn a_dangling_journal_symlink_cannot_split_the_compaction_owner() {
    let journal = Journal::new("target.journal");
    let alias = journal.directory.join("alias.journal");
    std::os::unix::fs::symlink(&journal.path, &alias).unwrap();
    assert!(matches!(
        DurableInferenceControl::open(&alias, /*capacity*/ 8),
        Err(Error::InvalidIdentity("native dangling journal symlink"))
    ));
    assert!(!journal.path.exists());
    assert!(
        fs::symlink_metadata(&alias)
            .unwrap()
            .file_type()
            .is_symlink()
    );
    // A regular absent path remains a valid journal creation request.
    let mut owner = DurableInferenceControl::open(&journal.path, /*capacity*/ 8).unwrap();
    owner.compact_native_journal().unwrap();
    assert!(matches!(
        DurableInferenceControl::open(&alias, /*capacity*/ 8),
        Err(Error::WriterUnavailable)
    ));
}
