//! Qualification-only configuration; no empirical calibration or daemon authority.
use crate::model::Features;
use crate::model::CODEC;
use crate::model::OUTPUT_ADAPTER;
use crate::model::WIDTH;
use crate::*;

pub fn definition(
    features: &Features,
    model: Digest32,
    boot: Digest32,
    input_scalars: usize,
    encoder_digest: Digest32,
) -> Result<CellDefinitionV1> {
    let width = WIDTH;
    let generation = Generation::new(1)?;
    let native = SparseConfig {
        model_digest: model,
        normalization_digest: model,
        generation,
        width,
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
    let runtime = NeuronRuntimeConfigV1 {
        config_id: id("perc-trained-native-qualification")?,
        generation,
        model_id: id("acquisition-tanh-mlp-f64")?,
        model_manifest_digest: model,
        encoder_digest,
        head_digest: model,
        weights_digest: model,
        tokenizer_digest: pin("no-tokenizer-f64"),
        preprocessor_digest: native.normalization_digest,
        quantization_digest: pin(&format!("{CODEC}:{OUTPUT_ADAPTER}")),
        runtime_digest: pin("rust-f64-normalize-tanh-matmul-calibrated-cost-ordinal-v1"),
        device_digest: boot,
        normalization_digest: native.normalization_digest,
        native_config_digest: native.digest()?,
        input_feature_dimension: input_scalars,
        state_width: width,
        modulator_dimension: 1,
        // Qualification fixture only. These calibration fields are not empirical measurements.
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: pin("diagnostic-not-scientific-calibration"),
            ood_artifact_digest: pin("diagnostic-not-scientific-ood"),
            generation,
            valid_from_sequence: 1,
            expires_after_sequence: 32,
            zero_confidence_error_q24: 16 * Q,
            maximum_in_domain_error_q24: 8 * Q,
            minimum_confidence_ppm: 0,
            maximum_ood_ppm: 1_000_000,
            minimum_active_ppm: 0,
            maximum_active_ppm: 1_000_000,
            maximum_projection_count: 8,
            measured_ece_ppm: 1000,
            maximum_ece_ppm: 50_000,
            measured_false_acceptance_ppm: 1000,
            maximum_false_acceptance_ppm: 20_000,
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 100_000,
            p99_latency_micros: 1_000_000,
            transient_allocation_bytes: 1_048_576,
            checkpoint_bytes: 65_536,
            write_amplification_ppm: 4_000_000,
        },
    };
    Ok(CellDefinitionV1 {
        cell_id: id("acquisition-trained-cell")?,
        bundle_digest: model,
        state_schema_digest: pin("perc-trained-owner-qualification-v1"),
        runtime,
        native,
        candidates: features
            .candidate_ids
            .iter()
            .enumerate()
            .map(|(index, candidate)| {
                Ok(CellCandidateV1 {
                    candidate_id: id(candidate)?,
                    activation_index: index,
                    kind: CellCandidateKindV1::SlowPath,
                })
            })
            .chain(std::iter::once(Ok(CellCandidateV1 {
                candidate_id: id("abstain")?,
                activation_index: width - 1,
                kind: CellCandidateKindV1::Abstain,
            })))
            .collect::<Result<Vec<_>>>()?,
        max_input_bytes: 65_536,
        max_queue_age_micros: 1_000_000,
        max_resident_bytes: 1_048_576,
    })
}
