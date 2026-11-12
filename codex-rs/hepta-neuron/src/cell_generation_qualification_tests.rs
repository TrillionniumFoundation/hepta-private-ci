use std::fs;
use std::fs::OpenOptions;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use pretty_assertions::assert_eq;

use super::support::*;
use crate::AnchorWitnessStore;
use crate::CellGenerationErrorV2;
use crate::CellGenerationJournalV2;
use crate::FileAnchorWitnessStore;
use crate::JournalAnchor;
use crate::JournalError;
use crate::WitnessStoreError;
use crate::cell_test_support::checked;
use crate::journal_lock::LockedFile;
use crate::qualification_file::FileBytesError;
use crate::qualification_file::MAXIMUM_BYTES;
use crate::qualification_file::file_bytes;

#[test]
fn qualification_bytes_match_both_original_files_without_releasing_either_lock() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    let req = request(&owner, "qualification-bytes");
    checked(owner.admit(req.clone(), /*now_micros*/ 11));
    checked(owner.commit(proposal(&req), /*now_micros*/ 20));
    checked(owner.file.seek(SeekFrom::Start(7)));
    let bytes = checked(owner.qualification_file_bytes(MAXIMUM_BYTES));
    assert_eq!(checked(owner.file.stream_position()), 7);
    assert_eq!(
        owner.qualification_file_bytes(MAXIMUM_BYTES),
        Ok(bytes.clone())
    );
    assert!(matches!(
        LockedFile::acquire(fixture.file("journal")),
        Err(JournalError::Busy)
    ));
    assert!(matches!(
        LockedFile::acquire(fixture.file("witness")),
        Err(JournalError::Busy)
    ));
    drop(owner);
    assert_eq!(
        ["journal", "witness"].map(|name| checked(fs::read(fixture.0.join(name)))),
        bytes
    );
}

#[test]
fn qualification_byte_bounds_leave_the_same_owner_and_cursor_usable() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    checked(owner.file.seek(SeekFrom::Start(5)));
    let bytes = checked(owner.qualification_file_bytes(MAXIMUM_BYTES));
    for maximum_bytes in [0, 1, MAXIMUM_BYTES + 1] {
        assert_eq!(
            owner.qualification_file_bytes(maximum_bytes),
            Err(CellGenerationErrorV2::Capacity)
        );
        assert_eq!(checked(owner.file.stream_position()), 5);
    }
    assert_eq!(owner.qualification_file_bytes(MAXIMUM_BYTES), Ok(bytes));
    assert_eq!(owner.pending_request(), Ok(None));
}

struct UnavailableObservation(FileAnchorWitnessStore);

impl AnchorWitnessStore for UnavailableObservation {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.0.current()
    }

    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        self.0.compare_and_swap(expected, next)
    }
}

#[test]
fn unsupported_witness_observation_returns_unavailable_without_cached_bytes() {
    let fixture = Fixture::new();
    let mut owner = checked(CellGenerationJournalV2::open(
        fixture.file("journal"),
        UnavailableObservation(fixture.witness()),
        config(),
        /*max_records*/ 128,
    ));
    checked(owner.file.seek(SeekFrom::Start(3)));
    let journal = owner.locked_bytes_for_test();
    let witness = checked(owner.witness.0.qualification_file_bytes(MAXIMUM_BYTES));
    assert_eq!(
        owner.qualification_file_bytes(MAXIMUM_BYTES),
        Err(CellGenerationErrorV2::Unavailable)
    );
    assert_eq!(checked(owner.file.stream_position()), 3);
    assert_eq!(owner.locked_bytes_for_test(), journal);
    assert_eq!(
        owner.witness.0.qualification_file_bytes(MAXIMUM_BYTES),
        Ok(witness)
    );
}

#[test]
fn failed_read_restores_the_original_cursor_and_keeps_contenders_excluded() {
    let fixture = Fixture::new();
    let mut created = fixture.file("read-error");
    checked(created.write_all(b"original locked file"));
    drop(created);
    let file = checked(
        OpenOptions::new()
            .write(true)
            .open(fixture.0.join("read-error")),
    );
    let mut locked = checked(LockedFile::acquire(file));
    checked(locked.seek(SeekFrom::Start(4)));
    assert!(matches!(
        file_bytes(&mut locked, MAXIMUM_BYTES),
        Err(FileBytesError::Io(_))
    ));
    assert_eq!(checked(locked.stream_position()), 4);
    assert!(matches!(
        LockedFile::acquire(fixture.file("read-error")),
        Err(JournalError::Busy)
    ));
    drop(locked);
    assert_eq!(
        checked(fs::read(fixture.0.join("read-error"))),
        b"original locked file"
    );
}
