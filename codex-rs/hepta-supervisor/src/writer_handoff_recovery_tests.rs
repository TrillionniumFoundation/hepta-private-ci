use super::*;

use std::fs::OpenOptions;

use pretty_assertions::assert_eq;
use tempfile::TempDir;

fn file(root: &TempDir) -> File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(root.path().join("handoff"))
        .expect("journal")
}

fn plan() -> WriterHandoffPlanV1 {
    WriterHandoffPlanV1 {
        operation_id: StableId::new("replace-1").expect("id"),
        domain_id: StableId::new("memory").expect("id"),
        source_writer: StableId::new("old").expect("id"),
        target_writer: StableId::new("new").expect("id"),
        old_generation: Generation::new(1).expect("generation"),
        new_generation: Generation::new(2).expect("generation"),
        authority_epoch: 1,
        migration_plan_digest: Digest32::of_bytes(b"migration"),
        schema_digest: Digest32::of_bytes(b"schema"),
        rollback_predecessor_digest: Digest32::of_bytes(b"predecessor"),
    }
}

fn step(phase: WriterHandoffPhaseV1) -> WriterHandoffAdvanceV1 {
    WriterHandoffAdvanceV1 {
        phase,
        evidence_digest: Digest32::of_bytes(format!("{phase:?}").as_bytes()),
        outbox_watermark: (phase == WriterHandoffPhaseV1::Drained).then_some(7),
        unknown_effect_count: 0,
    }
}

#[test]
fn writer_handoff_restarts_at_every_phase_and_retries_without_appending() {
    let root = TempDir::new().expect("temp");
    let mut journal = DurableWriterHandoffJournalV1::create(file(&root), plan()).expect("create");
    for phase in [
        WriterHandoffPhaseV1::AdmissionStopped,
        WriterHandoffPhaseV1::Drained,
        WriterHandoffPhaseV1::OldWriterFenced,
        WriterHandoffPhaseV1::Snapshotted,
        WriterHandoffPhaseV1::Migrated,
        WriterHandoffPhaseV1::Validated,
        WriterHandoffPhaseV1::NewWriterFenced,
        WriterHandoffPhaseV1::RoutePublished,
        WriterHandoffPhaseV1::Retired,
    ] {
        let request = step(phase);
        let checkpoint = journal.advance(request.clone()).expect("advance");
        let length = journal.durable_length;
        drop(journal);
        journal = DurableWriterHandoffJournalV1::recover_at_least(file(&root), &checkpoint)
            .expect("recover exact acknowledged phase");
        assert_eq!(journal.checkpoint(), &checkpoint);
        assert_eq!(journal.advance(request).expect("retry"), checkpoint);
        assert_eq!(journal.durable_length, length);
        assert!(!(checkpoint.old_writer_valid() && checkpoint.new_writer_valid()));
    }
}

#[test]
fn writer_handoff_rejects_acknowledged_prefix_rollback_before_tail_repair() {
    let root = TempDir::new().expect("temp");
    let mut journal = DurableWriterHandoffJournalV1::create(file(&root), plan()).expect("create");
    let old_length = journal.durable_length;
    let acknowledged = journal.advance(step(WriterHandoffPhaseV1::AdmissionStopped)).expect("advance");
    drop(journal);
    let mut raw = file(&root);
    raw.set_len(old_length).expect("simulate restored backup");
    raw.seek(SeekFrom::End(0)).expect("seek");
    raw.write_all(b"{torn").expect("write");
    raw.sync_all().expect("sync");
    drop(raw);
    assert!(matches!(
        DurableWriterHandoffJournalV1::recover_at_least(file(&root), &acknowledged),
        Err(WriterHandoffErrorV1::AcknowledgedCheckpointMissing)
    ));
    assert_eq!(file(&root).metadata().expect("metadata").len(), old_length + 5);
}

#[test]
fn writer_handoff_excludes_competing_recovery_until_owner_exits() {
    let root = TempDir::new().expect("temp");
    let journal = DurableWriterHandoffJournalV1::create(file(&root), plan()).expect("create");
    let checkpoint = journal.checkpoint().clone();
    assert!(matches!(
        DurableWriterHandoffJournalV1::recover_at_least(file(&root), &checkpoint),
        Err(WriterHandoffErrorV1::Busy)
    ));
    drop(journal);
    let recovered = DurableWriterHandoffJournalV1::recover_at_least(file(&root), &checkpoint)
        .expect("lock released at owner exit");
    assert_eq!(recovered.checkpoint(), &checkpoint);
}

#[test]
fn writer_handoff_rejects_oversized_sparse_history_and_releases_failed_lock() {
    let root = TempDir::new().expect("temp");
    let journal = DurableWriterHandoffJournalV1::create(file(&root), plan()).expect("create");
    let checkpoint = journal.checkpoint().clone();
    let length = journal.durable_length;
    drop(journal);
    file(&root).set_len(MAX_JOURNAL_BYTES * 128).expect("sparse file");
    assert!(matches!(
        DurableWriterHandoffJournalV1::recover(file(&root)),
        Err(WriterHandoffErrorV1::JournalTooLarge)
    ));
    file(&root).set_len(length).expect("restore original");
    assert!(DurableWriterHandoffJournalV1::recover_at_least(file(&root), &checkpoint).is_ok());
}

#[test]
fn writer_handoff_minimum_is_bound_to_operation_and_exact_chain() {
    let root = TempDir::new().expect("temp");
    let journal = DurableWriterHandoffJournalV1::create(file(&root), plan()).expect("create");
    let mut wrong = journal.checkpoint().clone();
    wrong.plan.operation_id = StableId::new("another-operation").expect("id");
    wrong.receipt_digest = checkpoint_digest(&wrong);
    drop(journal);
    assert!(matches!(
        DurableWriterHandoffJournalV1::recover_at_least(file(&root), &wrong),
        Err(WriterHandoffErrorV1::AcknowledgedCheckpointMissing)
    ));
}
