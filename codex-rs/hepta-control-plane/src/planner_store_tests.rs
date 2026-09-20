use std::fs;
use std::fs::File;
use std::io::Write;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_types::Digest32;

use super::PlannerDurableStoreV1;
use super::PlannerStoreError;
use super::generation_path;
use crate::PlannerJournalKindV1;
use crate::PlannerJournalV1;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn temp_directory(name: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_nanos();
    let path = std::env::temp_dir().join(format!(
        "hepta-control-planner-{name}-{}-{nonce}",
        std::process::id()
    ));
    fs::create_dir(&path).expect("create temp directory");
    path
}

fn selected_journal() -> (PlannerJournalV1, Digest32) {
    let decision = digest("decision");
    let mut journal = PlannerJournalV1::new();
    journal
        .append(PlannerJournalKindV1::Decision, decision, decision)
        .expect("decision");
    journal
        .append(
            PlannerJournalKindV1::SelectedPlan,
            digest("select"),
            decision,
        )
        .expect("selection");
    (journal, decision)
}

#[test]
fn durable_generations_reopen_and_reject_local_rollback() {
    let directory = temp_directory("round-trip");
    let (journal, decision) = selected_journal();

    {
        let mut store =
            PlannerDurableStoreV1::open(&directory, "planner").expect("open empty store");
        store.persist(&journal).expect("persist selection");
        assert_eq!(store.current_generation(), 1);
        assert_eq!(store.journal().selected_plan_digest(), Some(decision));
    }

    {
        let mut store =
            PlannerDurableStoreV1::open(&directory, "planner").expect("reopen selection");
        assert_eq!(store.journal().selected_plan_digest(), Some(decision));

        let empty = PlannerJournalV1::new();
        assert_eq!(
            store.persist(&empty).expect_err("rollback must reject"),
            PlannerStoreError::NonMonotonicReplace
        );

        let mut revoked = store.journal().clone();
        revoked
            .append(
                PlannerJournalKindV1::Revocation,
                digest("revoke"),
                decision,
            )
            .expect("revocation");
        store.persist(&revoked).expect("persist revocation");
        assert_eq!(store.current_generation(), 2);
    }

    {
        let store =
            PlannerDurableStoreV1::open(&directory, "planner").expect("reopen revocation");
        assert_eq!(store.journal().selected_plan_digest(), None);
    }

    fs::remove_dir_all(directory).expect("remove temp directory");
}

#[test]
fn corrupt_successor_generation_requires_recovery() {
    let directory = temp_directory("corrupt");
    let (journal, _) = selected_journal();
    {
        let mut store =
            PlannerDurableStoreV1::open(&directory, "planner").expect("open empty store");
        store.persist(&journal).expect("persist first generation");
    }

    let corrupt = generation_path(&directory, "planner", 2);
    let mut file = File::create(corrupt).expect("create corrupt generation");
    file.write_all(b"incomplete").expect("write corrupt generation");
    file.sync_all().expect("sync corrupt generation");

    assert!(matches!(
        PlannerDurableStoreV1::open(&directory, "planner"),
        Err(PlannerStoreError::RecoveryRequired)
    ));
    fs::remove_dir_all(directory).expect("remove temp directory");
}

#[test]
fn live_or_stale_writer_lock_fails_closed() {
    let directory = temp_directory("lock");
    fs::write(directory.join(".planner.lock"), b"stale").expect("write stale lock");
    assert!(matches!(
        PlannerDurableStoreV1::open(&directory, "planner"),
        Err(PlannerStoreError::Locked)
    ));
    fs::remove_dir_all(directory).expect("remove temp directory");
}
