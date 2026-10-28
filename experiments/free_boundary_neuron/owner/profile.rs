//! Exact finite encoder-domain profile; it does not certify task-success calibration.
use crate::Result;
use crate::Q;
use codex_hepta_neuron::NeuronCalibrationProfileV1;
use codex_hepta_neuron::NeuronResourceEnvelopeV1;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

pub fn configuration(
    bundle: Digest32,
    calibration: Digest32,
    binary: Digest32,
    expires: u64,
) -> Result<(SparseConfig, NeuronRuntimeConfigV1)> {
    if !(1..=64).contains(&expires) {
        return Err("Unregistered calibration lifetime".into());
    }
    let native = SparseConfig {
        model_digest: bundle,
        normalization_digest: Digest32::of_bytes(b"free-boundary.finite-grid-index-q24.v1"),
        generation: Generation::new(1)?,
        width: 10,
        top_k: 2,
        temporal_decay_q24: 3 * Q / 4,
        inhibition_gain_q24: Q / 4,
        inhibition: vec![],
        activity_decay_q24: 3 * Q / 4,
        target_activity_q24: Q / 5,
        threshold_rate_q24: Q / 64,
        threshold_min_q24: 0,
        threshold_max_q24: Q / 2,
        eligibility_decay_q24: Q / 2,
    };
    let config = NeuronRuntimeConfigV1 {
        config_id: StableId::new("free-boundary.finite-owner.v1")?,
        generation: native.generation,
        model_id: StableId::new("free-boundary.grid-readout.v1")?,
        model_manifest_digest: bundle,
        encoder_digest: Digest32::of_bytes(b"finite-grid-observation-encoder.v1"),
        head_digest: bundle,
        weights_digest: bundle,
        tokenizer_digest: Digest32::of_bytes(b"no-text-tokenizer.v1"),
        preprocessor_digest: native.normalization_digest,
        quantization_digest: Digest32::of_bytes(b"q24-round-nearest.v1"),
        runtime_digest: binary,
        device_digest: Digest32::of_bytes(std::env::consts::ARCH.as_bytes()),
        normalization_digest: native.normalization_digest,
        native_config_digest: native.digest()?,
        input_feature_dimension: 4,
        state_width: 10,
        modulator_dimension: 1,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: calibration,
            ood_artifact_digest: calibration,
            generation: native.generation,
            valid_from_sequence: 1,
            expires_after_sequence: expires,
            zero_confidence_error_q24: Q,
            maximum_in_domain_error_q24: Q,
            minimum_confidence_ppm: 750_000,
            maximum_ood_ppm: 250_000,
            minimum_active_ppm: 0,
            maximum_active_ppm: 1_000_000,
            maximum_projection_count: 10,
            measured_ece_ppm: 0,
            maximum_ece_ppm: 30_000,
            measured_false_acceptance_ppm: 0,
            maximum_false_acceptance_ppm: 4_999,
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 1_000_000,
            p99_latency_micros: 10_000_000,
            transient_allocation_bytes: 1 << 20,
            checkpoint_bytes: 1 << 20,
            write_amplification_ppm: 4_000_000,
        },
    };
    Ok((native, config))
}
