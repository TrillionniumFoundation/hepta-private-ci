#![cfg(unix)]

use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::OpenOptionsExt;

use codex_hepta_types::Digest32;

use super::PlannerJournalStoreV1;
use super::PlannerStoreError;
use super::STATE_FILE;
use super::STORE_V2_MAGIC;
use super::encode_store_v1_for_test;
use crate::PlannerJournalKindV1;
use crate::PlannerJournalV1;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn selected_journal() -> PlannerJournalV1 {
    let mut journal = PlannerJournalV1::new();
    journal
        .append(
            PlannerJournalKindV1::Decision,
            digest("decision-identity"),
            digest("decision"),
        )
        .expect("record decision");
    journal
        .append(
            PlannerJournalKindV1::SelectedPlan,
            digest("selection-identity"),
            digest("decision"),
        )
        .expect("select recorded decision");
    journal
}

#[test]
fn durable_store_fsync_reopens_selected_plan() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let root = temporary.path().join("planner");

    let (mut store, mut journal) =
        PlannerJournalStoreV1::open(&root, &[]).expect("open initial store");
    assert!(journal.entries().is_empty());

    journal = selected_journal();
    store.persist(&journal).expect("persist selected journal");
    drop(store);

    let (_store, reopened) = PlannerJournalStoreV1::open(&root, &[]).expect("reopen durable store");
    assert_eq!(reopened.entries(), journal.entries());
    assert_eq!(reopened.selected_plan_digest(), Some(digest("decision")));
}

#[test]
fn v1_reference_envelope_migrates_atomically_to_v2() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let root = temporary.path().join("planner");
    std::fs::DirBuilder::new()
        .mode(0o700)
        .create(&root)
        .expect("create owner directory");

    let journal = selected_journal();
    let legacy = encode_store_v1_for_test(&journal).expect("encode v1");
    let state_path = root.join(STATE_FILE);
    let mut state = OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(&state_path)
        .expect("create legacy state");
    state.write_all(&legacy).expect("write legacy state");
    state.sync_all().expect("sync legacy state");
    drop(state);

    let (_store, reopened) = PlannerJournalStoreV1::open(&root, &[]).expect("migrate v1 store");
    assert_eq!(reopened.entries(), journal.entries());
    let migrated = std::fs::read(&state_path).expect("read migrated state");
    assert_eq!(&migrated[..STORE_V2_MAGIC.len()], STORE_V2_MAGIC);
}

#[test]
fn restore_of_pre_revocation_backup_fails_current_recovery_floor() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let root = temporary.path().join("planner");

    let (mut store, _initial) = PlannerJournalStoreV1::open(&root, &[]).expect("open store");
    let mut journal = selected_journal();
    store.persist(&journal).expect("persist selected state");
    let backup = std::fs::read(root.join(STATE_FILE)).expect("capture backup");

    journal
        .revoke(digest("revocation-identity"), digest("decision"))
        .expect("revoke selected decision");
    store.persist(&journal).expect("persist revocation");
    assert_eq!(journal.selected_plan_digest(), None);
    drop(store);

    let state_path = root.join(STATE_FILE);
    let mut restored = OpenOptions::new()
        .write(true)
        .truncate(true)
        .open(&state_path)
        .expect("open restored state");
    restored.write_all(&backup).expect("restore old backup");
    restored.sync_all().expect("sync restored backup");
    drop(restored);

    assert_eq!(
        PlannerJournalStoreV1::open(&root, &[digest("decision")])
            .expect_err("current revocation floor must reject predecessor backup"),
        PlannerStoreError::RevocationRegression
    );
}

#[test]
fn persist_rejects_history_regression() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let root = temporary.path().join("planner");

    let (mut store, _initial) = PlannerJournalStoreV1::open(&root, &[]).expect("open store");
    let journal = selected_journal();
    store.persist(&journal).expect("persist selected state");

    assert_eq!(
        store
            .persist(&PlannerJournalV1::new())
            .expect_err("durable store must reject rollback to shorter history"),
        PlannerStoreError::HistoryRegression
    );
}

#[test]
fn corrupt_v1_migration_leaves_predecessor_bytes_unchanged() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let root = temporary.path().join("planner");
    std::fs::DirBuilder::new()
        .mode(0o700)
        .create(&root)
        .expect("create owner directory");

    let journal = selected_journal();
    let mut legacy = encode_store_v1_for_test(&journal).expect("encode v1");
    let last = legacy.len() - 1;
    legacy[last] ^= 1;
    let state_path = root.join(STATE_FILE);
    let mut state = OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(&state_path)
        .expect("create corrupt legacy state");
    state
        .write_all(&legacy)
        .expect("write corrupt legacy state");
    state.sync_all().expect("sync corrupt legacy state");
    drop(state);

    assert_eq!(
        PlannerJournalStoreV1::open(&root, &[]).expect_err("corrupt migration must fail closed"),
        PlannerStoreError::CorruptState
    );
    assert_eq!(
        std::fs::read(&state_path).expect("read predecessor"),
        legacy,
        "failed migration must not rewrite predecessor bytes"
    );
}
