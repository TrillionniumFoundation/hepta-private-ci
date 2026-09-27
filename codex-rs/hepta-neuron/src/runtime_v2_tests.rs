use super::*;

use std::fs;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

const Q: i64 = 1 << 24;
static NEXT: AtomicU64 = AtomicU64::new(1);

fn checked<T, E: std::fmt::Debug>(value: Result<T, E>) -> T {
    match value {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-neuron-runtime-v2-{}-{serial}",
            std::process::id()
        ));
        checked(fs::create_dir(&root));
        Self(root)
    }

    fn store(&self) -> PathBuf {
        self.0.join("generation.hptngs02")
    }

    fn index(&self) -> PathBuf {
        self.0.join("runtime-index.hptngi02")
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[derive(Clone, Default)]
struct MemoryWitness {
    current: Arc<Mutex<Option<JournalAnchor>>>,
    lose_next_ack: Arc<AtomicBool>,
}

impl MemoryWitness {
    fn lose_next_ack(&self) {
        self.lose_next_ack.store(true, Ordering::SeqCst);
    }
}

impl AnchorWitnessStore for MemoryWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.current
            .lock()
            .map(|value| *value)
            .map_err(|_| WitnessStoreError::Unavailable)
    }

    fn admit_new_anchor(&self, expected: Option<JournalAnchor>) -> Result<(), WitnessStoreError> {
        if self.current()? == expected {
            Ok(())
        } else {
            Err(WitnessStoreError::Conflict)
        }
    }

    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        let mut current = self
            .current
            .lock()
            .map_err(|_| WitnessStoreError::Unavailable)?;
        if *current != expected {
            return Err(WitnessStoreError::Conflict);
        }
        *current = Some(next);
        if self.lose_next_ack.swap(false, Ordering::SeqCst) {
            return Err(WitnessStoreError::Indeterminate);
        }
        Ok(())
    }
}

struct Allow;

impl NeuronAdmissionGuard for Allow {
    fn check(
        &mut self,
        _config: &NeuronRuntimeConfigV1,
        _input: &NeuronTickInputV1,
    ) -> Result<(), NeuronAdmissionError> {
        Ok(())
    }
}

struct FakeDurableModel {
    calls: Arc<AtomicUsize>,
    transient_allocation_bytes: u64,
}

impl FakeDurableModel {
    fn new(calls: Arc<AtomicUsize>) -> Self {
        Self {
            calls,
            transient_allocation_bytes: 8_192,
        }
    }
}

impl NeuronModelPort for FakeDurableModel {
    fn execute(
        &mut self,
        request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        let drive_q24 = (0..request.expected_output_width)
            .map(|index| match index {
                0 => Q,
                1 => Q / 2,
                _ => 0,
            })
            .collect::<Vec<_>>();
        let prediction_q24 = vec![0; request.expected_output_width];
        let runtime_receipt = LocalModelRuntimeReceiptV1 {
            model_id: request.model_id.clone(),
            model_manifest_digest: digest("manifest"),
            weights_digest: request.weights_digest,
            tokenizer_digest: digest("tokenizer"),
            preprocessor_digest: digest("preprocessor"),
            quantization_id: id("q8"),
            quantization_digest: digest("quantization"),
            backend_id: id("cpu.reference"),
            runtime_digest: digest("runtime"),
            device_identity_digest: digest("device"),
            latency_micros: 50,
            resident_bytes: 4_096,
        };
        let output_digest = checked(canonical_model_output_digest_v1(
            &drive_q24,
            &prediction_q24,
            &runtime_receipt,
        ));
        Ok(NeuronModelOutputV1 {
            encoder_digest: request.encoder_digest,
            head_digest: request.head_digest,
            output_digest,
            drive_q24,
            prediction_q24,
            queue_age_micros: 7,
            transient_allocation_bytes: self.transient_allocation_bytes,
            runtime_receipt,
        })
    }
}

impl DurableNeuronModelPort for FakeDurableModel {}

fn digest(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

fn id(label: &str) -> StableId {
    checked(StableId::new(label))
}

fn native_config() -> SparseConfig {
    SparseConfig {
        model_digest: digest("head"),
        normalization_digest: digest("normalization"),
        generation: checked(Generation::new(1)),
        width: 5,
        top_k: 1,
        temporal_decay_q24: Q / 2,
        inhibition_gain_q24: Q,
        inhibition: Vec::new(),
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
        config_id: id("neuron.config.1"),
        generation: native.generation,
        model_id: id("model.1"),
        model_manifest_digest: digest("manifest"),
        encoder_digest: digest("encoder"),
        head_digest: native.model_digest,
        weights_digest: digest("weights"),
        tokenizer_digest: digest("tokenizer"),
        preprocessor_digest: digest("preprocessor"),
        quantization_digest: digest("quantization"),
        runtime_digest: digest("runtime"),
        device_digest: digest("device"),
        normalization_digest: native.normalization_digest,
        native_config_digest: checked(native.digest()),
        input_feature_dimension: 3,
        state_width: native.width,
        modulator_dimension: 4,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: digest("calibration"),
            ood_artifact_digest: digest("ood"),
            generation: native.generation,
            valid_from_sequence: 1,
            expires_after_sequence: 32,
            zero_confidence_error_q24: 16 * Q,
            maximum_in_domain_error_q24: 8 * Q,
            minimum_confidence_ppm: 500_000,
            maximum_ood_ppm: 500_000,
            minimum_active_ppm: 100_000,
            maximum_active_ppm: 300_000,
            maximum_projection_count: 8,
            measured_ece_ppm: 10_000,
            maximum_ece_ppm: 50_000,
            measured_false_acceptance_ppm: 5_000,
            maximum_false_acceptance_ppm: 20_000,
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

fn body_bundle(generation: Generation) -> NeuronBodyBundleIdentityV1 {
    NeuronBodyBundleIdentityV1 {
        body_manifest_digest: digest("body-manifest"),
        body_generation: generation,
        base_bundle_digest: digest("base-bundle"),
        organ_id: id("organ.reasoning"),
        organ_bundle_digest: digest("organ-bundle"),
        cell_slot_id: Some(id("cell.temporal.1")),
        cell_bundle_digest: Some(digest("cell-bundle")),
        effective_parameter_digest: digest("effective-parameters"),
        source_revision_digest: digest("source-revision"),
    }
}

fn subject() -> StableId {
    id("subject.1")
}

fn objective() -> Digest32 {
    digest("objective")
}

fn scope() -> JournalScope {
    JournalScope {
        scope_digest: checked(subject_scope_digest(&subject())),
        objective_digest: objective(),
    }
}

fn contexts(
    native: &SparseConfig,
    config: &NeuronRuntimeConfigV1,
    body: &NeuronBodyBundleIdentityV1,
) -> (NeuronGenerationStoreContextV2, NeuronRuntimeIndexContextV2) {
    let config_digest = checked(config.semantic_digest());
    let body_digest = checked(body.semantic_digest());
    (
        NeuronGenerationStoreContextV2 {
            generation: native.generation,
            scope: scope(),
            runtime_config_digest: config_digest,
            body_bundle_digest: body_digest,
            max_records: 16,
            max_pending_witness: 16,
            max_checkpoint_bytes: 256 * 1024,
            max_full_receipt_bytes: 256 * 1024,
            max_file_bytes: 8 * 1024 * 1024,
            max_startup_replay_bytes: 8 * 1024 * 1024,
        },
        NeuronRuntimeIndexContextV2 {
            generation: native.generation,
            scope: scope(),
            runtime_config_digest: config_digest,
            body_bundle_digest: body_digest,
            max_records: 16,
            max_file_bytes: 1024 * 1024,
            max_startup_replay_bytes: 1024 * 1024,
        },
    )
}

fn input(sequence: u64, checkpoint_digest: Digest32) -> NeuronTickInputV1 {
    let feature_vector_q24 = vec![Q / 4, Q / 8, -Q / 8];
    NeuronTickInputV1 {
        tick_id: id(&format!("tick.{sequence}")),
        subject_id: subject(),
        logical_sequence: sequence,
        monotonic_time_micros: sequence * 1_000,
        checkpoint_digest,
        input_feature_digest: canonical_feature_vector_digest_v1(&feature_vector_q24),
        feature_vector_q24,
        objective_digest: objective(),
        ndu_snapshot_digest: digest("ndu"),
        body_generation: Some(1),
        modulator_digest: None,
    }
}

#[test]
fn exact_retry_and_restart_return_the_original_full_receipt_once() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let body = body_bundle(native.generation);
    let (store_context, index_context) = contexts(&native, &config, &body);
    let witness = MemoryWitness::default();
    let mut runtime = checked(NeuronRuntimeV2::bootstrap(
        &fixture.store(),
        &fixture.index(),
        native.clone(),
        scope(),
        config.clone(),
        body.clone(),
        store_context.clone(),
        index_context.clone(),
        witness.clone(),
    ));
    let calls = Arc::new(AtomicUsize::new(0));
    let mut model = FakeDurableModel::new(Arc::clone(&calls));
    let request = input(1, Digest32::ZERO);
    let first = checked(runtime.tick_guarded(&mut model, request.clone(), &mut Allow));
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert!(matches!(
        first.disposition,
        NeuronCommitDispositionV1::CommittedReady
    ));
    assert_eq!(
        checked(runtime.tick_guarded(&mut model, request.clone(), &mut Allow)),
        first
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    drop(runtime);

    let mut recovered = checked(NeuronRuntimeV2::recover(
        &fixture.store(),
        &fixture.index(),
        native,
        scope(),
        config,
        body,
        store_context,
        index_context,
        witness,
    ));
    assert_eq!(
        checked(recovered.tick_guarded(&mut model, request, &mut Allow)),
        first
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

#[test]
fn same_tick_with_changed_input_conflicts_without_model_reexecution() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let body = body_bundle(native.generation);
    let (store_context, index_context) = contexts(&native, &config, &body);
    let mut runtime = checked(NeuronRuntimeV2::bootstrap(
        &fixture.store(),
        &fixture.index(),
        native,
        scope(),
        config,
        body,
        store_context,
        index_context,
        MemoryWitness::default(),
    ));
    let calls = Arc::new(AtomicUsize::new(0));
    let mut model = FakeDurableModel::new(Arc::clone(&calls));
    let request = input(1, Digest32::ZERO);
    checked(runtime.tick_guarded(&mut model, request.clone(), &mut Allow));
    let mut changed = request;
    changed.feature_vector_q24[0] += 1;
    changed.input_feature_digest = canonical_feature_vector_digest_v1(&changed.feature_vector_q24);
    assert!(matches!(
        runtime.tick_guarded(&mut model, changed, &mut Allow),
        Err(NeuronRuntimeV2Error::Index(
            NeuronRuntimeIndexError::Conflict
        ))
    ));
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

#[test]
fn unpredictable_resource_excess_is_committed_degraded() {
    let fixture = Fixture::new();
    let native = native_config();
    let mut config = runtime_config(&native);
    config.resource_envelope.transient_allocation_bytes = 1;
    let body = body_bundle(native.generation);
    let (store_context, index_context) = contexts(&native, &config, &body);
    let mut runtime = checked(NeuronRuntimeV2::bootstrap(
        &fixture.store(),
        &fixture.index(),
        native,
        scope(),
        config,
        body,
        store_context,
        index_context,
        MemoryWitness::default(),
    ));
    let calls = Arc::new(AtomicUsize::new(0));
    let mut model = FakeDurableModel::new(calls);
    let committed = checked(runtime.tick_guarded(
        &mut model,
        input(1, Digest32::ZERO),
        &mut Allow,
    ));
    assert!(matches!(
        committed.disposition,
        NeuronCommitDispositionV1::CommittedDegraded { .. }
    ));
    assert!(committed.output.tick.abstain);
}

#[test]
fn expired_calibration_rejects_before_model_and_index_mutation() {
    let fixture = Fixture::new();
    let native = native_config();
    let mut config = runtime_config(&native);
    config.calibration.valid_from_sequence = 2;
    let body = body_bundle(native.generation);
    let (store_context, index_context) = contexts(&native, &config, &body);
    let mut runtime = checked(NeuronRuntimeV2::bootstrap(
        &fixture.store(),
        &fixture.index(),
        native,
        scope(),
        config,
        body,
        store_context,
        index_context,
        MemoryWitness::default(),
    ));
    let calls = Arc::new(AtomicUsize::new(0));
    let mut model = FakeDurableModel::new(Arc::clone(&calls));
    assert!(matches!(
        runtime.tick_guarded(&mut model, input(1, Digest32::ZERO), &mut Allow),
        Err(NeuronRuntimeV2Error::Configuration(
            NeuronRuntimeError::CalibrationExpired
        ))
    ));
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    assert_eq!(checked(runtime.index.pending()), None);
    assert!(checked(runtime.index.records()).is_empty());
}

#[test]
fn committed_store_with_lost_index_ack_recovers_without_second_model_call() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let body = body_bundle(native.generation);
    let (store_context, index_context) = contexts(&native, &config, &body);
    let witness = MemoryWitness::default();
    let mut runtime = checked(NeuronRuntimeV2::bootstrap(
        &fixture.store(),
        &fixture.index(),
        native.clone(),
        scope(),
        config.clone(),
        body.clone(),
        store_context.clone(),
        index_context.clone(),
        witness.clone(),
    ));
    let request = input(1, Digest32::ZERO);
    let key = NeuronOperationKeyV2 {
        tick_id: request.tick_id.clone(),
        input_semantic_digest: checked(request.semantic_digest()),
    };
    checked(runtime.index.prepare(key, None));
    runtime.index.fail_next_append_after_sync();
    let calls = Arc::new(AtomicUsize::new(0));
    let mut model = FakeDurableModel::new(Arc::clone(&calls));
    assert!(matches!(
        runtime.tick_guarded(&mut model, request.clone(), &mut Allow),
        Err(NeuronRuntimeV2Error::Index(
            NeuronRuntimeIndexError::Indeterminate
        ))
    ));
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    drop(runtime);

    let mut recovered = checked(NeuronRuntimeV2::recover(
        &fixture.store(),
        &fixture.index(),
        native,
        scope(),
        config,
        body,
        store_context,
        index_context,
        witness,
    ));
    checked(recovered.tick_guarded(&mut model, request, &mut Allow));
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

#[test]
fn lost_witness_ack_is_read_back_and_does_not_repeat_model() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let body = body_bundle(native.generation);
    let (store_context, index_context) = contexts(&native, &config, &body);
    let witness = MemoryWitness::default();
    witness.lose_next_ack();
    let mut runtime = checked(NeuronRuntimeV2::bootstrap(
        &fixture.store(),
        &fixture.index(),
        native,
        scope(),
        config,
        body,
        store_context,
        index_context,
        witness,
    ));
    let calls = Arc::new(AtomicUsize::new(0));
    let mut model = FakeDurableModel::new(Arc::clone(&calls));
    let request = input(1, Digest32::ZERO);
    let first = checked(runtime.tick_guarded(&mut model, request.clone(), &mut Allow));
    assert_eq!(checked(runtime.pending_witness_count()), 0);
    assert_eq!(
        checked(runtime.tick_guarded(&mut model, request, &mut Allow)),
        first
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}
