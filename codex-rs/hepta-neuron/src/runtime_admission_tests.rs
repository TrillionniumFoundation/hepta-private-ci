use super::*;

use std::fs;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

const Q: i64 = 1 << 24;
static NEXT: AtomicU64 = AtomicU64::new(0);

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture identity")
}

struct Fixture {
    path: PathBuf,
    native: SparseConfig,
    config: NeuronRuntimeConfigV1,
}

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "hepta-neuron-admission-{}-{serial}",
            std::process::id()
        ));
        fs::create_dir(&path).expect("private fixture directory");
        let generation = Generation::new(1).expect("generation");
        let native = SparseConfig {
            model_digest: digest("head"),
            normalization_digest: digest("normalization"),
            generation,
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
        };
        let config = NeuronRuntimeConfigV1 {
            config_id: id("config"),
            generation,
            model_id: id("model"),
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
            native_config_digest: native.digest().expect("native config"),
            input_feature_dimension: 1,
            state_width: native.width,
            modulator_dimension: 1,
            calibration: NeuronCalibrationProfileV1 {
                calibration_artifact_digest: digest("calibration"),
                ood_artifact_digest: digest("ood"),
                generation,
                valid_from_sequence: 1,
                expires_after_sequence: 16,
                zero_confidence_error_q24: 16 * Q,
                maximum_in_domain_error_q24: 8 * Q,
                minimum_confidence_ppm: 0,
                maximum_ood_ppm: 1_000_000,
                minimum_active_ppm: 0,
                maximum_active_ppm: 1_000_000,
                maximum_projection_count: 64,
                measured_ece_ppm: 0,
                maximum_ece_ppm: 50_000,
                measured_false_acceptance_ppm: 0,
                maximum_false_acceptance_ppm: 20_000,
            },
            resource_envelope: NeuronResourceEnvelopeV1 {
                p95_latency_micros: 1_000_000,
                p99_latency_micros: 10_000_000,
                transient_allocation_bytes: 1 << 20,
                checkpoint_bytes: 1 << 20,
                write_amplification_ppm: 4_000_000,
            },
        };
        Self { path, native, config }
    }

    fn file(&self, name: &str) -> File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(self.path.join(name))
            .expect("fixture file")
    }

    fn scope(&self) -> JournalScope {
        JournalScope {
            scope_digest: subject_scope_digest(&id("subject")).expect("scope"),
            objective_digest: digest("objective"),
        }
    }

    fn witness(&self) -> crate::FileAnchorWitnessStore {
        crate::FileAnchorWitnessStore::open(
            self.file("witness"),
            self.scope(),
            self.config.generation,
            /*max_records*/ 16,
        )
        .expect("file witness")
    }

    fn bootstrap(&self) -> NeuronRuntime<crate::FileAnchorWitnessStore> {
        NeuronRuntime::bootstrap(
            self.file("journal"),
            self.file("operations"),
            self.native.clone(),
            self.scope(),
            /*max_records*/ 16,
            /*max_operations*/ 16,
            self.config.clone(),
            self.witness(),
        )
        .expect("bootstrap")
    }

    fn recover(&self) -> NeuronRuntime<crate::FileAnchorWitnessStore> {
        NeuronRuntime::recover(
            self.file("journal"),
            self.file("operations"),
            self.native.clone(),
            self.scope(),
            /*max_records*/ 16,
            /*max_operations*/ 16,
            self.config.clone(),
            self.witness(),
        )
        .expect("recover")
    }

    fn bytes(&self) -> Vec<Vec<u8>> {
        ["journal", "operations", "witness"]
            .iter()
            .map(|name| fs::read(self.path.join(name)).expect("durable bytes"))
            .collect()
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.path);
    }
}

#[derive(Default)]
struct Model {
    calls: usize,
    allocation: u64,
}

impl NeuronModelPort for Model {
    fn execute(
        &mut self,
        request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        self.calls += 1;
        let runtime_receipt = LocalModelRuntimeReceiptV1 {
            model_id: request.model_id.clone(),
            model_manifest_digest: digest("manifest"),
            weights_digest: request.weights_digest,
            tokenizer_digest: digest("tokenizer"),
            preprocessor_digest: digest("preprocessor"),
            quantization_id: id("q8"),
            quantization_digest: digest("quantization"),
            backend_id: id("test.reference"),
            runtime_digest: digest("runtime"),
            device_identity_digest: digest("device"),
            latency_micros: 1,
            resident_bytes: 4096,
        };
        let mut drive_q24 = vec![0; request.expected_output_width];
        drive_q24[0] = Q;
        let prediction_q24 = vec![0; request.expected_output_width];
        let output_digest = canonical_model_output_digest_v1(
            &drive_q24,
            &prediction_q24,
            &runtime_receipt,
        )
        .expect("fixture output digest");
        Ok(NeuronModelOutputV1 {
            encoder_digest: request.encoder_digest,
            head_digest: request.head_digest,
            output_digest,
            drive_q24,
            prediction_q24,
            queue_age_micros: 0,
            transient_allocation_bytes: self.allocation,
            runtime_receipt,
        })
    }
}

fn input(sequence: u64, predecessor: Digest32) -> NeuronTickInputV1 {
    let features = vec![Q / 4];
    NeuronTickInputV1 {
        tick_id: id(&format!("tick.{sequence}")),
        subject_id: id("subject"),
        logical_sequence: sequence,
        monotonic_time_micros: sequence * 1000,
        checkpoint_digest: predecessor,
        input_feature_digest: canonical_feature_vector_digest_v1(&features),
        feature_vector_q24: features,
        objective_digest: digest("objective"),
        ndu_snapshot_digest: digest("ndu"),
        body_generation: Some(1),
        modulator_digest: None,
    }
}

#[test]
fn guarded_expiry_is_no_update_and_historical_result_survives_reopen() {
    let mut fixture = Fixture::new();
    fixture.config.calibration.expires_after_sequence = 1;
    let mut runtime = fixture.bootstrap();
    let mut model = Model::default();
    let first_input = input(1, Digest32::ZERO);
    let first = runtime
        .tick_guarded(&mut model, first_input.clone(), &mut MechanismOnly)
        .expect("first product tick");
    let before = fixture.bytes();
    let expired = input(2, first.tick.checkpoint_after);
    assert_eq!(
        runtime.tick_guarded(&mut model, expired.clone(), &mut MechanismOnly),
        Err(NeuronRuntimeError::CalibrationExpired)
    );
    assert_eq!(fixture.bytes(), before);
    assert_eq!(model.calls, 1);
    drop(runtime);
    let mut reopened = fixture.recover();
    assert_eq!(
        reopened.tick_guarded(&mut model, first_input, &mut MechanismOnly),
        Ok(first)
    );
    assert_eq!(
        reopened.tick_guarded(&mut model, expired, &mut MechanismOnly),
        Err(NeuronRuntimeError::CalibrationExpired)
    );
    assert_eq!(model.calls, 1);
    assert_eq!(fixture.bytes(), before);
}

#[test]
fn clock_regression_rejects_before_model_and_leaves_all_stores_unchanged() {
    let fixture = Fixture::new();
    let mut runtime = fixture.bootstrap();
    let mut model = Model::default();
    let first = runtime
        .tick_guarded(&mut model, input(1, Digest32::ZERO), &mut MechanismOnly)
        .expect("first tick");
    let mut second = input(2, first.tick.checkpoint_after);
    second.monotonic_time_micros = 1000;
    let before = fixture.bytes();
    assert_eq!(
        runtime.tick_guarded(&mut model, second, &mut MechanismOnly),
        Err(NeuronRuntimeError::Journal(JournalError::Mechanism(SparseError::Clock)))
    );
    assert_eq!(model.calls, 1);
    assert_eq!(fixture.bytes(), before);
}

#[test]
fn impossible_checkpoint_envelope_rejects_without_model_or_state_update() {
    let mut fixture = Fixture::new();
    fixture.config.resource_envelope.checkpoint_bytes = 1;
    let mut runtime = fixture.bootstrap();
    let mut model = Model::default();
    let before = fixture.bytes();
    assert_eq!(
        runtime.tick_guarded(&mut model, input(1, Digest32::ZERO), &mut MechanismOnly),
        Err(NeuronRuntimeError::InvalidConfig)
    );
    assert_eq!(model.calls, 0);
    assert_eq!(runtime.current_anchor().expect("anchor"), None);
    assert_eq!(fixture.bytes(), before);
}

#[test]
fn measured_allocation_overrun_is_a_replayable_committed_degraded_result() {
    let fixture = Fixture::new();
    let mut runtime = fixture.bootstrap();
    let mut model = Model { calls: 0, allocation: 2 << 20 };
    let tick = input(1, Digest32::ZERO);
    let input_digest = tick.semantic_digest().expect("input digest");
    let result = runtime
        .tick_guarded(&mut model, tick.clone(), &mut MechanismOnly)
        .expect("durable degraded tick");
    assert!(result.tick.abstain);
    let expected = Some(NeuronCommitDispositionV1::CommittedDegraded {
        reasons: vec![DegradationReasonV1::AllocationEnvelope],
        abstain_reasons: vec![],
    });
    assert_eq!(
        runtime.query_committed_disposition(&tick.tick_id, input_digest).expect("disposition"),
        expected
    );
    drop(runtime);
    let mut reopened = fixture.recover();
    assert_eq!(
        reopened.query_committed_disposition(&tick.tick_id, input_digest).expect("recovered disposition"),
        expected
    );
    assert_eq!(
        reopened.tick_guarded(&mut model, tick, &mut MechanismOnly),
        Ok(result)
    );
    assert_eq!(model.calls, 1);
}

#[test]
fn legacy_expired_calibration_remains_explicit_state_advance_abstention() {
    let mut fixture = Fixture::new();
    fixture.config.calibration.expires_after_sequence = 1;
    let mut runtime = fixture.bootstrap();
    let mut model = Model::default();
    let first = runtime.tick(&mut model, input(1, Digest32::ZERO)).expect("first");
    let second = input(2, first.tick.checkpoint_after);
    let key = second.semantic_digest().expect("key");
    let output = runtime.tick(&mut model, second.clone()).expect("legacy tick");
    assert!(output.tick.abstain);
    assert_eq!(runtime.current_anchor().expect("anchor").expect("committed").sequence, 2);
    assert_eq!(
        runtime.query_committed_disposition(&second.tick_id, key).expect("legacy disposition"),
        Some(NeuronCommitDispositionV1::CommittedAbstained {
            reasons: vec![AbstainReasonV1::CalibrationExpiredLegacy],
        })
    );
}
