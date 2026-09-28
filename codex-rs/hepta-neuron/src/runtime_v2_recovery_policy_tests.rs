use super::*;

use std::fs;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_types::Generation;

use crate::LocalModelRuntimeReceiptV1;
use crate::NeuronCalibrationProfileV1;
use crate::NeuronResourceEnvelopeV1;
use crate::canonical_feature_vector_digest_v1;
use crate::canonical_model_output_digest_v1;

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
            "hepta-neuron-runtime-v2-recovery-policy-{}-{serial}",
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

struct Deny;

impl NeuronAdmissionGuard for Deny {
    fn check(
        &mut self,
        _config: &NeuronRuntimeConfigV1,
        _input: &NeuronTickInputV1,
    ) -> Result<(), NeuronAdmissionError> {
        Err(NeuronAdmissionError::Revoked)
    }
}

struct RevokeAtFinalUse {
    checks: usize,
}

impl NeuronAdmissionGuard for RevokeAtFinalUse {
    fn check(
        &mut self,
        _config: &NeuronRuntimeConfigV1,
        _input: &NeuronTickInputV1,
    ) -> Result<(), NeuronAdmissionError> {
        self.checks += 1;
        if self.checks >= 3 {
            Err(NeuronAdmissionError::Revoked)
        } else {
            Ok(())
        }
    }
}

struct ValidModel {
    execute_calls: Arc<AtomicUsize>,
}

impl NeuronModelPort for ValidModel {
    fn execute(
        &mut self,
        request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        self.execute_calls.fetch_add(1, Ordering::SeqCst);
        Ok(valid_output(request))
    }
}

impl DurableNeuronModelPort for ValidModel {}

struct RecoverableModel {
    execute_calls: Arc<AtomicUsize>,
    reconcile_calls: Arc<AtomicUsize>,
}

impl NeuronModelPort for RecoverableModel {
    fn execute(
        &mut self,
        _request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        self.execute_calls.fetch_add(1, Ordering::SeqCst);
        Err(NeuronModelError::Indeterminate)
    }
}

impl DurableNeuronModelPort for RecoverableModel {
    fn reconcile(
        &mut self,
        request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelResolutionV2, NeuronModelError> {
        self.reconcile_calls.fetch_add(1, Ordering::SeqCst);
        Ok(NeuronModelResolutionV2::Observed(Box::new(valid_output(
            request,
        ))))
    }
}

struct CountingNotStartedModel {
    execute_calls: Arc<AtomicUsize>,
    reconcile_calls: Arc<AtomicUsize>,
}

impl NeuronModelPort for CountingNotStartedModel {
    fn execute(
        &mut self,
        _request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        self.execute_calls.fetch_add(1, Ordering::SeqCst);
        Err(NeuronModelError::Indeterminate)
    }
}

impl DurableNeuronModelPort for CountingNotStartedModel {
    fn reconcile(
        &mut self,
        _request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelResolutionV2, NeuronModelError> {
        self.reconcile_calls.fetch_add(1, Ordering::SeqCst);
        Ok(NeuronModelResolutionV2::NotStarted)
    }
}

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
        config_id: id("neuron.config.recovery"),
        generation: native.generation,
        model_id: id("model.recovery"),
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
        cell_slot_id: Some(id("cell.temporal.recovery")),
        cell_bundle_digest: Some(digest("cell-bundle")),
        effective_parameter_digest: digest("effective-parameters"),
        source_revision_digest: digest("source-revision"),
    }
}

fn subject() -> StableId {
    id("subject.recovery")
}

fn objective() -> Digest32 {
    digest("objective.recovery")
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

fn input() -> NeuronTickInputV1 {
    let feature_vector_q24 = vec![Q / 4, Q / 8, -Q / 8];
    NeuronTickInputV1 {
        tick_id: id("tick.recovery.1"),
        subject_id: subject(),
        logical_sequence: 1,
        monotonic_time_micros: 1_000,
        checkpoint_digest: Digest32::ZERO,
        input_feature_digest: canonical_feature_vector_digest_v1(&feature_vector_q24),
        feature_vector_q24,
        objective_digest: objective(),
        ndu_snapshot_digest: digest("ndu.recovery"),
        body_generation: Some(1),
        modulator_digest: None,
    }
}

fn valid_output(request: &NeuronModelRequestV1) -> NeuronModelOutputV1 {
    let drive_q24 = vec![Q, Q / 2, 0, 0, 0];
    let prediction_q24 = vec![0; request.expected_output_width];
    let runtime_receipt = LocalModelRuntimeReceiptV1 {
        model_id: request.model_id.clone(),
        model_manifest_digest: digest("manifest"),
        weights_digest: request.weights_digest,
        tokenizer_digest: digest("tokenizer"),
        preprocessor_digest: digest("preprocessor"),
        quantization_id: id("q8"),
        quantization_digest: digest("quantization"),
        backend_id: id("cpu.recovery.fixture"),
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
    NeuronModelOutputV1 {
        encoder_digest: request.encoder_digest,
        head_digest: request.head_digest,
        output_digest,
        drive_q24,
        prediction_q24,
        queue_age_micros: 7,
        transient_allocation_bytes: 8_192,
        runtime_receipt,
    }
}

fn bootstrap(fixture: &Fixture) -> NeuronRuntimeV2<MemoryWitness> {
    let native = native_config();
    let config = runtime_config(&native);
    let body = body_bundle(native.generation);
    let (store_context, index_context) = contexts(&native, &config, &body);
    checked(NeuronRuntimeV2::bootstrap(
        &fixture.store(),
        &fixture.index(),
        native,
        scope(),
        config,
        body,
        store_context,
        index_context,
        MemoryWitness::default(),
    ))
}

#[test]
fn revocation_after_provider_observation_preserves_truth_but_denies_release() {
    let fixture = Fixture::new();
    let mut runtime = bootstrap(&fixture);
    let execute_calls = Arc::new(AtomicUsize::new(0));
    let mut model = ValidModel {
        execute_calls: Arc::clone(&execute_calls),
    };
    let request = input();
    let mut guard = RevokeAtFinalUse { checks: 0 };

    assert!(matches!(
        runtime.tick_guarded(&mut model, request.clone(), &mut guard),
        Err(NeuronRuntimeV2Error::Admission(
            NeuronAdmissionError::Revoked
        ))
    ));
    assert_eq!(execute_calls.load(Ordering::SeqCst), 1);
    assert!(matches!(
        checked(runtime.query_input_operation(&request)),
        NeuronOperationStatusV2::Committed { .. }
    ));
    assert!(matches!(
        runtime.query_result_guarded(&request, &mut Deny),
        Err(NeuronRuntimeV2Error::Admission(
            NeuronAdmissionError::Revoked
        ))
    ));
    assert!(checked(runtime.query_result_guarded(&request, &mut Allow)).is_some());
}

#[test]
fn recovery_converges_observed_provider_result_without_redispatch() {
    let fixture = Fixture::new();
    let mut runtime = bootstrap(&fixture);
    let execute_calls = Arc::new(AtomicUsize::new(0));
    let reconcile_calls = Arc::new(AtomicUsize::new(0));
    let mut model = RecoverableModel {
        execute_calls: Arc::clone(&execute_calls),
        reconcile_calls: Arc::clone(&reconcile_calls),
    };
    let request = input();

    assert!(matches!(
        runtime.tick_guarded(&mut model, request.clone(), &mut Allow),
        Err(NeuronRuntimeV2Error::Model(
            NeuronModelError::Indeterminate
        ))
    ));
    assert_eq!(execute_calls.load(Ordering::SeqCst), 1);
    assert_eq!(reconcile_calls.load(Ordering::SeqCst), 0);
    assert_eq!(
        checked(runtime.query_input_operation(&request)),
        NeuronOperationStatusV2::OutcomeUnknown
    );

    let recovered = checked(runtime.recover_operation(&mut model, &request));
    assert!(matches!(
        recovered,
        NeuronOperationStatusV2::Committed { .. }
    ));
    assert_eq!(execute_calls.load(Ordering::SeqCst), 1);
    assert_eq!(reconcile_calls.load(Ordering::SeqCst), 1);
    let measurement = runtime.last_measurement().expect("recovery measurement");
    assert!(measurement.recovery_only);
    assert!(measurement.checkpoint_payload_bytes > 0);
    assert!(measurement.full_receipt_bytes > 0);
    assert!(measurement.measured_sync_micros() <= measurement.total_micros);
    assert!(measurement.store_non_sync_micros() <= measurement.store_commit_micros);
    assert!(measurement.index_non_sync_micros() <= measurement.index_commit_micros);
    assert!(matches!(
        runtime.query_result_guarded(&request, &mut Deny),
        Err(NeuronRuntimeV2Error::Admission(
            NeuronAdmissionError::Revoked
        ))
    ));
}

#[test]
fn quiesce_recovery_closes_reserved_not_executed_without_provider_call() {
    let fixture = Fixture::new();
    let mut runtime = bootstrap(&fixture);
    let request = input();
    let key = NeuronOperationKeyV2 {
        tick_id: request.tick_id.clone(),
        input_semantic_digest: checked(request.semantic_digest()),
    };
    checked(runtime.index.prepare(key, None));
    let execute_calls = Arc::new(AtomicUsize::new(0));
    let reconcile_calls = Arc::new(AtomicUsize::new(0));
    let mut model = CountingNotStartedModel {
        execute_calls: Arc::clone(&execute_calls),
        reconcile_calls: Arc::clone(&reconcile_calls),
    };

    assert_eq!(
        checked(runtime.recover_operation(&mut model, &request)),
        NeuronOperationStatusV2::Failed(NeuronOperationFailureV2::AdmissionDenied)
    );
    assert_eq!(execute_calls.load(Ordering::SeqCst), 0);
    assert_eq!(reconcile_calls.load(Ordering::SeqCst), 0);
    assert_eq!(checked(runtime.pending_operation_status()), None);
}
