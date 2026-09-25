#![cfg(unix)]

use std::fmt::Debug;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::OpenOptionsExt;

use codex_hepta_types::Digest32;

use super::NEXT_FILE;
use super::PlannerJournalStoreV1;
use super::PlannerStoreError;
use super::STATE_FILE;
use super::STORE_V2_MAGIC;
use super::encode_store_v1_for_test;
use crate::PlannerJournalKindV1;
use crate::PlannerJournalV1;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn must_err<T, E>(result: Result<T, E>) -> E {
    match result {
        Err(error) => error,
        Ok(_) => panic!("expected an error"),
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn selected_journal() -> PlannerJournalV1 {
    let mut journal = PlannerJournalV1::new();
    must(journal.append(
        PlannerJournalKindV1::Decision,
        digest("decision-identity"),
        digest("decision"),
    ));
    must(journal.append(
        PlannerJournalKindV1::SelectedPlan,
        digest("selection-identity"),
        digest("decision"),
    ));
    journal
}

#[test]
fn durable_store_reopens_selected_plan_after_ack_loss() {
    let temporary = must(tempfile::tempdir());
    let root = temporary.path().join("planner");
    let (mut store, initial) = must(PlannerJournalStoreV1::open(&root, &[]));
    assert!(initial.entries().is_empty());

    let journal = selected_journal();
    must(store.persist(&journal));
    // Simulate process exit after commit but before the caller receives an ack.
    drop(store);

    let (_store, reopened) = must(PlannerJournalStoreV1::open(&root, &[]));
    assert_eq!(reopened.entries(), journal.entries());
    assert_eq!(reopened.selected_plan_digest(), Some(digest("decision")));
}

#[test]
fn duplicate_persist_is_idempotent_and_does_not_duplicate_history() {
    let temporary = must(tempfile::tempdir());
    let root = temporary.path().join("planner");
    let (mut store, _initial) = must(PlannerJournalStoreV1::open(&root, &[]));
    let journal = selected_journal();
    must(store.persist(&journal));
    must(store.persist(&journal));
    assert_eq!(store.current().entries(), journal.entries());
}

#[test]
fn torn_next_file_never_replaces_the_last_committed_state() {
    let temporary = must(tempfile::tempdir());
    let root = temporary.path().join("planner");
    let (mut store, _initial) = must(PlannerJournalStoreV1::open(&root, &[]));
    let journal = selected_journal();
    must(store.persist(&journal));
    drop(store);

    let mut torn = must(
        OpenOptions::new()
            .create(true)
            .truncate(true)
            .write(true)
            .mode(0o600)
            .open(root.join(NEXT_FILE)),
    );
    must(torn.write_all(b"torn-uncommitted-successor"));
    must(torn.sync_all());
    drop(torn);

    let (_store, reopened) = must(PlannerJournalStoreV1::open(&root, &[]));
    assert_eq!(reopened.entries(), journal.entries());
}

#[test]
fn v1_reference_envelope_migrates_atomically_to_v2() {
    let temporary = must(tempfile::tempdir());
    let root = temporary.path().join("planner");
    must(std::fs::DirBuilder::new().mode(0o700).create(&root));

    let journal = selected_journal();
    let legacy = must(encode_store_v1_for_test(&journal));
    let state_path = root.join(STATE_FILE);
    let mut state = must(
        OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .open(&state_path),
    );
    must(state.write_all(&legacy));
    must(state.sync_all());
    drop(state);

    let (_store, reopened) = must(PlannerJournalStoreV1::open(&root, &[]));
    assert_eq!(reopened.entries(), journal.entries());
    let migrated = must(std::fs::read(&state_path));
    assert_eq!(&migrated[..STORE_V2_MAGIC.len()], STORE_V2_MAGIC);
}

#[test]
fn restore_of_pre_revocation_backup_fails_current_recovery_floor() {
    let temporary = must(tempfile::tempdir());
    let root = temporary.path().join("planner");
    let (mut store, _initial) = must(PlannerJournalStoreV1::open(&root, &[]));
    let mut journal = selected_journal();
    must(store.persist(&journal));
    let backup = must(std::fs::read(root.join(STATE_FILE)));

    must(journal.revoke(digest("revocation-identity"), digest("decision")));
    must(store.persist(&journal));
    assert_eq!(journal.selected_plan_digest(), None);
    drop(store);

    let state_path = root.join(STATE_FILE);
    let mut restored = must(
        OpenOptions::new()
            .write(true)
            .truncate(true)
            .open(&state_path),
    );
    must(restored.write_all(&backup));
    must(restored.sync_all());
    drop(restored);

    assert_eq!(
        must_err(PlannerJournalStoreV1::open(&root, &[digest("decision")],)),
        PlannerStoreError::RevocationRegression
    );
}

#[test]
fn persist_rejects_history_regression() {
    let temporary = must(tempfile::tempdir());
    let root = temporary.path().join("planner");
    let (mut store, _initial) = must(PlannerJournalStoreV1::open(&root, &[]));
    let journal = selected_journal();
    must(store.persist(&journal));

    assert_eq!(
        must_err(store.persist(&PlannerJournalV1::new())),
        PlannerStoreError::HistoryRegression
    );
}

#[test]
fn corrupt_v1_migration_leaves_predecessor_bytes_unchanged() {
    let temporary = must(tempfile::tempdir());
    let root = temporary.path().join("planner");
    must(std::fs::DirBuilder::new().mode(0o700).create(&root));

    let journal = selected_journal();
    let mut legacy = must(encode_store_v1_for_test(&journal));
    let last = legacy.len() - 1;
    legacy[last] ^= 1;
    let state_path = root.join(STATE_FILE);
    let mut state = must(
        OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .open(&state_path),
    );
    must(state.write_all(&legacy));
    must(state.sync_all());
    drop(state);

    assert_eq!(
        must_err(PlannerJournalStoreV1::open(&root, &[])),
        PlannerStoreError::CorruptState
    );
    assert_eq!(must(std::fs::read(&state_path)), legacy);
}

#[test]
fn indeterminate_publish_fences_writer_until_reopen() {
    let temporary = must(tempfile::tempdir());
    let root = temporary.path().join("planner");
    let (mut store, _initial) = must(PlannerJournalStoreV1::open(&root, &[]));
    let journal = selected_journal();

    assert_eq!(
        must_err(store.persist_with_post_replace_failure_for_test(&journal)),
        PlannerStoreError::RecoveryRequired
    );
    assert_eq!(
        must_err(store.persist(&journal)),
        PlannerStoreError::RecoveryRequired
    );
    drop(store);

    let (_reopened_store, reopened) = must(PlannerJournalStoreV1::open(&root, &[]));
    assert_eq!(reopened.entries(), journal.entries());
    assert_eq!(reopened.selected_plan_digest(), Some(digest("decision")));
}
