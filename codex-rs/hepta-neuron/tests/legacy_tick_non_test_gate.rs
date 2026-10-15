//! Real external Cargo integration linkage: the Neuron library is compiled
//! WITHOUT cfg(test), even though this test binary itself is a test harness.
//! A fabricated local model driver can never obtain production Final-use by
//! calling the legacy public NeuronRuntime::tick method.

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::NeuronCalibrationProfileV1;
use codex_hepta_neuron::NeuronModelError;
use codex_hepta_neuron::NeuronModelOutputV1;
use codex_hepta_neuron::NeuronModelPort;
use codex_hepta_neuron::NeuronModelRequestV1;
use codex_hepta_neuron::NeuronResourceEnvelopeV1;
use codex_hepta_neuron::NeuronRuntime;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::NeuronRuntimeError;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_neuron::WitnessStoreError;
use codex_hepta_neuron::canonical_feature_vector_digest_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

const Q24: i64 = 1 << 24;

fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("non-test gate fixture could not construct: {error:?}"),
    }
}

struct PrivateJournalRoot(PathBuf);
impl PrivateJournalRoot {
    fn create() -> Self {
        let serial = checked(SystemTime::now().duration_since(UNIX_EPOCH)).as_nanos();
        let root = std::env::temp_dir().join(format!(
            "hepta-neuron-legacy-non-test-{}-{serial}",
            std::process::id()
        ));
        checked(fs::create_dir(&root));
        Self(root)
    }
    fn journal(&self) -> File {
        checked(
            OpenOptions::new()
                .read(true)
                .write(true)
                .create_new(true)
                .open(self.0.join("journal")),
        )
    }
}
impl Drop for PrivateJournalRoot {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

struct NeverAuthorizingWitness;
impl AnchorWitnessStore for NeverAuthorizingWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        Ok(None)
    }
    fn compare_and_swap(
        &mut self,
        _expected: Option<JournalAnchor>,
        _next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        Err(WitnessStoreError::Unavailable)
    }
}

struct UntrustedModel {
    calls: usize,
}
impl NeuronModelPort for UntrustedModel {
    fn execute(
        &mut self,
        _request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        self.calls += 1;
        Err(NeuronModelError::Indeterminate)
    }
}

fn native() -> SparseConfig {
    SparseConfig {
        model_digest: Digest32::of_bytes(b"local-head"),
        normalization_digest: Digest32::of_bytes(b"normalizer"),
        generation: checked(Generation::new(1)),
        width: 5,
        top_k: 1,
        temporal_decay_q24: Q24 / 2,
        inhibition_gain_q24: Q24,
        inhibition: vec![],
        activity_decay_q24: 0,
        target_activity_q24: Q24 / 8,
        threshold_rate_q24: Q24 / 8,
        threshold_min_q24: -Q24,
        threshold_max_q24: Q24,
        eligibility_decay_q24: Q24 / 2,
    }
}

fn configuration(n: &SparseConfig) -> NeuronRuntimeConfigV1 {
    NeuronRuntimeConfigV1 {
        config_id: checked(StableId::new("neuron.legacy.test")),
        generation: n.generation,
        model_id: checked(StableId::new("model.untrusted")),
        model_manifest_digest: Digest32::of_bytes(b"manifest"),
        encoder_digest: Digest32::of_bytes(b"encoder"),
        head_digest: n.model_digest,
        weights_digest: Digest32::of_bytes(b"weights"),
        tokenizer_digest: Digest32::of_bytes(b"tokenizer"),
        preprocessor_digest: Digest32::of_bytes(b"preprocessor"),
        quantization_digest: Digest32::of_bytes(b"quantization"),
        runtime_digest: Digest32::of_bytes(b"runtime"),
        device_digest: Digest32::of_bytes(b"device"),
        normalization_digest: n.normalization_digest,
        native_config_digest: checked(n.digest()),
        input_feature_dimension: 3,
        state_width: n.width,
        modulator_dimension: 4,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: Digest32::of_bytes(b"calibration"),
            ood_artifact_digest: Digest32::of_bytes(b"ood"),
            generation: n.generation,
            valid_from_sequence: 1,
            expires_after_sequence: 32,
            zero_confidence_error_q24: 16 * Q24,
            maximum_in_domain_error_q24: 8 * Q24,
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

#[test]
fn legacy_neuron_tick_cannot_invoke_untrusted_model_in_non_test_library() {
    let directory = PrivateJournalRoot::create();
    let native = native();
    let objective = Digest32::of_bytes(b"objective");
    let scope = JournalScope {
        scope_digest: Digest32::of_bytes(b"registered.scope"),
        objective_digest: objective,
    };
    let config = configuration(&native);
    let mut runtime = checked(NeuronRuntime::bootstrap(
        directory.journal(),
        native,
        scope,
        16,
        config,
        NeverAuthorizingWitness,
    ));
    let features = vec![Q24 / 4, Q24 / 8, -Q24 / 8];
    let input = NeuronTickInputV1 {
        tick_id: checked(StableId::new("tick.1")),
        subject_id: checked(StableId::new("subject.1")),
        logical_sequence: 1,
        monotonic_time_micros: 1000,
        checkpoint_digest: Digest32::ZERO,
        input_feature_digest: canonical_feature_vector_digest_v1(&features),
        feature_vector_q24: features,
        objective_digest: objective,
        ndu_snapshot_digest: Digest32::of_bytes(b"untrusted-ndu"),
        body_generation: Some(1),
        modulator_digest: None,
    };
    let mut model = UntrustedModel { calls: 0 };
    let rejected = runtime.tick(&mut model, input);
    assert!(
        matches!(rejected, Err(NeuronRuntimeError::MissingFinalUseAuthorization)),
        "a non-test library must reject the legacy Tick before even preparing a model request"
    );
    assert_eq!(model.calls, 0, "untrusted driver must never be invoked");
    assert!(
        checked(runtime.current_anchor()).is_none(),
        "denied Tick may not append to the original Neuron journal"
    );
}
