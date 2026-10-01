use std::fmt::Debug;
use std::fs::OpenOptions;
use std::io::Write;

use codex_hepta_types::Digest32;
use tempfile::tempdir;

use super::LOG_NAME;
use super::PlannerStoreConfigV1;
use super::PlannerStoreError;
use super::PlannerStoreFailpointV1;
use super::PlannerStoreRecordKindV1;
use super::PlannerStoreV1;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn must_err<T, E: Debug>(result: Result<T, E>) -> E {
    match result {
        Err(error) => error,
        Ok(_) => panic!("expected error"),
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn append(store: &mut PlannerStoreV1, name: &str) {
    must(store.append(
        PlannerStoreRecordKindV1::Decision,
        digest(&format!("operation:{name}")),
        digest(&format!("payload:{name}")),
        format!("canonical decision envelope {name}").as_bytes(),
    ));
}

#[test]
fn complete_envelopes_reopen_and_verify_anchor() {
    let directory = must(tempdir());
    let anchor = digest("independent-anchor");
    let mut store = must(PlannerStoreV1::open(
        directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    append(&mut store, "one");
    let checkpoint = must(store.checkpoint(anchor));
    assert_eq!(checkpoint.sequence, 1);
    assert_eq!(must(store.verify_checkpoint(anchor)), checkpoint);
    drop(store);

    let reopened = must(PlannerStoreV1::open(
        directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    assert_eq!(reopened.records().len(), 1);
    assert_eq!(
        reopened.records()[0].envelope,
        b"canonical decision envelope one"
    );
    assert_eq!(must(reopened.verify_checkpoint(anchor)), checkpoint);
}

#[test]
fn partial_tail_is_truncated_but_complete_corruption_is_not_repaired() {
    let directory = must(tempdir());
    let mut store = must(PlannerStoreV1::open(
        directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    append(&mut store, "one");
    drop(store);

    let mut log = must(
        OpenOptions::new()
            .append(true)
            .open(directory.path().join(LOG_NAME)),
    );
    must(log.write_all(b"partial-tail"));
    must(log.sync_data());
    drop(log);

    let reopened = must(PlannerStoreV1::open(
        directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    assert_eq!(reopened.records().len(), 1);
    drop(reopened);

    let mut bytes = must(std::fs::read(directory.path().join(LOG_NAME)));
    let last = bytes.len() - 1;
    bytes[last] ^= 1;
    must(std::fs::write(directory.path().join(LOG_NAME), bytes));
    let error = must_err(PlannerStoreV1::open(
        directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    assert!(matches!(error, PlannerStoreError::CorruptRecordDigest));
}

#[test]
fn crash_after_frame_write_reopens_idempotently() {
    let directory = must(tempdir());
    let mut store = must(PlannerStoreV1::open(
        directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    store.set_failpoint(Some(PlannerStoreFailpointV1::AfterFrameWriteBeforeSync));
    let error = must_err(store.append(
        PlannerStoreRecordKindV1::Decision,
        digest("operation:one"),
        digest("payload:one"),
        b"canonical decision envelope one",
    ));
    assert!(matches!(
        error,
        PlannerStoreError::Failpoint(PlannerStoreFailpointV1::AfterFrameWriteBeforeSync)
    ));
    drop(store);

    let mut reopened = must(PlannerStoreV1::open(
        directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    assert_eq!(reopened.records().len(), 1);
    let replay = must(reopened.append(
        PlannerStoreRecordKindV1::Decision,
        digest("operation:one"),
        digest("payload:one"),
        b"canonical decision envelope one",
    ));
    assert_eq!(replay.sequence, 1);
    assert_eq!(reopened.records().len(), 1);
}

#[test]
fn compaction_backup_and_restore_preserve_anchored_suffix() {
    let source = must(tempdir());
    let backup = must(tempdir());
    let restored = must(tempdir());
    let anchor = digest("backup-anchor");
    let mut store = must(PlannerStoreV1::open(
        source.path(),
        PlannerStoreConfigV1::default(),
    ));
    append(&mut store, "one");
    append(&mut store, "two");
    append(&mut store, "three");
    must(store.compact(2));
    assert_eq!(store.records()[0].sequence, 2);
    assert_eq!(store.records()[1].sequence, 3);
    must(store.checkpoint(anchor));
    must(store.backup_to(backup.path()));
    drop(store);

    let restored_store = must(PlannerStoreV1::restore_from_backup(
        backup.path(),
        restored.path(),
        PlannerStoreConfigV1::default(),
    ));
    assert_eq!(restored_store.records().len(), 2);
    assert_eq!(restored_store.records()[0].sequence, 2);
    assert_eq!(restored_store.records()[1].sequence, 3);
    must(restored_store.verify_checkpoint(anchor));
}
