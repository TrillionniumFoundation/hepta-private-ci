//! Actual pinned Hepta NeuronRuntime configuration for six action signals.
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

pub const Q24: i64 = 1 << 24;
pub const LIMIT: usize = 64;
pub const ACTIONS: usize = 6;

pub fn marker(text: &str) -> Digest32 {
    Digest32::of_bytes(text.as_bytes())
}

pub fn id(text: &str) -> StableId {
    StableId::new(text).expect("bounded static identifier")
}

pub fn configuration(model: Digest32, input_width: usize) -> (SparseConfig, NeuronRuntimeConfigV1) {
    let generation = Generation::new(1).expect("generation one");
    let sparse = SparseConfig {
        model_digest: model,
        normalization_digest: model,
        generation,
        width: ACTIONS,
        top_k: 1,
        temporal_decay_q24: 0,
        inhibition_gain_q24: 0,
        inhibition: vec![],
        activity_decay_q24: 0,
        target_activity_q24: Q24 / ACTIONS as i64,
        threshold_rate_q24: 0,
        threshold_min_q24: 0,
        threshold_max_q24: 0,
        eligibility_decay_q24: 0,
    };
    let config = NeuronRuntimeConfigV1 {
        config_id: id("hepta.digital.preread.v1"),
        generation,
        model_id: id("hepta.digital.finite17.policy.v1"),
        model_manifest_digest: model,
        encoder_digest: marker("digital.public-no-posterior.v1"),
        head_digest: model,
        weights_digest: model,
        tokenizer_digest: marker("numeric.no-tokenizer"),
        preprocessor_digest: marker("digital.public-and-finite17-state.v1"),
        quantization_digest: marker("selected-action-six.q24.v1"),
        runtime_digest: marker(env!("HEPTA_TASK_NATIVE_SOURCE_DIGEST")),
        device_digest: marker(std::env::consts::ARCH),
        normalization_digest: model,
        native_config_digest: sparse.digest().expect("bounded native configuration"),
        input_feature_dimension: input_width,
        state_width: ACTIONS,
        modulator_dimension: 1,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: marker("research.calibration-unestablished.worst-case"),
            ood_artifact_digest: marker("research.ood-unestablished.worst-case"),
            generation,
            valid_from_sequence: 1,
            expires_after_sequence: LIMIT as u64,
            zero_confidence_error_q24: 16 * Q24,
            maximum_in_domain_error_q24: 16 * Q24,
            minimum_confidence_ppm: 0,
            maximum_ood_ppm: 1_000_000,
            minimum_active_ppm: 0,
            maximum_active_ppm: 1_000_000,
            maximum_projection_count: 20,
            measured_ece_ppm: 1_000_000,
            maximum_ece_ppm: 1_000_000,
            measured_false_acceptance_ppm: 1_000_000,
            maximum_false_acceptance_ppm: 1_000_000,
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 10_000_000,
            p99_latency_micros: 30_000_000,
            transient_allocation_bytes: 1 << 24,
            checkpoint_bytes: 1 << 22,
            write_amplification_ppm: 4_000_000,
        },
    };
    (sparse, config)
}

pub fn packed(features: &[f64]) -> Vec<i64> {
    features
        .iter()
        .map(|v| (v / (1.0 + v.abs()) * Q24 as f64).round() as i64)
        .collect()
}
