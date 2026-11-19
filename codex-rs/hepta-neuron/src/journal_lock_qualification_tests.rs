use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

use super::LockedFile;
use super::QualificationFileReadError;
use super::qualification_file_bytes;
use crate::AnchorWitnessStore;
use crate::FileAnchorWitnessStore;
use crate::JournalScope;
use crate::WitnessStoreError;

static NEXT: AtomicU64 = AtomicU64::new(0);

fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("owned-file fixture: {error:?}"),
    }
}

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "hepta-neuron-owned-file-{}-{serial}",
            std::process::id()
        ));
        checked(OpenOptions::new().write(true).create_new(true).open(&path));
        Self(path)
    }

    fn read_write(&self) -> File {
        checked(OpenOptions::new().read(true).write(true).open(&self.0))
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

#[test]
fn qualification_reads_physical_same_length_changes_without_releasing_lock_or_cursor() {
    let fixture = Fixture::new();
    let mut owner = checked(LockedFile::acquire(fixture.read_write()));
    checked(owner.write_all(b"before"));
    checked(owner.seek(SeekFrom::Start(2)));
    assert_eq!(
        checked(qualification_file_bytes(&mut owner, /*max_bytes*/ 64)),
        b"before"
    );
    assert_eq!(checked(owner.stream_position()), 2);
    checked(owner.rewind());
    checked(owner.write_all(b"after!"));
    checked(owner.seek(SeekFrom::Start(3)));
    assert_eq!(
        checked(qualification_file_bytes(&mut owner, /*max_bytes*/ 64)),
        b"after!"
    );
    assert_eq!(checked(owner.stream_position()), 3);
    let contender = fixture.read_write();
    assert!(matches!(
        contender.try_lock(),
        Err(TryLockError::WouldBlock)
    ));
    drop(owner);
    checked(contender.try_lock());
}

#[test]
fn qualification_bounds_and_read_errors_never_hide_cursor_changes() {
    let fixture = Fixture::new();
    checked(fixture.read_write().write_all(b"before"));
    let file = checked(OpenOptions::new().write(true).open(&fixture.0));
    let mut owner = checked(LockedFile::acquire(file));
    checked(owner.seek(SeekFrom::Start(2)));
    assert!(matches!(
        qualification_file_bytes(&mut owner, /*max_bytes*/ 4),
        Err(QualificationFileReadError::Capacity)
    ));
    assert!(matches!(
        qualification_file_bytes(&mut owner, /*max_bytes*/ 0),
        Err(QualificationFileReadError::InvalidLimit)
    ));
    assert!(matches!(
        qualification_file_bytes(&mut owner, /*max_bytes*/ 64),
        Err(QualificationFileReadError::Io(_))
    ));
    assert_eq!(checked(owner.stream_position()), 2);
}

#[test]
fn qualification_witness_read_failure_keeps_the_owner_poisoned() {
    let fixture = Fixture::new();
    let file = checked(OpenOptions::new().write(true).open(&fixture.0));
    let mut witness = checked(FileAnchorWitnessStore::open(
        file,
        JournalScope {
            scope_digest: Digest32::of_bytes(b"owned-file-scope"),
            objective_digest: Digest32::of_bytes(b"owned-file-objective"),
        },
        checked(Generation::new(1)),
        /*max_records*/ 4,
    ));
    assert!(matches!(
        witness.qualification_file_bytes(/*max_bytes*/ 1024),
        Err(WitnessStoreError::Io(_))
    ));
    assert_eq!(witness.current(), Err(WitnessStoreError::Poisoned));
    assert_eq!(
        witness.qualification_file_bytes(/*max_bytes*/ 1024),
        Err(WitnessStoreError::Poisoned)
    );
}
