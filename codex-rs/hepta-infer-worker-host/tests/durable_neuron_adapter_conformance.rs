//! Conformance contract for every production Neuron inference adapter.
//!
//! This test exercises the concrete durable worker-host adapter through only
//! public product interfaces. It proves that absent/reserved operations are the
//! only `NotStarted` cases, dispatched-unknown work is never redispatched, exact
//! duplicate requests return the original receipt, changed payloads conflict,
//! and restart reconciliation preserves the provider operation identity.

use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_infer_core::FileNeuronFeatureExecutionStoreV1;
use codex_hepta_infer_core::NeuronFeatureObservationV1;
use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::NeuronFeatureStoreContextV1;
use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;
use codex_hepta_infer_core::NeuronModelRuntimeTupleV1;
use codex_hepta_infer_core::build_neuron_feature_receipt_v1;
use codex_hepta_infer_worker_host::DurableNeuronFeatureBackend;
use codex_hepta_infer_worker_host::DurableNeuronFeatureBackendError;
use codex_hepta_infer_worker_host::DurableNeuronFeaturePortV1;
use codex_hepta_neuron::DurableNeuronFeatureResolutionV2;
use codex_hepta_neuron::DurableNeuronInferenceControlPort;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronModelError;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use tempfile::TempDir;

fn checked<T, E: std::fmt::Debug>(value: Result<T, E>) -> T {
    value.unwrap_or_else(|error| panic!("fixture failed: {error:?}"))
}

fn digest(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

fn id(label: &str) -> StableId {
    checked(StableId::new(label))
}

fn generation() -> Generation {
    checked(Generation::new(41))
}

fn context() -> NeuronFeatureStoreContextV1 {
    NeuronFeatureStoreContextV1 {
        generation: generation(),
        owner_digest: digest("adapter-conformance-owner"),
        max_records: 32,
        max_receipt_bytes: 256 * 1024,
        max_file_bytes: 4 * 1024 * 1024,
        max_startup_replay_bytes: 4 * 1024 * 1024,
    }
}

fn request(label: &str) -> NeuronFeatureRequestV1 {
    NeuronFeatureRequestV1 {
        request_id: id(label),
        generation: generation(),
        model_id: id("adapter-conformance-model"),
        encoder_digest: digest("encoder"),
        head_digest: digest("head"),
        weights_digest: digest("weights"),
        input_digest: digest(&format!("input:{label}")),
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

#[derive(Clone, Default)]
struct SharedBackend {
    execute_calls: Arc<AtomicUsize>,
    reconcile_calls: Arc<AtomicUsize>,
    results: Arc<Mutex<BTreeMap<StableId, NeuronFeatureReceiptV1>>>,
}

impl SharedBackend {
    fn publish(&self, operation_id: StableId, value: NeuronFeatureReceiptV1) {
        checked(self.results.lock()).insert(operation_id, value);
    }

    fn execute_calls(&self) -> usize {
        self.execute_calls.load(Ordering::SeqCst)
    }

    fn reconcile_calls(&self) -> usize {
        self.reconcile_calls.load(Ordering::SeqCst)
    }
}

impl DurableNeuronFeatureBackend for SharedBackend {
    fn execute_new(
        &mut self,
        operation_id: &StableId,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, DurableNeuronFeatureBackendError> {
        self.execute_calls.fetch_add(1, Ordering::SeqCst);
        let value = receipt(request);
        self.publish(operation_id.clone(), value.clone());
        Ok(value)
    }

    fn reconcile(
        &mut self,
        operation_id: &StableId,
        _request: &NeuronFeatureRequestV1,
    ) -> Result<Option<NeuronFeatureReceiptV1>, DurableNeuronFeatureBackendError> {
        self.reconcile_calls.fetch_add(1, Ordering::SeqCst);
        Ok(checked(self.results.lock()).get(operation_id).cloned())
    }
}

#[test]
fn production_adapter_reconciliation_conformance_suite() {
    let root = checked(TempDir::new());
    let path = root.path().join("feature-store.bin");
    let backend = SharedBackend::default();
    let absent = request("adapter.absent");
    let original = request("adapter.original");

    let store = checked(FileNeuronFeatureExecutionStoreV1::create(&path, context()));
    let mut port = DurableNeuronFeaturePortV1::new(store, backend.clone());

    assert_eq!(
        checked(port.reconcile_feature(&absent)),
        DurableNeuronFeatureResolutionV2::NotStarted
    );
    assert_eq!(backend.execute_calls(), 0);
    assert_eq!(backend.reconcile_calls(), 0);

    let first = checked(port.execute_feature(&original));
    let duplicate = checked(port.execute_feature(&original));
    assert_eq!(duplicate, first);
    assert_eq!(backend.execute_calls(), 1);
    assert_eq!(backend.reconcile_calls(), 0);

    let mut changed = original.clone();
    changed.input_digest = digest("changed-input");
    changed.feature_vector_q24[0] = 0;
    assert_eq!(
        port.execute_feature(&changed),
        Err(NeuronModelError::Rejected)
    );
    assert_eq!(backend.execute_calls(), 1);
    drop(port);

    let store = checked(FileNeuronFeatureExecutionStoreV1::open_existing(
        &path,
        context(),
    ));
    let mut reopened = DurableNeuronFeaturePortV1::new(store, backend.clone());
    assert_eq!(
        checked(reopened.reconcile_feature(&original)),
        DurableNeuronFeatureResolutionV2::Observed(Box::new(first.clone()))
    );
    assert_eq!(backend.execute_calls(), 1);
    drop(reopened);

    let pending = request("adapter.dispatched-unknown");
    let mut store = checked(FileNeuronFeatureExecutionStoreV1::open_existing(
        &path,
        context(),
    ));
    checked(store.reserve(pending.clone()));
    checked(store.mark_dispatched(&pending));
    drop(store);

    let store = checked(FileNeuronFeatureExecutionStoreV1::open_existing(
        &path,
        context(),
    ));
    let mut restarted = DurableNeuronFeaturePortV1::new(store, backend.clone());
    assert_eq!(
        restarted.reconcile_feature(&pending),
        Err(NeuronModelError::Indeterminate)
    );
    assert_eq!(backend.execute_calls(), 1);
    assert_eq!(backend.reconcile_calls(), 1);

    let observed = receipt(&pending);
    backend.publish(pending.request_id.clone(), observed.clone());
    assert_eq!(
        checked(restarted.reconcile_feature(&pending)),
        DurableNeuronFeatureResolutionV2::Observed(Box::new(observed))
    );
    assert_eq!(backend.execute_calls(), 1);
    assert_eq!(backend.reconcile_calls(), 2);
}
