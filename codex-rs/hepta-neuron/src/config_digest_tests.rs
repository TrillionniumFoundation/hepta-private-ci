use super::*;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use crate::runtime_types::NeuronCalibrationProfileV1;
use crate::runtime_types::NeuronResourceEnvelopeV1;
use crate::runtime_types::Q24;

fn checked<T, E: std::fmt::Debug>(value: Result<T, E>) -> T {
    match value {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn config() -> NeuronRuntimeConfigV1 {
    let digest = Digest32::of_bytes(b"selected-runtime-field");
    let generation = checked(Generation::new(7));
    NeuronRuntimeConfigV1 {
        config_id: checked(StableId::new("config:one")),
        generation,
        model_id: checked(StableId::new("model:one")),
        model_manifest_digest: digest,
        encoder_digest: digest,
        head_digest: digest,
        weights_digest: digest,
        tokenizer_digest: digest,
        preprocessor_digest: digest,
        quantization_digest: digest,
        runtime_digest: digest,
        device_digest: digest,
        normalization_digest: digest,
        native_config_digest: digest,
        input_feature_dimension: 2,
        state_width: 5,
        modulator_dimension: 1,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: digest,
            ood_artifact_digest: digest,
            generation,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            zero_confidence_error_q24: Q24,
            maximum_in_domain_error_q24: Q24,
            minimum_confidence_ppm: 100_000,
            maximum_ood_ppm: 200_000,
            minimum_active_ppm: 0,
            maximum_active_ppm: 200_000,
            maximum_projection_count: 100,
            measured_ece_ppm: 10,
            maximum_ece_ppm: 100,
            measured_false_acceptance_ppm: 10,
            maximum_false_acceptance_ppm: 100,
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 100,
            p99_latency_micros: 200,
            transient_allocation_bytes: 1_000_000,
            checkpoint_bytes: 1_000_000,
            write_amplification_ppm: 1_000_000,
        },
    }
}

#[test]
fn every_runtime_selection_and_admission_field_changes_the_binding() {
    type Mutation = (&'static str, fn(&mut NeuronRuntimeConfigV1));
    let mutations: &[Mutation] = &[
        ("config_id", |value| {
            value.config_id = checked(StableId::new("config:two"))
        }),
        ("generation", |value| {
            value.generation = checked(value.generation.next());
            value.calibration.generation = value.generation;
        }),
        ("model_id", |value| {
            value.model_id = checked(StableId::new("model:two"))
        }),
        ("model_manifest_digest", |value| {
            value.model_manifest_digest = Digest32::of_bytes(b"changed")
        }),
        ("encoder_digest", |value| {
            value.encoder_digest = Digest32::of_bytes(b"changed")
        }),
        ("head_digest", |value| {
            value.head_digest = Digest32::of_bytes(b"changed")
        }),
        ("weights_digest", |value| {
            value.weights_digest = Digest32::of_bytes(b"changed")
        }),
        ("tokenizer_digest", |value| {
            value.tokenizer_digest = Digest32::of_bytes(b"changed")
        }),
        ("preprocessor_digest", |value| {
            value.preprocessor_digest = Digest32::of_bytes(b"changed")
        }),
        ("quantization_digest", |value| {
            value.quantization_digest = Digest32::of_bytes(b"changed")
        }),
        ("runtime_digest", |value| {
            value.runtime_digest = Digest32::of_bytes(b"changed")
        }),
        ("device_digest", |value| {
            value.device_digest = Digest32::of_bytes(b"changed")
        }),
        ("normalization_digest", |value| {
            value.normalization_digest = Digest32::of_bytes(b"changed")
        }),
        ("native_config_digest", |value| {
            value.native_config_digest = Digest32::of_bytes(b"changed")
        }),
        ("input_feature_dimension", |value| {
            value.input_feature_dimension += 1
        }),
        ("state_width", |value| value.state_width += 1),
        ("modulator_dimension", |value| {
            value.modulator_dimension += 1
        }),
        ("calibration_artifact_digest", |value| {
            value.calibration.calibration_artifact_digest = Digest32::of_bytes(b"changed")
        }),
        ("ood_artifact_digest", |value| {
            value.calibration.ood_artifact_digest = Digest32::of_bytes(b"changed")
        }),
        ("valid_from_sequence", |value| {
            value.calibration.valid_from_sequence += 1
        }),
        ("expires_after_sequence", |value| {
            value.calibration.expires_after_sequence += 1
        }),
        ("zero_confidence_error_q24", |value| {
            value.calibration.zero_confidence_error_q24 += 1
        }),
        ("maximum_in_domain_error_q24", |value| {
            value.calibration.maximum_in_domain_error_q24 += 1
        }),
        ("minimum_confidence_ppm", |value| {
            value.calibration.minimum_confidence_ppm += 1
        }),
        ("maximum_ood_ppm", |value| {
            value.calibration.maximum_ood_ppm += 1
        }),
        ("minimum_active_ppm", |value| {
            value.calibration.minimum_active_ppm += 1
        }),
        ("maximum_active_ppm", |value| {
            value.calibration.maximum_active_ppm += 1
        }),
        ("maximum_projection_count", |value| {
            value.calibration.maximum_projection_count += 1
        }),
        ("measured_ece_ppm", |value| {
            value.calibration.measured_ece_ppm += 1
        }),
        ("maximum_ece_ppm", |value| {
            value.calibration.maximum_ece_ppm += 1
        }),
        ("measured_false_acceptance_ppm", |value| {
            value.calibration.measured_false_acceptance_ppm += 1
        }),
        ("maximum_false_acceptance_ppm", |value| {
            value.calibration.maximum_false_acceptance_ppm += 1
        }),
        ("p95_latency_micros", |value| {
            value.resource_envelope.p95_latency_micros += 1
        }),
        ("p99_latency_micros", |value| {
            value.resource_envelope.p99_latency_micros += 1
        }),
        ("transient_allocation_bytes", |value| {
            value.resource_envelope.transient_allocation_bytes += 1
        }),
        ("checkpoint_bytes", |value| {
            value.resource_envelope.checkpoint_bytes += 1
        }),
        ("write_amplification_ppm", |value| {
            value.resource_envelope.write_amplification_ppm += 1
        }),
    ];
    let original = config();
    let digest = checked(original.semantic_digest());
    for (field, mutate) in mutations {
        let mut changed = original.clone();
        mutate(&mut changed);
        assert_ne!(
            checked(changed.semantic_digest()),
            digest,
            "unbound field: {field}"
        );
    }
    assert_eq!(checked(original.semantic_digest()), digest);
}

#[test]
fn runtime_semantic_binding_rejects_invalid_profiles() {
    let mut changed = config();
    changed.weights_digest = Digest32::ZERO;
    assert_eq!(
        changed.semantic_digest(),
        Err(NeuronRuntimeError::EmptyDigest("weights"))
    );

    let mut changed = config();
    changed.calibration.generation = checked(changed.generation.next());
    assert_eq!(
        changed.semantic_digest(),
        Err(NeuronRuntimeError::InvalidCalibration)
    );

    let mut changed = config();
    changed.state_width = 257;
    assert_eq!(
        changed.semantic_digest(),
        Err(NeuronRuntimeError::InvalidConfig)
    );
}
