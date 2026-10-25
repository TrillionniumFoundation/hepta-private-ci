//! Bind actual qualification artifacts and frozen head to unchanged ceilings.
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;

use crate::head::Q;

#[derive(Deserialize)]
pub struct Pins {
    pub protocol: String,
    pub feature_profile: String,
    pub weights: String,
    pub calibration: String,
    pub verification: String,
    pub device: String,
    pub upstream_model: String,
    pub source_manifest: String,
    pub dataset: String,
    pub measured_ece_ppm: u32,
    pub measured_false_acceptance_ppm: u32,
}

pub fn configuration(p: &Pins, binary: Digest32) -> Result<(SparseConfig, NeuronRuntimeConfigV1), Box<dyn std::error::Error>> {
    let head = Digest32::of_bytes(format!("{}:{}:{}", p.weights, p.calibration, p.feature_profile).as_bytes());
    let normalization = Digest32::of_bytes(b"abc3.correctness-reference-residual.no-scaling.v1");
    let native = SparseConfig {
        model_digest: head, normalization_digest: normalization, generation: Generation::new(1)?,
        width: 32, top_k: 4, temporal_decay_q24: Q/2, inhibition_gain_q24: Q,
        inhibition: vec![], activity_decay_q24: Q/2, target_activity_q24: Q/8,
        threshold_rate_q24: Q/8, threshold_min_q24: -Q, threshold_max_q24: Q,
        eligibility_decay_q24: Q/2,
    };
    let config = NeuronRuntimeConfigV1 {
        config_id: StableId::new("abc3.correctness.config.v1")?, generation: native.generation,
        model_id: StableId::new("abc3.observed-output-correctness.v1")?,
        model_manifest_digest: Digest32::of_bytes(format!("{}:{}:{}:{}", p.protocol, p.upstream_model, p.weights, p.calibration).as_bytes()),
        encoder_digest: p.feature_profile.parse()?, head_digest: head, weights_digest: p.weights.parse()?,
        tokenizer_digest: Digest32::of_bytes(b"v6-caption-vocabulary-24-public-token-onehot"),
        preprocessor_digest: p.feature_profile.parse()?,
        quantization_digest: Digest32::of_bytes(b"f64-affine-tanh-sigmoid;Q24-half-away;no-residual-rescaling"),
        runtime_digest: binary, device_digest: p.device.parse()?, normalization_digest: normalization,
        native_config_digest: native.digest()?, input_feature_dimension: 508, state_width: 32, modulator_dimension: 1,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: p.calibration.parse()?, ood_artifact_digest: p.verification.parse()?,
            generation: native.generation, valid_from_sequence: 1, expires_after_sequence: 2,
            zero_confidence_error_q24: Q, maximum_in_domain_error_q24: Q,
            minimum_confidence_ppm: 750_000, maximum_ood_ppm: 500_000,
            minimum_active_ppm: 10_000, maximum_active_ppm: 200_000, maximum_projection_count: 8,
            measured_ece_ppm: p.measured_ece_ppm, maximum_ece_ppm: 30_000,
            measured_false_acceptance_ppm: p.measured_false_acceptance_ppm, maximum_false_acceptance_ppm: 4_999,
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 3_000, p99_latency_micros: 8_000,
            transient_allocation_bytes: 512*1024, checkpoint_bytes: 1024*1024,
            write_amplification_ppm: 4_000_000,
        },
    };
    // The actual NeuronRuntime::bootstrap performs its private native validation.
    Ok((native, config))
}

pub fn subject_scope(subject: &StableId) -> Digest32 {
    // Exact canonical public encoding used by runtime_types::subject_scope_digest.
    let mut bytes = b"hepta.neuron.subject-scope.v1".to_vec();
    bytes.extend_from_slice(&(subject.as_str().len() as u32).to_be_bytes());
    bytes.extend_from_slice(subject.as_str().as_bytes());
    Digest32::of_bytes(&bytes)
}
