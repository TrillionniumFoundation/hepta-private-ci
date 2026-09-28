use super::*;

use std::collections::BTreeMap;

use codex_hepta_infer_core::NeuronFeatureObservationV1;
use codex_hepta_infer_core::NeuronFeatureStoreContextV1;
use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;
use codex_hepta_infer_core::NeuronModelRuntimeTupleV1;
use codex_hepta_infer_core::build_neuron_feature_receipt_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use tempfile::TempDir;

fn checked<T, E: std::fmt::Debug>(value: Result<T, E>) -> T {
    match value {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn digest(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

fn id(label: &str) -> StableId {
    checked(StableId::new(label))
}

fn generation() -> Generation {
    checked(Generation::new(11))
}

fn context() -> NeuronFeatureStoreContextV1 {
    NeuronFeatureStoreContextV1 {
        generation: generation(),
        owner_digest: digest("durable-feature-owner"),
        max_records: 16,
        max_receipt_bytes: 256 * 1024,
        max_file_bytes: 4 * 1024 * 1024,
        max_startup_replay_bytes: 4 * 1024 * 1024,
    }
}

fn request() -> NeuronFeatureRequestV1 {
    NeuronFeatureRequestV1 {
        request_id: id("durable.feature.tick.1"),
        generation: generation(),
        model_id: id("durable.feature.model.1"),
        encoder_digest: digest("encoder"),
        head_digest: digest("head"),
        weights_digest: digest("weights"),
        input_digest: digest("input"),
        feature_vector_q24: vec![1_i64 << 24, 0, -(1_i64 << 23)],
        expected_output_width: 5,
    }
}

fn receipt(request: &NeuronFeatureRequestV1) -> NeuronFeatureReceiptV1 {
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
            drive_q24: vec![1_i64 << 24, 0, 0, 0, 0],
            prediction_q24: vec![0; 5],
            observed_memory_bytes: 8192,
            transient_allocation_bytes: 1024,
            queue_age_micros: 2,
            latency_micros: 7,
            status: NeuronFeatureTerminalStatusV1::Succeeded,
        },
    ))
}

#[derive(Default)]
struct Backend {
    execute_calls: usize,
    reconcile_calls: usize,
    results: BTreeMap<StableId, NeuronFeatureReceiptV1>,
}

impl DurableNeuronFeatureBackend for Backend {
    fn execute_new(
        &mut self,
        operation_id: &StableId,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, DurableNeuronFeatureBackendError> {
        self.execute_calls += 1;
        let value = receipt(request);
        self.results.insert(operation_id.clone(), value.clone());
        Ok(value)
    }

    fn reconcile(
        &mut self,
        operation_id: &StableId,
        _request: &NeuronFeatureRequestV1,
    ) -> Result<Option<NeuronFeatureReceiptV1>, DurableNeuronFeatureBackendError> {
        self.reconcile_calls += 1;
        Ok(self.results.get(operation_id).cloned())
    }
}

#[test]
fn duplicate_returns_original_receipt_without_second_execution() {
    let root = checked(TempDir::new());
    let path = root.path().join("feature-store.bin");
    let store = checked(FileNeuronFeatureExecutionStoreV1::create(&path, context()));
    let mut port = DurableNeuronFeaturePortV1::new(store, Backend::default());
    let request = request();
    let first = checked(port.execute_feature(&request));
    let second = checked(port.execute_feature(&request));
    assert_eq!(first, second);
    assert_eq!(port.backend_mut().execute_calls, 1);
    assert_eq!(port.backend_mut().reconcile_calls, 0);
}

#[test]
fn recovered_dispatched_operation_reconciles_without_execution() {
    let root = checked(TempDir::new());
    let path = root.path().join("feature-store.bin");
    let request = request();
    let expected = receipt(&request);
    let mut store = checked(FileNeuronFeatureExecutionStoreV1::create(&path, context()));
    checked(store.reserve(request.clone()));
    checked(store.mark_dispatched(&request));
    drop(store);

    let mut backend = Backend::default();
    backend
        .results
        .insert(request.request_id.clone(), expected.clone());
    let store = checked(FileNeuronFeatureExecutionStoreV1::open_existing(
        &path,
        context(),
    ));
    let mut port = DurableNeuronFeaturePortV1::new(store, backend);
    assert_eq!(checked(port.execute_feature(&request)), expected);
    assert_eq!(port.backend_mut().execute_calls, 0);
    assert_eq!(port.backend_mut().reconcile_calls, 1);
}

#[test]
fn unresolved_dispatched_operation_is_indeterminate_not_reexecuted() {
    let root = checked(TempDir::new());
    let path = root.path().join("feature-store.bin");
    let request = request();
    let mut store = checked(FileNeuronFeatureExecutionStoreV1::create(&path, context()));
    checked(store.reserve(request.clone()));
    checked(store.mark_dispatched(&request));
    drop(store);

    let store = checked(FileNeuronFeatureExecutionStoreV1::open_existing(
        &path,
        context(),
    ));
    let mut port = DurableNeuronFeaturePortV1::new(store, Backend::default());
    assert_eq!(
        port.execute_feature(&request),
        Err(NeuronModelError::Indeterminate)
    );
    assert_eq!(port.backend_mut().execute_calls, 0);
    assert_eq!(port.backend_mut().reconcile_calls, 1);
}

#[test]
fn changed_payload_conflicts_before_backend() {
    let root = checked(TempDir::new());
    let path = root.path().join("feature-store.bin");
    let store = checked(FileNeuronFeatureExecutionStoreV1::create(&path, context()));
    let mut port = DurableNeuronFeaturePortV1::new(store, Backend::default());
    let request = request();
    checked(port.execute_feature(&request));
    let mut changed = request;
    changed.feature_vector_q24[0] = 0;
    changed.input_digest = digest("changed-input");
    assert_eq!(
        port.execute_feature(&changed),
        Err(NeuronModelError::Rejected)
    );
    assert_eq!(port.backend_mut().execute_calls, 1);
}

#[test]
fn explicit_reconcile_of_absent_or_reserved_work_never_dispatches() {
    let root = checked(TempDir::new());
    let path = root.path().join("feature-store.bin");
    let mut store = checked(FileNeuronFeatureExecutionStoreV1::create(&path, context()));
    let request = request();
    checked(store.reserve(request.clone()));
    let mut port = DurableNeuronFeaturePortV1::new(store, Backend::default());
    assert_eq!(
        checked(port.reconcile_feature(&request)),
        DurableNeuronFeatureResolutionV2::NotStarted
    );
    assert_eq!(port.backend_mut().execute_calls, 0);
    assert_eq!(port.backend_mut().reconcile_calls, 0);
    let mut absent = request;
    absent.request_id = id("never-reserved");
    assert_eq!(
        checked(port.reconcile_feature(&absent)),
        DurableNeuronFeatureResolutionV2::NotStarted
    );
    assert_eq!(port.backend_mut().execute_calls, 0);
}

#[test]
fn explicit_reconcile_of_dispatched_work_queries_and_returns_the_existing_receipt() {
    let root = checked(TempDir::new());
    let path = root.path().join("feature-store.bin");
    let request = request();
    let expected = receipt(&request);
    let mut store = checked(FileNeuronFeatureExecutionStoreV1::create(&path, context()));
    checked(store.reserve(request.clone()));
    checked(store.mark_dispatched(&request));
    let mut backend = Backend::default();
    backend
        .results
        .insert(request.request_id.clone(), expected.clone());
    let mut port = DurableNeuronFeaturePortV1::new(store, backend);
    assert_eq!(
        checked(port.reconcile_feature(&request)),
        DurableNeuronFeatureResolutionV2::Observed(Box::new(expected))
    );
    assert_eq!(port.backend_mut().execute_calls, 0);
    assert_eq!(port.backend_mut().reconcile_calls, 1);
}
