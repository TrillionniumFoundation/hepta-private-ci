use super::*;
use crate::*;
use crate::cell_test_support::*;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;
use std::fs;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

static NEXT: AtomicU64 = AtomicU64::new(0);

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!("hepta-cell-journal-{}-{serial}", std::process::id()));
        checked(fs::create_dir(&root));
        Self(root)
    }

    fn file(&self, name: &str) -> File {
        checked(OpenOptions::new().read(true).write(true).create(true).truncate(false).open(self.0.join(name)))
    }

    fn witness(&self) -> FileAnchorWitnessStore {
        checked(FileAnchorWitnessStore::open(
            self.file("witness"),
            JournalScope {
                scope_digest: d("cell-owner-journal"),
                objective_digest: d("journal-owner"),
            },
            checked(Generation::new(1)),
            /*max_records*/64,
        ))
    }

    fn open(&self) -> CellOwnerJournalV1<FileAnchorWitnessStore> {
        checked(CellOwnerJournalV1::open(
            self.file("journal"), self.witness(), specs(), /*max_records*/64,
        ))
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn specs() -> Vec<CellJournalPartitionV1> {
    ["run1", "run2"].iter().map(|run| CellJournalPartitionV1 {
        scope: scope(run),
        definition: definition(),
        source_frontier: d("frontier"),
        writer_epoch: 1,
    }).collect()
}

#[test]
fn shared_file_recovers_independent_checkpoints_and_exact_policy_receipts() {
    let fixture = Fixture::new();
    let mut journal = fixture.open();
    let a = proposal(&journal, input("run1"));
    let b = proposal(&journal, input("run2"));
    let first = checked(commit_cell_step(&mut journal, a, /*now_micros*/13));
    let second = checked(commit_cell_step(&mut journal, b, /*now_micros*/14));
    let snapshots = [
        checked(journal.snapshot(&scope("run1"))),
        checked(journal.snapshot(&scope("run2"))),
    ];
    drop(journal);
    let reopened = fixture.open();
    assert_eq!([
        checked(reopened.snapshot(&scope("run1"))),
        checked(reopened.snapshot(&scope("run2"))),
    ], snapshots);
    for receipt in [first, second] {
        assert_eq!(checked(reopened.reconcile(
            &receipt.scope, &receipt.operation_id, receipt.operation_digest,
        )), Some(receipt.clone()));
        assert_eq!(checked(reopened.lookup(
            &receipt.scope, &receipt.operation_id, receipt.semantic_request_digest,
        )), Some(receipt));
    }
    assert!(matches!(checked(enter_cell_step(
        &definition(), &reopened, &Encoder, input("run1"), /*now_micros*/500,
    )), CellStepEntryV1::Replayed(_)));
}

struct FailOnce<W> {
    inner: W,
    fail: Arc<AtomicBool>,
}

impl<W: AnchorWitnessStore> AnchorWitnessStore for FailOnce<W> {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.inner.current()
    }

    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        if self.fail.swap(false, Ordering::SeqCst) {
            return Err(WitnessStoreError::Unavailable);
        }
        self.inner.compare_and_swap(expected, next)
    }
}

#[test]
fn lost_witness_ack_fences_new_work_until_original_log_is_read_back() {
    let fixture = Fixture::new();
    let fail = Arc::new(AtomicBool::new(false));
    let witness = FailOnce { inner: fixture.witness(), fail: Arc::clone(&fail) };
    let mut journal = checked(CellOwnerJournalV1::open(
        fixture.file("journal"), witness, specs(), /*max_records*/64,
    ));
    let proposed = proposal(&journal, input("run1"));
    let expected = proposed.receipt().clone();
    fail.store(true, Ordering::SeqCst);
    assert_eq!(commit_cell_step(&mut journal, proposed, /*now_micros*/13), Err(CellExecutionError::CommitUncertain));
    assert!(matches!(prepare_cell_step(
        &definition(), &journal, &Encoder, input("run1"), /*now_micros*/14,
    ), Err(CellExecutionError::CommitUncertain)));
    assert_eq!(journal.reconcile(
        &expected.scope, &expected.operation_id, expected.operation_digest,
    ), Err(CellExecutionError::CommitUncertain));
    checked(journal.recover());
    assert_eq!(checked(journal.lookup(
        &expected.scope, &expected.operation_id, expected.semantic_request_digest,
    )), Some(expected.clone()));
    match checked(enter_cell_step(&definition(), &journal, &Encoder, input("run1"), /*now_micros*/15)) {
        CellStepEntryV1::Replayed(receipt) => assert_eq!(receipt, expected),
        CellStepEntryV1::Ready(_) => panic!("lost-ack commit was executed again"),
    }
    drop(journal);
    assert_eq!(checked(fixture.open().snapshot(&scope("run1"))).revision, 1);
}

#[test]
fn acknowledged_rollback_is_rejected_before_any_tail_repair() {
    let fixture = Fixture::new();
    let mut journal = fixture.open();
    let proposed = proposal(&journal, input("run1"));
    checked(commit_cell_step(&mut journal, proposed, /*now_micros*/13));
    drop(journal);
    let file = fixture.file("journal");
    checked(file.set_len(HEADER_BYTES as u64));
    drop(file);
    assert!(matches!(CellOwnerJournalV1::open(
        fixture.file("journal"), fixture.witness(), specs(), /*max_records*/64,
    ), Err(CellExecutionError::AcknowledgedHistoryMissing)));
    assert_eq!(checked(fixture.file("journal").metadata()).len(), HEADER_BYTES as u64);
}

#[test]
fn incomplete_unacknowledged_tail_is_trimmed_after_witness_validation() {
    let fixture = Fixture::new();
    let mut journal = fixture.open();
    let proposed = proposal(&journal, input("run1"));
    let receipt = checked(commit_cell_step(&mut journal, proposed, /*now_micros*/13));
    drop(journal);
    let mut file = fixture.file("journal");
    let committed_length = checked(file.seek(SeekFrom::End(0)));
    checked(file.write_all(&[0, 0, 0, 5, 1, 2]));
    checked(file.sync_all());
    drop(file);
    let journal = fixture.open();
    assert_eq!(checked(journal.reconcile(
        &receipt.scope, &receipt.operation_id, receipt.operation_digest,
    )), Some(receipt));
    assert_eq!(checked(fixture.file("journal").metadata()).len(), committed_length);
}

#[test]
fn persisted_frontier_fence_resets_state_and_rejects_prepared_writer() {
    let fixture = Fixture::new();
    let mut journal = fixture.open();
    let stale = proposal(&journal, input("run1"));
    checked(journal.reset_at_frontier(&scope("run1"), d("new-source"), /*writer_epoch*/2));
    assert_eq!(commit_cell_step(&mut journal, stale, /*now_micros*/13), Err(CellExecutionError::CommitConflict));
    let expected = checked(journal.snapshot(&scope("run1")));
    assert_eq!(expected.checkpoint, None);
    drop(journal);
    let journal = fixture.open();
    assert_eq!(checked(journal.snapshot(&scope("run1"))), expected);
    assert!(matches!(prepare_cell_step(
        &definition(), &journal, &Encoder, input("run1"), /*now_micros*/14,
    ), Err(CellExecutionError::StaleSource)));
}

#[test]
fn journal_lock_excludes_a_second_owner_before_it_reads_or_repairs() {
    let fixture = Fixture::new();
    let journal = fixture.open();
    let competitor_witness = checked(FileAnchorWitnessStore::open(
        fixture.file("other-witness"),
        JournalScope {
            scope_digest: d("cell-owner-journal"), objective_digest: d("journal-owner"),
        },
        checked(Generation::new(1)),
        /*max_records*/64,
    ));
    assert!(matches!(CellOwnerJournalV1::open(
        fixture.file("journal"), competitor_witness, specs(), /*max_records*/64,
    ), Err(CellExecutionError::OwnerUnavailable)));
    assert_eq!(checked(journal.snapshot(&scope("run1"))).revision, 0);
}
