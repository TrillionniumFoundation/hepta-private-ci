use super::*;

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_infer_worker_host::model_worker::DriverModelHandle;
use codex_hepta_infer_worker_host::model_worker::DriverNeuronFeatureObservation;
use codex_hepta_infer_worker_host::model_worker::DriverRunObservation;
use codex_hepta_infer_worker_host::model_worker::Error as WorkerError;
use codex_hepta_infer_worker_host::model_worker::ModelManifest;
use codex_hepta_infer_worker_host::model_worker::ResourceGrant;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::NeuronCalibrationProfileV1;
use codex_hepta_neuron::NeuronResourceEnvelopeV1;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_neuron::WitnessStoreError;
use codex_hepta_neuron::canonical_feature_vector_digest_v1;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

const Q: i64 = 1 << 24;
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
            "hepta-neuron-product-{}-{serial}",
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
                .open(self.0.join("journal")),
        )
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[derive(Clone, Default)]
struct MemoryWitness(Arc<Mutex<Option<JournalAnchor>>>);

impl AnchorWitnessStore for MemoryWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.0
            .lock()
            .map(|value| *value)
            .map_err(|_| WitnessStoreError::Unavailable)
    }

    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        let mut current = self
            .0
            .lock()
            .map_err(|_| WitnessStoreError::Unavailable)?;
        if *current != expected {
            return Err(WitnessStoreError::Conflict);
        }
        *current = Some(next);
        Ok(())
    }
}

#[derive(Debug, Default)]
struct Driver;

impl ModelDriver for Driver {
    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, WorkerError> {
        Ok(DriverModelHandle {
            opaque_id: format!("handle.{}", manifest.model_id),
            observed_memory_bytes: 4_096,
        })
    }

    fn run(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &WorkerRequest,
    ) -> Result<DriverRunObservation, WorkerError> {
        Err(WorkerError::DriverFailure(
            "generic model path is not used by this test".to_string(),
        ))
    }

    fn unload(&mut self, _handle: DriverModelHandle) -> Result<(), WorkerError> {
        Ok(())
    }
}

impl NeuronFeatureDriver for Driver {
    fn run_neuron_features(
        &mut self,
        _handle: &DriverModelHandle,
        request: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, WorkerError> {
        Ok(DriverNeuronFeatureObservation {
            terminal_observed: true,
            succeeded: true,
            encoder_digest: request.encoder_digest.clone(),
            head_digest: request.head_digest.clone(),
            drive_q24: vec![Q, Q / 2, 0, 0, 0],
            prediction_q24: vec![0; request.expected_output_width],
            observed_memory_bytes: 4_096,
            transient_allocation_bytes: 8_192,
            queue_age_micros: 3,
            latency_micros: 23,
        })
    }
}

fn native_config() -> SparseConfig {
    SparseConfig {
        model_digest: Digest32::of_bytes(b"head"),
        normalization_digest: Digest32::of_bytes(b"normalization"),
        generation: checked(Generation::new(1)),
        width: 5,
        top_k: 1,
        temporal_decay_q24: Q / 2,
        inhibition_gain_q24: Q,
        inhibition: vec![],
        activity_decay_q24: 0,
        target_activity_q24: Q / 8,
        threshold_rate_q24: Q / 8,
        threshold_min_q24: -Q,
        threshold_max_q24: Q,
        eligibility_decay_q24: Q / 2,
    }
}

fn runtime_config(native: &SparseConfig) -> NeuronRuntimeConfigV1 {
    NeuronRuntimeConfigV1 {
        config_id: checked(StableId::new("neuron.config.product")),
        generation: native.generation,
        model_id: checked(StableId::new("model.1")),
        encoder_digest: Digest32::of_bytes(b"encoder"),
        head_digest: native.model_digest,
        weights_digest: Digest32::of_bytes(b"weights"),
        normalization_digest: native.normalization_digest,
        native_config_digest: checked(native.digest()),
        input_feature_dimension: 3,
        state_width: native.width,
        modulator_dimension: 4,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: Digest32::of_bytes(b"calibration"),
            ood_artifact_digest: Digest32::of_bytes(b"ood"),
            generation: native.generation,
            valid_from_sequence: 1,
            expires_after_sequence: 64,
            zero_confidence_error_q24: 16 * Q,
            maximum_in_domain_error_q24: 8 * Q,
            minimum_confidence_ppm: 500_000,
            maximum_ood_ppm: 500_000,
            minimum_active_ppm: 100_000,
            maximum_active_ppm: 300_000,
            maximum_projection_count: 8,
            measured_ece_ppm: 10_000,
            maximum_ece_ppm: 30_000,
            measured_false_acceptance_ppm: 2_000,
            maximum_false_acceptance_ppm: 5_000,
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 1_000_000,
            p99_latency_micros: 10_000_000,
            transient_allocation_bytes: 1 << 20,
            checkpoint_bytes: 1 << 20,
            write_amplification_ppm: 4_000_000,
        },
    }
}

fn subject() -> StableId {
    checked(StableId::new("subject.product"))
}

fn objective() -> Digest32 {
    Digest32::of_bytes(b"objective")
}

fn scope() -> JournalScope {
    let mut bytes = b"hepta.neuron.subject-scope.v1".to_vec();
    let raw = subject().as_str().as_bytes().to_vec();
    bytes.extend_from_slice(&(raw.len() as u32).to_be_bytes());
    bytes.extend_from_slice(&raw);
    JournalScope {
        scope_digest: Digest32::of_bytes(&bytes),
        objective_digest: objective(),
    }
}

fn tick() -> NeuronTickInputV1 {
    let feature_vector_q24 = vec![Q / 4, Q / 8, -Q / 8];
    NeuronTickInputV1 {
        tick_id: checked(StableId::new("tick.product.1")),
        subject_id: subject(),
        logical_sequence: 1,
        monotonic_time_micros: 1_000,
        checkpoint_digest: Digest32::ZERO,
        input_feature_digest: canonical_feature_vector_digest_v1(&feature_vector_q24),
        feature_vector_q24,
        objective_digest: objective(),
        ndu_snapshot_digest: Digest32::of_bytes(b"ndu"),
        body_generation: Some(1),
        modulator_digest: None,
    }
}

fn grant() -> ResourceGrant {
    ResourceGrant {
        grant_id: "grant.neuron.1".to_string(),
        authority_epoch: 1,
        generation: 1,
        expires_at_ms: 10_000,
        revoked: false,
        maximum_models: 1,
        maximum_active_requests: 2,
        maximum_memory_bytes: 1 << 20,
        semantic_digest: Digest32::of_bytes(b"grant").to_string(),
    }
}

fn manifest(config: &NeuronRuntimeConfigV1) -> ModelManifest {
    ModelManifest {
        model_id: config.model_id.to_string(),
        model_digest: Digest32::of_bytes(b"model-tuple").to_string(),
        weights_digest: config.weights_digest.to_string(),
        tokenizer_digest: Digest32::of_bytes(b"tokenizer").to_string(),
        preprocessor_digest: Digest32::of_bytes(b"preprocessor").to_string(),
        quantization_digest: Digest32::of_bytes(b"quantization").to_string(),
        runtime_digest: Digest32::of_bytes(b"runtime").to_string(),
        device_digest: Digest32::of_bytes(b"device").to_string(),
        maximum_tokens: 64,
    }
}

fn authorization(manifest: &ModelManifest) -> WorkerRequest {
    WorkerRequest {
        request_id: "request.neuron.1".to_string(),
        reservation_id: "reservation.neuron.1".to_string(),
        model_digest: manifest.model_digest.clone(),
        payload_digest: Digest32::of_bytes(b"placeholder").to_string(),
        maximum_tokens: 1,
        deadline_ms: 9_000,
        lease_payload_digest: Digest32::of_bytes(b"placeholder").to_string(),
        reservation_model_digest: manifest.model_digest.clone(),
        reservation_maximum_tokens: 1,
        cancelled: false,
    }
}

fn setup() -> (
    Fixture,
    NeuronRuntime<MemoryWitness>,
    InferenceWorker<Driver>,
    ModelManifest,
) {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        native,
        scope(),
        /*max_records*/ 16,
        config.clone(),
        MemoryWitness::default(),
    ));
    let expected_manifest = manifest(&config);
    let mut worker = checked(InferenceWorker::new(
        100,
        "worker.neuron.1".to_string(),
        1,
        grant(),
        Driver,
    ));
    checked(worker.load_model(100, expected_manifest.clone()));
    (fixture, runtime, worker, expected_manifest)
}

#[test]
fn product_caller_consumes_real_loaded_manifest_and_commits_neuron_tick() {
    let (_fixture, mut runtime, mut worker, manifest) = setup();
    let tick = tick();
    let mut authorization = authorization(&manifest);
    let payload =
        checked(expected_neuron_worker_payload_digest_v1(&runtime, &tick, &authorization));
    authorization.payload_digest = payload.clone();
    authorization.lease_payload_digest = payload;
    let output = checked(run_neuron_tick_v1(
        &mut runtime,
        &mut worker,
        AuthorizedNeuronTickV1 {
            now_ms: 100,
            authorization,
            tick,
        },
    ));
    assert_eq!(output.model_runtime.weights_digest.to_string(), manifest.weights_digest);
    assert_eq!(
        output.model_runtime.tokenizer_digest.to_string(),
        manifest.tokenizer_digest
    );
    assert!(!output.tick.abstain);
    assert!(!output.signal.authority.grants_any());
    assert!(checked(runtime.current_anchor()).is_some());
}

#[test]
fn product_caller_rejects_unbound_lease_without_mutating_checkpoint() {
    let (_fixture, mut runtime, mut worker, manifest) = setup();
    let tick = tick();
    let authorization = authorization(&manifest);
    assert_eq!(
        run_neuron_tick_v1(
            &mut runtime,
            &mut worker,
            AuthorizedNeuronTickV1 {
                now_ms: 100,
                authorization,
                tick,
            },
        )
        .err(),
        Some(NeuronRuntimeError::Model(NeuronModelError::Rejected))
    );
    assert_eq!(checked(runtime.current_anchor()), None);
}

#[test]
fn product_caller_rejects_loaded_weights_drift_before_commit() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        native,
        scope(),
        /*max_records*/ 16,
        config.clone(),
        MemoryWitness::default(),
    ));
    let mut changed_manifest = manifest(&config);
    changed_manifest.weights_digest = Digest32::of_bytes(b"other-weights").to_string();
    let mut worker = checked(InferenceWorker::new(
        100,
        "worker.neuron.2".to_string(),
        1,
        grant(),
        Driver,
    ));
    checked(worker.load_model(100, changed_manifest.clone()));
    let tick = tick();
    let mut authorization = authorization(&changed_manifest);
    let payload =
        checked(expected_neuron_worker_payload_digest_v1(&runtime, &tick, &authorization));
    authorization.payload_digest = payload.clone();
    authorization.lease_payload_digest = payload;
    assert_eq!(
        run_neuron_tick_v1(
            &mut runtime,
            &mut worker,
            AuthorizedNeuronTickV1 {
                now_ms: 100,
                authorization,
                tick,
            },
        )
        .err(),
        Some(NeuronRuntimeError::Model(NeuronModelError::Rejected))
    );
    assert_eq!(checked(runtime.current_anchor()), None);
}
