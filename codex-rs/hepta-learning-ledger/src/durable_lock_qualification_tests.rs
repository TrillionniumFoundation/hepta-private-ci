//! Real file observations retain the owner lock and byte-level sensitivity.

use std::fs;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;

use super::LockedFile;
use crate::DurableLedgerError;

struct TestDirectory(PathBuf);

impl TestDirectory {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(/*v*/ 0);
        let path = std::env::temp_dir().join(format!(
            "hepta-locked-file-qualification-{}-{}",
            std::process::id(),
            NEXT.fetch_add(/*val*/ 1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }

    fn path(&self) -> &Path {
        &self.0
    }
}

impl Drop for TestDirectory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn qualification_reads_observe_equal_length_changes_without_releasing_lock_or_cursor() {
    let directory = TestDirectory::new();
    let path = directory.path().join("owner");
    let mut owner = LockedFile::acquire(
        OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(&path)
            .unwrap(),
    )
    .unwrap();
    owner.write_all(b"first").unwrap();
    owner.seek(SeekFrom::Start(2)).unwrap();
    const LIMIT: u64 = 32;
    let original = owner.qualification_bytes(LIMIT).unwrap();
    assert_eq!(original, b"first");
    assert_eq!(owner.stream_position().unwrap(), 2);

    let contender = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&path)
        .unwrap();
    assert!(matches!(
        contender.try_lock(),
        Err(TryLockError::WouldBlock)
    ));

    owner.seek(SeekFrom::Start(0)).unwrap();
    owner.write_all(b"other").unwrap();
    owner.seek(SeekFrom::Start(2)).unwrap();
    let changed = owner.qualification_bytes(LIMIT).unwrap();
    assert_eq!(changed, b"other");
    assert_ne!(changed, original);
    assert_eq!(owner.stream_position().unwrap(), 2);
    assert!(matches!(
        contender.try_lock(),
        Err(TryLockError::WouldBlock)
    ));
    #[cfg(windows)]
    assert_eq!(std::fs::read(&path).unwrap_err().raw_os_error(), Some(33));
}

#[test]
fn qualification_reads_enforce_bounds_and_restore_cursor_after_read_error() {
    let directory = TestDirectory::new();
    let path = directory.path().join("write-only-owner");
    let mut owner = LockedFile::acquire(
        OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&path)
            .unwrap(),
    )
    .unwrap();
    owner.write_all(b"first").unwrap();
    owner.seek(SeekFrom::Start(2)).unwrap();
    assert_eq!(
        owner.qualification_bytes(/*maximum_bytes*/ 4),
        Err(DurableLedgerError::Capacity)
    );
    assert_eq!(owner.stream_position().unwrap(), 2);
    assert_eq!(
        owner.qualification_bytes(/*maximum_bytes*/ 0),
        Err(DurableLedgerError::InvalidLimit)
    );
    assert_eq!(owner.stream_position().unwrap(), 2);
    assert!(matches!(
        owner.qualification_bytes(/*maximum_bytes*/ 32),
        Err(DurableLedgerError::Io(_))
    ));
    assert_eq!(owner.stream_position().unwrap(), 2);
    let contender = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&path)
        .unwrap();
    assert!(matches!(
        contender.try_lock(),
        Err(TryLockError::WouldBlock)
    ));
}
