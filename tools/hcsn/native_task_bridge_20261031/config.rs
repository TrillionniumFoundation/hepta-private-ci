use crate::contract::deployment_digest;
use crate::contract::id;
use crate::contract::marker;
use crate::contract::LIMIT;
use crate::contract::Q;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

pub fn configuration(
    model: Digest32,
    width: usize,
) -> Result<(SparseConfig, NeuronRuntimeConfigV1), String> {
    let generation = Generation::new(1).map_err(|error| error.to_string())?;
    let head = deployment_digest(model);
    let native = SparseConfig {
        model_digest: head,
        normalization_digest: model,
        generation,
        width: 5,
        top_k: 1,
        temporal_decay_q24: 0,
        inhibition_gain_q24: 0,
        inhibition: vec![],
        activity_decay_q24: 0,
        target_activity_q24: Q / 5,
        threshold_rate_q24: 0,
        threshold_min_q24: 0,
        threshold_max_q24: 0,
        eligibility_decay_q24: 0,
    };
    let config = NeuronRuntimeConfigV1 {
        config_id: id("hepta.task.native-bridge.v2")?,
        generation,
        model_id: id("hepta.task.frozen-residual-mlp.v2")?,
        model_manifest_digest: model,
        encoder_digest: marker("public-features-plus-prior-plus-mask.q24.v1"),
        head_digest: head,
        weights_digest: model,
        tokenizer_digest: marker("numeric-vector.no-tokenizer"),
        preprocessor_digest: marker("checkpoint.norm.mean-scale.f64"),
        quantization_digest: marker("q24-input-round-nearest-and-score-offset-four"),
        runtime_digest: marker(env!("HEPTA_TASK_NATIVE_SOURCE_DIGEST")),
        device_digest: marker(std::env::consts::ARCH),
        normalization_digest: model,
        native_config_digest: native.digest().map_err(|error| error.to_string())?,
        input_feature_dimension: width + 8,
        state_width: 5,
        modulator_dimension: 1,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: marker("research.calibration-unestablished.worst-case"),
            ood_artifact_digest: marker("research.ood-unestablished.worst-case"),
            generation,
            valid_from_sequence: 1,
            expires_after_sequence: LIMIT as u64,
            zero_confidence_error_q24: 16 * Q,
            maximum_in_domain_error_q24: 16 * Q,
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
            checkpoint_bytes: 1 << 20,
            write_amplification_ppm: 4_000_000,
        },
    };
    Ok((native, config))
}
