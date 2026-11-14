use crate::model::{INPUTS, Projection, Q, WIDTH, digest, id};
use codex_hepta_neuron::{
    JournalScope, NeuronCalibrationProfileV1, NeuronResourceEnvelopeV1, NeuronRuntimeConfigV1,
    NeuronTickInputV1, SparseConfig, canonical_feature_vector_digest_v1,
};
use codex_hepta_types::{Digest32, Generation};

pub fn native() -> SparseConfig {
    SparseConfig {
        model_digest: digest("fixed Q24 projection head v1"),
        normalization_digest: digest("fixed projection normalization v1"),
        generation: Generation::new(1).expect("positive generation"),
        width: WIDTH,
        top_k: 1,
        temporal_decay_q24: Q / 2,
        inhibition_gain_q24: 0,
        inhibition: vec![],
        activity_decay_q24: Q / 2,
        target_activity_q24: Q / 4,
        threshold_rate_q24: Q / 16,
        threshold_min_q24: -Q,
        threshold_max_q24: Q,
        eligibility_decay_q24: Q / 2,
    }
}

pub fn config(model: &Projection) -> NeuronRuntimeConfigV1 {
    let n = native();
    let t = &model.tuple;
    NeuronRuntimeConfigV1 {
        config_id: id("research.component-owner.config.v1"),
        generation: n.generation,
        model_id: t.model_id.clone(),
        model_manifest_digest: t.model_manifest_digest,
        encoder_digest: digest("fixed numeric projection encoder v1"),
        head_digest: n.model_digest,
        weights_digest: t.weights_digest,
        tokenizer_digest: t.tokenizer_digest,
        preprocessor_digest: t.preprocessor_digest,
        quantization_digest: t.quantization_digest,
        runtime_digest: t.runtime_digest,
        device_digest: t.device_digest,
        normalization_digest: n.normalization_digest,
        native_config_digest: n.digest().expect("native config"),
        input_feature_dimension: INPUTS,
        state_width: WIDTH,
        modulator_dimension: 1,
        // These are explicitly fixture fields, not empirical calibration evidence.
        // Publication remains DENY_ALL; this harness has no effect destination.
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: digest(
                "uncertified calibration fixture; not a production calibration artifact",
            ),
            ood_artifact_digest: digest("uncertified OOD fixture; no task qualification"),
            generation: n.generation,
            valid_from_sequence: 1,
            expires_after_sequence: 4096,
            zero_confidence_error_q24: 16 * Q,
            maximum_in_domain_error_q24: 8 * Q,
            minimum_confidence_ppm: 1_000_000,
            maximum_ood_ppm: 0,
            minimum_active_ppm: 0,
            maximum_active_ppm: 1_000_000,
            maximum_projection_count: 8,
            measured_ece_ppm: 0,
            maximum_ece_ppm: 0,
            measured_false_acceptance_ppm: 0,
            maximum_false_acceptance_ppm: 0,
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

pub fn scope(index: usize) -> JournalScope {
    let subject = id(format!("research.component-owner.{index}"));
    let raw = subject.as_str().as_bytes();
    let mut bytes = b"hepta.neuron.subject-scope.v1".to_vec();
    bytes.extend_from_slice(&(raw.len() as u32).to_be_bytes());
    bytes.extend_from_slice(raw);
    JournalScope {
        scope_digest: Digest32::of_bytes(&bytes),
        objective_digest: digest("native owner component measurement; no task utility"),
    }
}

pub fn input(index: usize, sequence: u64, checkpoint: Digest32) -> NeuronTickInputV1 {
    let features = (0..INPUTS)
        .map(|j| ((index * 13 + j * 7 + sequence as usize * 3) % 31) as i64 * Q / 32 - Q / 2)
        .collect::<Vec<_>>();
    NeuronTickInputV1 {
        tick_id: id(format!("research.tick.{index}.{sequence}")),
        subject_id: id(format!("research.component-owner.{index}")),
        logical_sequence: sequence,
        monotonic_time_micros: sequence * 1000,
        checkpoint_digest: checkpoint,
        input_feature_digest: canonical_feature_vector_digest_v1(&features),
        feature_vector_q24: features,
        objective_digest: scope(index).objective_digest,
        ndu_snapshot_digest: digest(
            "synthetic research NDU input; not an independent future outcome",
        ),
        body_generation: Some(1),
        modulator_digest: None,
    }
}
