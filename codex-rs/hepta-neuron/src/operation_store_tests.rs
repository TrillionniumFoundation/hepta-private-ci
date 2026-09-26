use super::*;

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

use crate::LocalModelRuntimeReceiptV1;
use crate::NeuronResourceReceiptV1;
use crate::NeuronSignalReceiptV1;
use crate::NeuronTickReceiptV1;

static NEXT: AtomicU64 = AtomicU64::new(0);

fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-neuron-operation-store-{}-{serial}",
            std::process::id()
        ));
        checked(fs::create_dir(&root));
        Self(root)
    }

    fn file(&self) -> File {
        checked(
            OpenOptions::new()
                .read(true)
                .write(true)
                .create(true)
                .truncate(false)
                .open(self.path()),
        )
    }

    fn path(&self) -> PathBuf {
        self.0.join("operations")
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn digest(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

fn id(label: &str) -> StableId {
    checked(StableId::new(label))
}

fn generation() -> Generation {
    checked(Generation::new(1))
}

fn scope() -> JournalScope {
    JournalScope {
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
    }
}

fn anchor(sequence: u64) -> JournalAnchor {
    JournalAnchor {
        sequence,
        checkpoint_digest: digest(&format!("checkpoint-{sequence}")),
    }
}

fn operation(
    sequence: u64,
    expected_anchor: Option<JournalAnchor>,
    tick_id: &str,
) -> PreparedNeuronOperationV1 {
    let next_anchor = anchor(sequence);
    let checkpoint_before = expected_anchor.map_or(Digest32::ZERO, |value| value.checkpoint_digest);
    let input_digest = digest(&format!("input-{sequence}"));
    let runtime_receipt = LocalModelRuntimeReceiptV1 {
        model_id: id("model"),
        model_manifest_digest: digest("manifest"),
        weights_digest: digest("weights"),
        tokenizer_digest: digest("tokenizer"),
        preprocessor_digest: digest("preprocessor"),
        quantization_id: id("q8"),
        quantization_digest: digest("quantization"),
        backend_id: id("backend"),
        runtime_digest: digest("runtime"),
        device_identity_digest: digest("device"),
        latency_micros: 11,
        resident_bytes: 4096,
    };
    let output = NeuronRuntimeOutputV1 {
        tick: NeuronTickReceiptV1 {
            tick_id: id(tick_id),
            checkpoint_before,
            checkpoint_after: next_anchor.checkpoint_digest,
            activation_digest: digest("activation"),
            active_indices: vec![0],
            sparsity_ppm: 200_000,
            threshold_digest: digest("threshold"),
            eligibility_digest: digest("eligibility"),
            prediction_error_q24: 1,
            confidence_ppm: 900_000,
            ood_ppm: 100_000,
            abstain: false,
            resource_receipt: NeuronResourceReceiptV1 {
                execution_micros: 10,
                transient_allocation_bytes: 128,
                checkpoint_bytes: 256,
                journal_bytes_written: 320,
                write_amplification_ppm: 1_250_000,
                saturation_count: 0,
                queue_age_micros: 1,
            },
        },
        signal: NeuronSignalReceiptV1 {
            signal_set_id: id(tick_id),
            model_runtime_digest: digest("model-runtime"),
            temporal_state_digest: digest("temporal"),
            signals_q24: vec![1, 0, 0, 0, 0],
            activation_sparsity_ppm: 200_000,
            ood_ppm: 100_000,
            abstain: false,
            authority: AuthorityPosture::DENY_ALL,
        },
        model_runtime: runtime_receipt,
    };
    checked(PreparedNeuronOperationV1::new(
        input_digest,
        id(tick_id),
        expected_anchor,
        next_anchor,
        SparseTick {
            scope_digest: scope().scope_digest,
            objective_digest: scope().objective_digest,
            ndu_digest: digest("ndu"),
            body_digest: digest("body"),
            input_digest,
            sequence,
            monotonic_micros: sequence * 1_000,
            drive_q24: vec![1, 0, 0, 0, 0],
            prediction_q24: vec![0; 5],
        },
        output,
    ))
}

fn open(fixture: &Fixture, config_digest: Digest32) -> FileNeuronOperationStore {
    checked(FileNeuronOperationStore::open(
        fixture.file(),
        config_digest,
        scope(),
        generation(),
        /*state_width*/ 5,
        /*max_operations*/ 8,
    ))
}

#[test]
fn prepared_and_completed_results_survive_reopen() {
    let fixture = Fixture::new();
    let config_digest = digest("config");
    let first = operation(1, None, "tick-1");
    {
        let mut store = open(&fixture, config_digest);
        checked(store.prepare(first.clone()));
        assert_eq!(checked(store.pending()), Some(first.clone()));
        checked(store.complete(first.operation_digest));
        assert_eq!(checked(store.latest()), Some(first.clone()));
    }
    let reopened = open(&fixture, config_digest);
    assert_eq!(checked(reopened.frontier()), Some(first.next_anchor));
    assert_eq!(checked(reopened.find_tick(&first.tick_id)), Some(first));
    assert_eq!(checked(reopened.pending()), None);
}

#[test]
fn exact_context_is_frozen_and_rejection_does_not_rewrite_history() {
    let fixture = Fixture::new();
    let config_digest = digest("config");
    let first = operation(1, None, "tick-1");
    {
        let mut store = open(&fixture, config_digest);
        checked(store.prepare(first.clone()));
        checked(store.complete(first.operation_digest));
    }
    let before = checked(fs::read(fixture.path()));
    assert_eq!(
        FileNeuronOperationStore::open(
            fixture.file(),
            digest("different-config"),
            scope(),
            generation(),
            /*state_width*/ 5,
            /*max_operations*/ 8,
        )
        .err(),
        Some(OperationStoreError::ContextMismatch)
    );
    assert_eq!(checked(fs::read(fixture.path())), before);
}

#[test]
fn incomplete_tail_is_removed_without_losing_the_last_complete_result() {
    let fixture = Fixture::new();
    let config_digest = digest("config");
    let first = operation(1, None, "tick-1");
    {
        let mut store = open(&fixture, config_digest);
        checked(store.prepare(first.clone()));
        checked(store.complete(first.operation_digest));
    }
    let complete_length = checked(fs::metadata(fixture.path())).len();
    {
        let mut file = checked(OpenOptions::new().append(true).open(fixture.path()));
        checked(file.write_all(&[0, 0, 0]));
        checked(file.sync_all());
    }
    let reopened = open(&fixture, config_digest);
    assert_eq!(checked(reopened.latest()), Some(first));
    assert_eq!(checked(fs::metadata(fixture.path())).len(), complete_length);
}

#[test]
fn live_writer_and_reused_tick_identity_are_fenced() {
    let fixture = Fixture::new();
    let config_digest = digest("config");
    let mut store = open(&fixture, config_digest);
    assert_eq!(
        FileNeuronOperationStore::open(
            fixture.file(),
            config_digest,
            scope(),
            generation(),
            /*state_width*/ 5,
            /*max_operations*/ 8,
        )
        .err(),
        Some(OperationStoreError::Busy)
    );
    let first = operation(1, None, "tick-1");
    checked(store.prepare(first.clone()));
    let mut changed = first;
    changed.input_digest = digest("different-input");
    assert_eq!(
        store.prepare(changed).err(),
        Some(OperationStoreError::InvalidRecord)
    );
}

#[test]
fn existing_open_rejects_missing_history_without_initializing_it() {
    let fixture = Fixture::new();
    let file = fixture.file();
    let before = checked(fs::read(fixture.path()));
    assert_eq!(
        FileNeuronOperationStore::open_existing(
            file,
            digest("config"),
            scope(),
            generation(),
            /*state_width*/ 5,
            /*max_operations*/ 8,
        )
        .err(),
        Some(OperationStoreError::HistoryMissing)
    );
    assert_eq!(checked(fs::read(fixture.path())), before);
}
