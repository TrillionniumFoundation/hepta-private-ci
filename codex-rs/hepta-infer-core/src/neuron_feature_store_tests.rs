use super::*;

use std::fs;
use std::fs::OpenOptions;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use crate::NeuronFeatureObservationV1;
use crate::build_neuron_feature_receipt_v1;

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
            "hepta-neuron-feature-store-{}-{serial}",
            std::process::id()
        ));
        checked(fs::create_dir(&root));
        let file = root.join("feature-store.bin");
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

fn generation() -> Generation {
    checked(Generation::new(7))
}

fn context() -> NeuronFeatureStoreContextV1 {
    NeuronFeatureStoreContextV1 {
        generation: generation(),
        owner_digest: digest("feature-owner"),
        max_records: 16,
        max_receipt_bytes: 256 * 1024,
        max_file_bytes: 4 * 1024 * 1024,
        max_startup_replay_bytes: 4 * 1024 * 1024,
    }
}

fn request() -> NeuronFeatureRequestV1 {
    let features = vec![1_i64 << 24, 0, -(1_i64 << 23)];
    NeuronFeatureRequestV1 {
        request_id: id("feature.tick.1"),
        generation: generation(),
        model_id: id("feature.model.1"),
        encoder_digest: digest("encoder"),
        head_digest: digest("head"),
        weights_digest: digest("weights"),
        input_digest: digest("input"),
        feature_vector_q24: features,
        expected_output_width: 5,
    }
}

fn receipt(request: &NeuronFeatureRequestV1) -> NeuronFeatureReceiptV1 {
    receipt_with_status(request, NeuronFeatureTerminalStatusV1::Succeeded)
}

fn receipt_with_status(
    request: &NeuronFeatureRequestV1,
    status: NeuronFeatureTerminalStatusV1,
) -> NeuronFeatureReceiptV1 {
    let (drive_q24, prediction_q24) = match status {
        NeuronFeatureTerminalStatusV1::Succeeded => (vec![1_i64 << 24, 0, 0, 0, 0], vec![0; 5]),
        NeuronFeatureTerminalStatusV1::Failed
        | NeuronFeatureTerminalStatusV1::Cancelled
        | NeuronFeatureTerminalStatusV1::Indeterminate => (Vec::new(), Vec::new()),
    };
    checked(build_neuron_feature_receipt_v1(
        request,
        NeuronModelRuntimeTupleV1 {
            model_id: request.model_id.clone(),
            model_manifest_digest: digest("manifest"),
            weights_digest: request.weights_digest,
            tokenizer_digest: digest("tokenizer"),
            preprocessor_digest: digest("preprocessor"),
            quantization_digest: digest("quantization"),
            runtime_digest: digest("runtime"),
            device_digest: digest("device"),
        },
        NeuronFeatureObservationV1 {
            encoder_digest: request.encoder_digest,
            head_digest: request.head_digest,
            drive_q24,
            prediction_q24,
            observed_memory_bytes: 4096,
            transient_allocation_bytes: 512,
            queue_age_micros: 3,
            latency_micros: 9,
            status,
        },
    ))
}

#[test]
fn exact_duplicate_returns_original_full_receipt_after_restart() {
    let fixture = Fixture::new();
    let request = request();
    let expected = receipt(&request);
    let mut store = checked(FileNeuronFeatureExecutionStoreV1::create(
        &fixture.file,
        context(),
    ));
    assert!(matches!(
        checked(store.admit(&request)),
        NeuronFeatureAdmissionV1::New
    ));
    checked(store.reserve(request.clone()));
    checked(store.mark_dispatched(&request));
    let committed = checked(store.observe(&request, expected.clone()));
    assert_eq!(committed.receipt, Some(expected.clone()));
    drop(store);

    let reopened = checked(FileNeuronFeatureExecutionStoreV1::open_existing(
        &fixture.file,
        context(),
    ));
    assert_eq!(
        checked(reopened.admit(&request)),
        NeuronFeatureAdmissionV1::Historical(Box::new(NeuronFeatureExecutionRecordV1 {
            request: request.clone(),
            request_digest: checked(neuron_feature_request_digest_v1(&request)),
            state: NeuronFeatureExecutionStateV1::Succeeded,
            receipt: Some(expected),
        }))
    );
}

#[test]
fn same_tick_with_changed_payload_conflicts() {
    let fixture = Fixture::new();
    let request = request();
    let mut store = checked(FileNeuronFeatureExecutionStoreV1::create(
        &fixture.file,
        context(),
    ));
    checked(store.reserve(request.clone()));
    let mut changed = request;
    changed.feature_vector_q24[0] = 0;
    changed.input_digest = digest("changed-input");
    assert_eq!(
        store.admit(&changed),
        Err(NeuronFeatureStoreError::Conflict)
    );
}

#[test]
fn dispatched_recovery_is_reconcile_only_and_has_no_fabricated_result() {
    let fixture = Fixture::new();
    let request = request();
    let mut store = checked(FileNeuronFeatureExecutionStoreV1::create(
        &fixture.file,
        context(),
    ));
    checked(store.reserve(request.clone()));
    checked(store.mark_dispatched(&request));
    drop(store);

    let reopened = checked(FileNeuronFeatureExecutionStoreV1::open_existing(
        &fixture.file,
        context(),
    ));
    let record = checked(reopened.get(&request.request_id)).expect("record");
    assert_eq!(record.state, NeuronFeatureExecutionStateV1::Dispatched);
    assert_eq!(record.receipt, None);
    assert_eq!(checked(reopened.unresolved_count()), 1);
}

#[test]
fn partial_tail_is_truncated_without_success() {
    let fixture = Fixture::new();
    let request = request();
    let mut store = checked(FileNeuronFeatureExecutionStoreV1::create(
        &fixture.file,
        context(),
    ));
    checked(store.reserve(request.clone()));
    let stable = checked(fs::metadata(&fixture.file)).len();
    drop(store);
    let mut file = checked(OpenOptions::new().append(true).open(&fixture.file));
    checked(file.write_all(&[0, 0, 0]));
    checked(file.sync_all());
    drop(file);

    let reopened = checked(FileNeuronFeatureExecutionStoreV1::open_existing(
        &fixture.file,
        context(),
    ));
    assert_eq!(checked(fs::metadata(&fixture.file)).len(), stable);
    let record = checked(reopened.get(&request.request_id)).expect("record");
    assert_eq!(record.state, NeuronFeatureExecutionStateV1::Reserved);
    assert_eq!(record.receipt, None);
}

#[test]
fn post_sync_uncertainty_recovers_one_terminal_receipt() {
    let fixture = Fixture::new();
    let request = request();
    let expected = receipt(&request);
    let mut store = checked(FileNeuronFeatureExecutionStoreV1::create(
        &fixture.file,
        context(),
    ));
    checked(store.reserve(request.clone()));
    checked(store.mark_dispatched(&request));
    store.fail_next_append_after_sync();
    assert_eq!(
        store.observe(&request, expected.clone()),
        Err(NeuronFeatureStoreError::Indeterminate)
    );
    drop(store);

    let reopened = checked(FileNeuronFeatureExecutionStoreV1::open_existing(
        &fixture.file,
        context(),
    ));
    let record = checked(reopened.get(&request.request_id)).expect("record");
    assert_eq!(record.state, NeuronFeatureExecutionStateV1::Succeeded);
    assert_eq!(record.receipt, Some(expected));
}

#[test]
fn complete_frame_corruption_fails_closed() {
    let fixture = Fixture::new();
    let request = request();
    let mut store = checked(FileNeuronFeatureExecutionStoreV1::create(
        &fixture.file,
        context(),
    ));
    checked(store.reserve(request));
    drop(store);

    let mut file = checked(
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(&fixture.file),
    );
    checked(file.seek(SeekFrom::Start(HEADER_BYTES as u64 + 8)));
    checked(file.write_all(&[0xff]));
    checked(file.sync_all());
    drop(file);

    assert!(matches!(
        FileNeuronFeatureExecutionStoreV1::open_existing(&fixture.file, context()),
        Err(NeuronFeatureStoreError::Corrupt)
    ));
}

#[test]
fn indeterminate_survives_restart_and_resolves_without_redispatch() {
    for status in [
        NeuronFeatureTerminalStatusV1::Succeeded,
        NeuronFeatureTerminalStatusV1::Failed,
        NeuronFeatureTerminalStatusV1::Cancelled,
    ] {
        let fixture = Fixture::new();
        let request = request();
        let unknown = receipt_with_status(&request, NeuronFeatureTerminalStatusV1::Indeterminate);
        let mut store = checked(FileNeuronFeatureExecutionStoreV1::create(
            &fixture.file,
            context(),
        ));
        checked(store.reserve(request.clone()));
        checked(store.mark_dispatched(&request));
        let unresolved = checked(store.observe(&request, unknown.clone()));
        let bytes = checked(fs::read(&fixture.file));
        assert_eq!(
            checked(store.observe(&request, unknown.clone())),
            unresolved
        );
        assert_eq!(checked(fs::read(&fixture.file)), bytes);
        drop(store);

        let mut store = checked(FileNeuronFeatureExecutionStoreV1::open_existing(
            &fixture.file,
            context(),
        ));
        assert_eq!(checked(store.unresolved()), vec![unresolved.clone()]);
        assert_eq!(checked(store.unresolved_count()), 1);
        assert_eq!(checked(store.reserve(request.clone())), unresolved);
        assert_eq!(
            store.mark_dispatched(&request),
            Err(NeuronFeatureStoreError::InvalidTransition)
        );
        let terminal = checked(store.observe(&request, receipt_with_status(&request, status)));
        let bytes = checked(fs::read(&fixture.file));
        assert_eq!(
            store.observe(&request, unknown),
            Err(NeuronFeatureStoreError::Conflict)
        );
        assert_eq!(checked(fs::read(&fixture.file)), bytes);
        drop(store);

        let store = checked(FileNeuronFeatureExecutionStoreV1::open_existing(
            &fixture.file,
            context(),
        ));
        assert_eq!(checked(store.get(&request.request_id)), Some(terminal));
        assert_eq!(checked(store.unresolved_count()), 0);
    }
}

#[test]
fn unknown_resolution_sync_loss_is_recovered_not_reexecuted() {
    let fixture = Fixture::new();
    let request = request();
    let mut store = checked(FileNeuronFeatureExecutionStoreV1::create(
        &fixture.file,
        context(),
    ));
    checked(store.reserve(request.clone()));
    checked(store.mark_dispatched(&request));
    checked(store.observe(
        &request,
        receipt_with_status(&request, NeuronFeatureTerminalStatusV1::Indeterminate),
    ));
    store.fail_next_append_after_sync();
    let expected = receipt(&request);
    assert_eq!(
        store.observe(&request, expected.clone()),
        Err(NeuronFeatureStoreError::Indeterminate)
    );
    drop(store);
    let mut store = checked(FileNeuronFeatureExecutionStoreV1::open_existing(
        &fixture.file,
        context(),
    ));
    let bytes = checked(fs::read(&fixture.file));
    assert_eq!(
        checked(store.observe(&request, expected.clone())).receipt,
        Some(expected)
    );
    assert_eq!(checked(fs::read(&fixture.file)), bytes);
    assert_eq!(checked(store.unresolved_count()), 0);
}

#[test]
fn wrong_generation_cannot_create_unreplayable_history() {
    let fixture = Fixture::new();
    let mut store = checked(FileNeuronFeatureExecutionStoreV1::create(
        &fixture.file,
        context(),
    ));
    let mut request = request();
    request.generation = checked(Generation::new(8));
    let bytes = checked(fs::read(&fixture.file));
    assert_eq!(
        store.reserve(request),
        Err(NeuronFeatureStoreError::ContextMismatch)
    );
    assert_eq!(checked(fs::read(&fixture.file)), bytes);
    drop(store);
    let store = checked(FileNeuronFeatureExecutionStoreV1::open_existing(
        &fixture.file,
        context(),
    ));
    assert_eq!(checked(store.unresolved_count()), 0);
}

#[test]
fn resolution_rejects_model_replacement_in_writer_and_replay() {
    let fixture = Fixture::new();
    let request = request();
    let mut store = checked(FileNeuronFeatureExecutionStoreV1::create(
        &fixture.file,
        context(),
    ));
    checked(store.reserve(request.clone()));
    checked(store.mark_dispatched(&request));
    let unknown = receipt_with_status(&request, NeuronFeatureTerminalStatusV1::Indeterminate);
    checked(store.observe(&request, unknown.clone()));
    let mut runtime = unknown.runtime_tuple;
    runtime.device_digest = digest("replacement-device");
    let changed = checked(build_neuron_feature_receipt_v1(
        &request,
        runtime,
        NeuronFeatureObservationV1 {
            encoder_digest: request.encoder_digest,
            head_digest: request.head_digest,
            drive_q24: Vec::new(),
            prediction_q24: Vec::new(),
            observed_memory_bytes: 4096,
            transient_allocation_bytes: 512,
            queue_age_micros: 3,
            latency_micros: 9,
            status: NeuronFeatureTerminalStatusV1::Failed,
        },
    ));
    let bytes = checked(fs::read(&fixture.file));
    assert_eq!(
        store.observe(&request, changed.clone()),
        Err(NeuronFeatureStoreError::Conflict)
    );
    assert_eq!(checked(fs::read(&fixture.file)), bytes);
    // Bypass only the writer reducer to exercise validation of a checksummed,
    // structurally valid but semantically invalid event during reopen.
    let event = Event::ResolveIndeterminateV1 {
        request_id: request.request_id.to_string(),
        request_digest: checked(neuron_feature_request_digest_v1(&request)).to_string(),
        receipt: ReceiptDto::from_receipt(&changed),
    };
    checked(store.append_payload(&checked(encode_event(&event))));
    drop(store);
    assert!(matches!(
        FileNeuronFeatureExecutionStoreV1::open_existing(&fixture.file, context()),
        Err(NeuronFeatureStoreError::Corrupt)
    ));
}
