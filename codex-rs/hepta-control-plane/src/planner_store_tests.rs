use std::fs;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;

use super::PlannerJournalStoreError;
use super::PlannerJournalStoreV1;
use super::STORE_MAGIC;
use crate::PlannerJournalKindV1;
use crate::PlannerJournalV1;

static TEST_SEQUENCE: AtomicU64 = AtomicU64::new(1);

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn path(name: &str) -> PathBuf {
    let sequence = TEST_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    std::env::temp_dir().join(format!(
        "hepta-control-planner-store-{name}-{}-{sequence}.bin",
        std::process::id()
    ))
}

fn journal(value: &str) -> PlannerJournalV1 {
    let mut journal = PlannerJournalV1::new();
    let digest = digest(value);
    journal
        .append(PlannerJournalKindV1::Snapshot, digest, digest)
        .expect("valid journal entry");
    journal
}

#[test]
fn atomic_commit_reopens_exact_journal() {
    let path = path("reopen");
    let mut store = PlannerJournalStoreV1::create(&path).expect("create store");
    let expected = journal("snapshot-a");
    store.commit(&expected).expect("commit");
    drop(store);

    let reopened = PlannerJournalStoreV1::open(&path).expect("reopen");
    assert_eq!(reopened.journal().entries(), expected.entries());
    let _ = fs::remove_file(path);
}

#[test]
fn raw_v1_journal_migrates_to_versioned_store() {
    let path = path("migration");
    let expected = journal("legacy");
    fs::write(&path, expected.export_bytes()).expect("write legacy journal");

    let reopened = PlannerJournalStoreV1::open(&path).expect("migrate");
    assert_eq!(reopened.journal().entries(), expected.entries());
    assert!(fs::read(&path).expect("read migrated").starts_with(STORE_MAGIC));
    let _ = fs::remove_file(path);
}

#[test]
fn restore_revalidates_semantics_before_replacing_state() {
    let path = path("restore");
    let mut store = PlannerJournalStoreV1::create(&path).expect("create store");
    let restored = journal("restored");
    store
        .restore_journal_bytes(&restored.export_bytes())
        .expect("restore");
    assert_eq!(store.journal().entries(), restored.entries());
    let _ = fs::remove_file(path);
}

#[test]
fn envelope_corruption_fails_closed() {
    let path = path("corrupt");
    let mut store = PlannerJournalStoreV1::create(&path).expect("create store");
    store.commit(&journal("snapshot")).expect("commit");
    drop(store);
    let mut bytes = fs::read(&path).expect("read");
    let last = bytes.len() - 1;
    bytes[last] ^= 1;
    fs::write(&path, bytes).expect("tamper");

    assert_eq!(
        PlannerJournalStoreV1::open(&path).expect_err("corruption must reject"),
        PlannerJournalStoreError::CorruptEnvelope
    );
    let _ = fs::remove_file(path);
}
