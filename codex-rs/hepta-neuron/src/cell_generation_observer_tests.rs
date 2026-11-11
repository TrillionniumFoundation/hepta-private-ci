//! Physical observer tests use the existing journal-port fixture. The Current
//! double here is not Root custody, an ordinary task or a publication grant.

use super::*;
use crate::CellGenerationJournalObserverV1;
use crate::CellGenerationObserverConfigV1;
use pretty_assertions::assert_eq;
use std::io::Write;

fn observer_config() -> CellGenerationObserverConfigV1 {
    CellGenerationObserverConfigV1 {
        generation: config(),
        journal_records: 128,
        witness_scope: JournalScope {
            scope_digest: Digest32::of_bytes(b"guarded-scope"),
            objective_digest: Digest32::of_bytes(b"guarded-task"),
        },
        witness_generation: Generation::new(1).unwrap(),
        witness_records: 128,
    }
}

fn observer(files: &Files) -> CellGenerationJournalObserverV1 {
    CellGenerationJournalObserverV1::from_original_files(
        File::open(files.0.join("journal")).unwrap(),
        File::open(files.0.join("witness")).unwrap(),
        observer_config(),
    )
    .unwrap()
}

fn owner(files: &Files) -> CellGenerationJournalV2<FileAnchorWitnessStore> {
    let config = config();
    let binding = CellGenerationOwnerBindingV1::new(&config, /*max_records*/ 128).unwrap();
    CellGenerationJournalV2::open_guarded(
        files.file("journal"),
        files.witness(),
        config,
        /*max_records*/ 128,
        Arc::new(Current(Mutex::new((Some(binding), None)))),
    )
    .unwrap()
}

#[test]
fn observer_reads_exact_live_owner_and_keeps_both_writer_fences() {
    let files = Files::new();
    let mut owner = owner(&files);
    let reader = observer(&files);
    assert!(files.file("journal").try_lock().is_err());
    assert!(files.file("witness").try_lock().is_err());
    let first = reader.observe().unwrap();
    assert!(first.is_genesis());
    assert_eq!(first.observation(), &owner.observe_generation().unwrap());
    let held = reader.files_binding();
    owner.drain().unwrap();
    let before = (files.bytes(), fs::read(files.0.join("witness")).unwrap());
    let after = reader.observe().unwrap();
    assert!(after.is_drained());
    assert!(!after.is_genesis());
    assert_eq!(after.observation(), &owner.observe_generation().unwrap());
    assert_eq!(reader.files_binding(), held);
    assert_eq!(
        (files.bytes(), fs::read(files.0.join("witness")).unwrap()),
        before
    );
}

#[test]
fn observer_refuses_partial_suffix_until_the_actual_writer_recovers() {
    let files = Files::new();
    let mut owner = owner(&files);
    let reader = observer(&files);
    let original = reader.observe().unwrap();
    let mut extra = OpenOptions::new()
        .append(true)
        .open(files.0.join("journal"))
        .unwrap();
    extra.write_all(&[0, 0]).unwrap();
    extra.sync_all().unwrap();
    let partial = files.bytes();
    assert_eq!(reader.observe().err(), Some(CellGenerationErrorV2::Pending));
    assert_eq!(files.bytes(), partial);
    owner.recover().unwrap();
    assert_eq!(reader.observe().unwrap(), original);
}

#[test]
fn observer_rejects_acknowledged_journal_or_physical_witness_rollback() {
    let files = Files::new();
    let mut owner = owner(&files);
    let empty_journal = files.bytes();
    let empty_witness = fs::read(files.0.join("witness")).unwrap();
    let reader = observer(&files);
    owner.drain().unwrap();
    let journal = files.bytes();
    let witness = fs::read(files.0.join("witness")).unwrap();
    fs::write(files.0.join("journal"), &empty_journal).unwrap();
    assert_eq!(
        reader.observe().err(),
        Some(CellGenerationErrorV2::AcknowledgedHistoryMissing)
    );
    assert_eq!(files.bytes(), empty_journal);
    fs::write(files.0.join("journal"), &journal).unwrap();
    fs::write(files.0.join("witness"), &empty_witness).unwrap();
    assert_eq!(
        reader.observe().err(),
        Some(CellGenerationErrorV2::AcknowledgedHistoryMissing)
    );
    assert_eq!(fs::read(files.0.join("witness")).unwrap(), empty_witness);
    fs::write(files.0.join("witness"), &witness).unwrap();
    assert!(reader.observe().unwrap().is_drained());
    fs::remove_file(files.0.join("journal")).unwrap();
    assert_eq!(
        reader.observe().err(),
        Some(CellGenerationErrorV2::InvalidBinding)
    );
}

#[test]
fn unwritten_target_is_not_reported_as_actual_genesis_and_wrong_context_is_refused() {
    let files = Files::new();
    let journal = files.file("journal");
    let witness = files.witness();
    let reader = observer(&files);
    assert!(reader.require_original_unwritten().is_ok());
    assert!(reader.require_original_unwritten_or_genesis().is_ok());
    assert_eq!(reader.observe().err(), Some(CellGenerationErrorV2::Corrupt));
    let config = config();
    let binding = CellGenerationOwnerBindingV1::new(&config, /*max_records*/ 128).unwrap();
    let _owner = CellGenerationJournalV2::open_guarded(
        journal,
        witness,
        config,
        /*max_records*/ 128,
        Arc::new(Current(Mutex::new((None, Some(binding))))),
    )
    .unwrap();
    assert!(reader.observe().unwrap().is_genesis());
    assert_eq!(reader.require_original_unwritten().err(), Some(CellGenerationErrorV2::Pending));
    assert!(reader.require_original_unwritten_or_genesis().is_ok());
    let mut wrong = observer_config();
    wrong.generation.task_digest = [97; 32];
    let wrong = CellGenerationJournalObserverV1::from_original_files(
        files.file("journal"),
        files.file("witness"),
        wrong,
    )
    .unwrap();
    assert_eq!(
        wrong.observe().err(),
        Some(CellGenerationErrorV2::InvalidBinding)
    );
    assert!(
        CellGenerationJournalObserverV1::from_original_files(
            files.file("journal"),
            files.file("journal"),
            observer_config(),
        )
        .is_err()
    );
}

#[test]
fn fresh_initial_observer_refuses_uninitialized_witness_and_existing_genesis() {
    let files = Files::new();
    let _journal = files.file("journal");
    let _uninitialized = files.file("witness");
    let reader = observer(&files);
    assert_eq!(reader.require_original_unwritten().err(), Some(CellGenerationErrorV2::Unavailable));
    let witness = files.witness();
    reader.require_original_unwritten().unwrap();
    drop(witness);
    let original_owner = owner(&files);
    let original = reader.observe().unwrap();
    assert!(original.is_genesis());
    drop(original_owner);
    assert_eq!(reader.require_original_unwritten().err(), Some(CellGenerationErrorV2::Pending));
    // A header cannot be called a fresh absent target, even with empty witness.
    assert_eq!(reader.observe().unwrap(), original);
}
