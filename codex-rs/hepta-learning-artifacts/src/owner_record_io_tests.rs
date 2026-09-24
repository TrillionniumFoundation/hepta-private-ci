//! Exercise complete owner writes and exact retries with independent sync cuts.
use super::*;
use crate::owner_host::tests::TestDir;
use crate::test_support::FixtureError;
use crate::test_support::FixtureValue;
use std::cell::RefCell;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum SyncCut {
    File,
    Directory,
}

fn sync_cut(file: &File) -> SyncCut {
    if file.metadata().fixture("sync descriptor metadata").is_dir() {
        SyncCut::Directory
    } else {
        SyncCut::File
    }
}

fn interrupted_acknowledgement(cut: SyncCut) {
    let directory = TestDir::new();
    let path = directory.0.join("selected-version.record");
    let bytes = b"complete immutable recovery record";
    let calls = RefCell::new(Vec::new());
    let fail = |file: &File| {
        let stage = sync_cut(file);
        calls.borrow_mut().push(stage);
        if stage == cut {
            Err(std::io::Error::other("injected sync acknowledgement loss"))
        } else {
            file.sync_all()
        }
    };
    for _ in 0..2 {
        calls.borrow_mut().clear();
        let error = write_bounded_with_sync(&path, bytes, MAX_SMALL_RECORD_BYTES, &fail)
            .fixture_error("uncertain initial write and exact retry must not acknowledge");
        assert!(matches!(error, ArtifactOwnerHostError::Indeterminate));
        assert_eq!(fs::read(&path).fixture("read intact bytes"), bytes);
        let expected = match cut {
            SyncCut::File => vec![SyncCut::File],
            SyncCut::Directory => vec![SyncCut::File, SyncCut::Directory],
        };
        assert_eq!(*calls.borrow(), expected);
    }
    calls.borrow_mut().clear();
    write_bounded_with_sync(&path, bytes, MAX_SMALL_RECORD_BYTES, &|file| {
        calls.borrow_mut().push(sync_cut(file));
        file.sync_all()
    })
    .fixture("retry re-establishes both actual durability barriers");
    assert_eq!(*calls.borrow(), vec![SyncCut::File, SyncCut::Directory]);
    assert_eq!(
        read_small_record(&path, MAX_SMALL_RECORD_BYTES).fixture("reopen"),
        bytes
    );
}

#[test]
fn exact_retry_reestablishes_failed_file_sync() {
    interrupted_acknowledgement(SyncCut::File);
}

#[test]
fn exact_retry_reestablishes_failed_directory_sync() {
    interrupted_acknowledgement(SyncCut::Directory);
}

#[test]
fn conflicting_or_partial_records_are_never_replaced_on_retry() {
    let directory = TestDir::new();
    let path = directory.0.join("immutable.record");
    let previous = b"part";
    fs::write(&path, previous).fixture("create uncertain prefix");
    let error = write_bounded_with_sync(
        &path,
        b"partially written record",
        MAX_SMALL_RECORD_BYTES,
        &|_| panic!("conflicting bytes cannot reach a success barrier"),
    )
    .fixture_error("partial record must remain a conflict");
    assert!(matches!(error, ArtifactOwnerHostError::IdentityConflict));
    assert_eq!(
        fs::read(&path).fixture("existing prefix retained"),
        previous
    );
}

#[test]
fn over_capacity_rejects_before_creation_or_existing_file_change() {
    let directory = TestDir::new();
    let path = directory.0.join("bounded.record");
    let reject = || {
        write_bounded_with_sync(&path, b"oversize", /*limit*/ 3, &|_| {
            panic!("oversized record cannot reach a success barrier")
        })
        .fixture_error("record capacity")
    };
    assert!(matches!(reject(), ArtifactOwnerHostError::Capacity));
    assert!(!path.exists());
    fs::write(&path, b"old").fixture("old record");
    assert!(matches!(reject(), ArtifactOwnerHostError::Capacity));
    assert_eq!(fs::read(&path).fixture("old bytes"), b"old");
}

#[cfg(unix)]
#[test]
fn exact_retry_flushes_without_replacing_the_file() {
    use std::os::unix::fs::MetadataExt;
    let directory = TestDir::new();
    let path = directory.0.join("stable.record");
    write_create_only_or_exact(&path, b"stable").fixture("initial durable record");
    let before = fs::metadata(&path).fixture("initial metadata");
    write_create_only_or_exact(&path, b"stable").fixture("exact durable retry");
    let after = fs::metadata(&path).fixture("retry metadata");
    assert_eq!(
        (after.dev(), after.ino(), after.len()),
        (before.dev(), before.ino(), before.len())
    );
}
