use codex_hepta_types::Digest32;

use super::BACKUP_FILE;
use super::CURRENT_FILE;
use super::FRONTIER_FILE;
use super::PlannerJournalStoreV1;
use super::PlannerStoreError;
use super::encode_store;
use crate::PlannerJournalKindV1;
use crate::PlannerJournalV1;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn decision_journal() -> PlannerJournalV1 {
    let mut journal = PlannerJournalV1::new();
    journal
        .append(
            PlannerJournalKindV1::Decision,
            digest("decision-identity"),
            digest("decision"),
        )
        .expect("record decision");
    journal
}

#[test]
fn durable_store_reopens_exact_committed_journal() {
    let directory = tempfile::tempdir().expect("tempdir");
    let (store, empty) = PlannerJournalStoreV1::open(directory.path()).expect("open store");
    assert!(empty.entries().is_empty());

    let mut journal = decision_journal();
    journal
        .append(
            PlannerJournalKindV1::SelectedPlan,
            digest("selection"),
            digest("decision"),
        )
        .expect("select recorded decision");
    store.commit(&journal).expect("commit");
    let reopened = store.reopen().expect("reopen");
    assert_eq!(reopened.entries(), journal.entries());

    let (_, reopened_from_root) =
        PlannerJournalStoreV1::open(directory.path()).expect("reopen root");
    assert_eq!(reopened_from_root.entries(), journal.entries());
}

#[test]
fn frontier_rolls_back_only_an_uncommitted_current_replacement() {
    let directory = tempfile::tempdir().expect("tempdir");
    let (store, _) = PlannerJournalStoreV1::open(directory.path()).expect("open store");
    let journal = decision_journal();
    store.commit(&journal).expect("commit decision");

    let committed_bytes =
        std::fs::read(directory.path().join(CURRENT_FILE)).expect("read committed current");
    std::fs::write(directory.path().join(BACKUP_FILE), &committed_bytes)
        .expect("stage matching backup");

    let mut uncommitted = journal.clone();
    uncommitted
        .append(
            PlannerJournalKindV1::SelectedPlan,
            digest("selection"),
            digest("decision"),
        )
        .expect("select");
    std::fs::write(
        directory.path().join(CURRENT_FILE),
        encode_store(&uncommitted).expect("encode uncommitted"),
    )
    .expect("simulate crash after current replacement");

    let (_, recovered) =
        PlannerJournalStoreV1::open(directory.path()).expect("recover old frontier");
    assert_eq!(recovered.entries(), journal.entries());
}

#[test]
fn committed_revocation_cannot_be_resurrected_from_older_backup() {
    let directory = tempfile::tempdir().expect("tempdir");
    let (store, _) = PlannerJournalStoreV1::open(directory.path()).expect("open store");
    let mut selected = decision_journal();
    selected
        .append(
            PlannerJournalKindV1::SelectedPlan,
            digest("selection"),
            digest("decision"),
        )
        .expect("select");
    store.commit(&selected).expect("commit selected");

    let mut revoked = selected.clone();
    revoked
        .append(
            PlannerJournalKindV1::Revocation,
            digest("revocation"),
            digest("decision"),
        )
        .expect("revoke");
    store.commit(&revoked).expect("commit revocation");
    assert_eq!(store.reopen().expect("reopen").selected_plan_digest(), None);

    std::fs::write(directory.path().join(CURRENT_FILE), b"corrupt")
        .expect("corrupt current");
    assert_eq!(
        PlannerJournalStoreV1::open(directory.path())
            .expect_err("older backup must not cross committed frontier"),
        PlannerStoreError::FrontierMismatch
    );
}

#[test]
fn missing_frontier_never_reseeds_a_new_format_store() {
    let directory = tempfile::tempdir().expect("tempdir");
    let (store, _) = PlannerJournalStoreV1::open(directory.path()).expect("open store");
    let journal = decision_journal();
    store.commit(&journal).expect("commit");
    std::fs::remove_file(directory.path().join(FRONTIER_FILE)).expect("remove frontier");

    assert_eq!(
        PlannerJournalStoreV1::open(directory.path())
            .expect_err("new store without frontier must fail closed"),
        PlannerStoreError::FrontierMismatch
    );
}

#[test]
fn raw_v1_journal_migrates_to_store_envelope_and_frontier() {
    let directory = tempfile::tempdir().expect("tempdir");
    let journal = decision_journal();
    std::fs::write(directory.path().join(CURRENT_FILE), journal.export_bytes())
        .expect("write legacy raw journal");

    let (store, migrated) =
        PlannerJournalStoreV1::open(directory.path()).expect("migrate legacy journal");
    assert_eq!(migrated.entries(), journal.entries());
    assert!(directory.path().join(FRONTIER_FILE).is_file());
    assert_eq!(store.reopen().expect("reopen migrated").entries(), journal.entries());
}
