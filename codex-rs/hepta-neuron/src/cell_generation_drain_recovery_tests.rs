//! Real generation files at the original Drain durability boundary.

use pretty_assertions::assert_eq;

use super::*;

#[test]
fn original_generation_drain_reopen_and_replay_keep_exact_journal_and_witness() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    let initial = fixture.bytes();
    let initial_witness = checked(fs::read(fixture.0.join("witness")));
    checked(owner.drain());
    assert_eq!(owner.is_drained(), Ok(true));
    let complete = fixture.bytes();
    let witness = checked(fs::read(fixture.0.join("witness")));
    assert_ne!(complete, initial);
    assert_ne!(witness, initial_witness);
    checked(owner.drain());
    assert_eq!(fixture.bytes(), complete);
    assert_eq!(checked(fs::read(fixture.0.join("witness"))), witness);
    drop(owner);
    let mut recovered = fixture.open();
    assert_eq!(recovered.is_drained(), Ok(true));
    checked(recovered.drain());
    assert_eq!(fixture.bytes(), complete);
    assert_eq!(checked(fs::read(fixture.0.join("witness"))), witness);
}

#[test]
fn original_generation_drain_readonly_witness_failure_reopens_the_retained_frame_once() {
    let fixture = Fixture::new();
    drop(fixture.open());
    let initial = fixture.bytes();
    let initial_witness = checked(fs::read(fixture.0.join("witness")));
    let witness = checked(FileAnchorWitnessStore::open(
        checked(std::fs::File::open(fixture.0.join("witness"))),
        JournalScope {
            scope_digest: Digest32::of_bytes(b"scope"),
            objective_digest: Digest32::of_bytes(b"objective"),
        },
        checked(Generation::new(/*value*/ 1)),
        /*max_records*/ 4_096,
    ));
    let mut owner = checked(CellGenerationJournalV2::open(
        fixture.file("journal"),
        witness,
        config(),
        /*max_records*/ 128,
    ));
    // The actual journal write and fsync happen before this readonly witness
    // descriptor refuses the CAS. No synthetic frame or anchor is installed.
    assert_eq!(owner.drain(), Err(CellGenerationErrorV2::CommitUncertain));
    let complete = fixture.bytes();
    assert_ne!(complete, initial);
    assert_eq!(
        checked(fs::read(fixture.0.join("witness"))),
        initial_witness
    );
    assert_eq!(
        owner.is_drained(),
        Err(CellGenerationErrorV2::CommitUncertain)
    );
    assert_eq!(owner.drain(), Err(CellGenerationErrorV2::CommitUncertain));
    assert_eq!(fixture.bytes(), complete);
    drop(owner);
    let mut recovered = fixture.open();
    assert_eq!(recovered.is_drained(), Ok(true));
    assert_eq!(fixture.bytes(), complete);
    let witness = checked(fs::read(fixture.0.join("witness")));
    assert_ne!(witness, initial_witness);
    checked(recovered.drain());
    assert_eq!(fixture.bytes(), complete);
    assert_eq!(checked(fs::read(fixture.0.join("witness"))), witness);
}
