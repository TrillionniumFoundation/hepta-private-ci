use super::*;

use std::fs;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

static NEXT: AtomicU64 = AtomicU64::new(1);

fn checked<T, E: std::fmt::Debug>(value: Result<T, E>) -> T {
    match value {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

struct Fixture {
    root: PathBuf,
    file: PathBuf,
}

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-neuron-runtime-index-v2-{}-{serial}",
            std::process::id()
        ));
        checked(fs::create_dir(&root));
        let file = root.join("runtime-index.hptngi02");
        Self { root, file }
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

fn digest(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

fn id(label: &str) -> StableId {
    checked(StableId::new(label))
}

fn context() -> NeuronRuntimeIndexContextV2 {
    NeuronRuntimeIndexContextV2 {
        generation: checked(Generation::new(3)),
        scope: JournalScope {
            scope_digest: digest("scope"),
            objective_digest: digest("objective"),
        },
        runtime_config_digest: digest("config"),
        body_bundle_digest: digest("body"),
        max_records: 8,
        max_file_bytes: 1024 * 1024,
        max_startup_replay_bytes: 1024 * 1024,
    }
}

fn key(label: &str, payload: &str) -> NeuronOperationKeyV2 {
    NeuronOperationKeyV2 {
        tick_id: id(label),
        input_semantic_digest: digest(payload),
    }
}

fn anchor(sequence: u64) -> JournalAnchor {
    JournalAnchor {
        sequence,
        checkpoint_digest: digest(&format!("checkpoint-{sequence}")),
    }
}

#[test]
fn prepare_complete_reopen_preserves_exact_order() {
    let fixture = Fixture::new();
    let mut index = checked(FileNeuronRuntimeIndexV2::create(&fixture.file, context()));
    let first = key("tick-1", "input-1");
    checked(index.prepare(first.clone(), None));
    checked(index.complete(&first, anchor(1), digest("operation-1")));
    let second = key("tick-2", "input-2");
    checked(index.prepare(second.clone(), Some(anchor(1))));
    checked(index.complete(&second, anchor(2), digest("operation-2")));
    drop(index);

    let reopened = checked(FileNeuronRuntimeIndexV2::open_existing(
        &fixture.file,
        context(),
    ));
    let records = checked(reopened.records());
    assert_eq!(records.len(), 2);
    assert_eq!(records[0].key, first);
    assert_eq!(records[1].key, second);
    assert_eq!(checked(reopened.frontier()), Some(anchor(2)));
    assert_eq!(checked(reopened.pending()), None);
}

#[test]
fn exact_retry_is_historical_and_changed_payload_conflicts() {
    let fixture = Fixture::new();
    let mut index = checked(FileNeuronRuntimeIndexV2::create(&fixture.file, context()));
    let operation = key("tick-1", "input-1");
    checked(index.prepare(operation.clone(), None));
    let completed = checked(index.complete(&operation, anchor(1), digest("operation-1")));
    assert_eq!(
        checked(index.admit(&operation, Some(anchor(1)))),
        NeuronRuntimeIndexAdmissionV2::Historical(completed)
    );
    assert_eq!(
        index.admit(&key("tick-1", "different-input"), Some(anchor(1))),
        Err(NeuronRuntimeIndexError::Conflict)
    );
}

#[test]
fn prepared_operation_is_durable_before_result_commit() {
    let fixture = Fixture::new();
    let operation = key("tick-1", "input-1");
    let mut index = checked(FileNeuronRuntimeIndexV2::create(&fixture.file, context()));
    checked(index.prepare(operation.clone(), None));
    drop(index);

    let reopened = checked(FileNeuronRuntimeIndexV2::open_existing(
        &fixture.file,
        context(),
    ));
    assert_eq!(
        checked(reopened.admit(&operation, None)),
        NeuronRuntimeIndexAdmissionV2::Pending(NeuronRuntimeIndexPendingV2 {
            key: operation,
            expected_anchor: None,
        })
    );
}

#[test]
fn partial_tail_is_truncated_without_fabricated_completion() {
    let fixture = Fixture::new();
    let operation = key("tick-1", "input-1");
    let mut index = checked(FileNeuronRuntimeIndexV2::create(&fixture.file, context()));
    checked(index.prepare(operation.clone(), None));
    drop(index);
    let stable = checked(fs::metadata(&fixture.file)).len();
    let mut file = checked(OpenOptions::new().append(true).open(&fixture.file));
    checked(file.write_all(&[0, 0, 0]));
    checked(file.sync_all());
    drop(file);

    let reopened = checked(FileNeuronRuntimeIndexV2::open_existing(
        &fixture.file,
        context(),
    ));
    assert_eq!(checked(fs::metadata(&fixture.file)).len(), stable);
    assert!(matches!(
        checked(reopened.admit(&operation, None)),
        NeuronRuntimeIndexAdmissionV2::Pending(_)
    ));
    assert!(checked(reopened.records()).is_empty());
}

#[test]
fn post_sync_uncertainty_reopens_as_one_prepared_event() {
    let fixture = Fixture::new();
    let operation = key("tick-1", "input-1");
    let mut index = checked(FileNeuronRuntimeIndexV2::create(&fixture.file, context()));
    index.fail_next_append_after_sync();
    assert_eq!(
        index.prepare(operation.clone(), None),
        Err(NeuronRuntimeIndexError::Indeterminate)
    );
    drop(index);

    let reopened = checked(FileNeuronRuntimeIndexV2::open_existing(
        &fixture.file,
        context(),
    ));
    assert_eq!(
        checked(reopened.pending()),
        Some(NeuronRuntimeIndexPendingV2 {
            key: operation,
            expected_anchor: None,
        })
    );
}

#[test]
fn legacy_prepared_record_is_never_treated_as_proof_of_non_execution() {
    let fixture = Fixture::new();
    let operation = key("legacy-tick", "input");
    let mut index = checked(FileNeuronRuntimeIndexV2::create(&fixture.file, context()));
    let event = IndexEventV2::Prepared {
        key: OperationKeyDto::from_key(&operation),
        expected_anchor: None,
    };
    let payload = checked(encode_event(index.event_frontier, &event));
    checked(index.append_payload(&payload));
    drop(index);
    let index = checked(FileNeuronRuntimeIndexV2::open_existing(
        &fixture.file,
        context(),
    ));
    assert!(checked(index.dispatched()));
    assert_eq!(
        checked(checked(index.pending()).ok_or("pending legacy operation")).key,
        operation
    );
}

#[test]
fn failure_tombstones_are_idempotent_and_conflict_fenced() {
    let fixture = Fixture::new();
    let operation = key("failed-tick", "input");
    let mut index = checked(FileNeuronRuntimeIndexV2::create(&fixture.file, context()));
    checked(index.prepare(operation.clone(), None));
    checked(index.mark_dispatched(&operation));
    checked(index.fail_operation(&operation, NeuronOperationFailureV2::InvalidModelOutput));
    let length = checked(fs::metadata(&fixture.file)).len();
    checked(index.fail_operation(&operation, NeuronOperationFailureV2::InvalidModelOutput));
    assert_eq!(checked(fs::metadata(&fixture.file)).len(), length);
    assert_eq!(
        index.fail_operation(&operation, NeuronOperationFailureV2::AdmissionDenied),
        Err(NeuronRuntimeIndexError::Conflict)
    );
    assert_eq!(
        index.admit(&key("failed-tick", "changed"), None),
        Err(NeuronRuntimeIndexError::Conflict)
    );
    drop(index);
    let index = checked(FileNeuronRuntimeIndexV2::open_existing(
        &fixture.file,
        context(),
    ));
    assert_eq!(
        checked(index.failure(&operation)),
        Some(NeuronOperationFailureV2::InvalidModelOutput)
    );
    assert_eq!(checked(index.pending()), None);
    assert_eq!(checked(index.frontier()), None);
}
