use super::*;
use codex_hepta_neuron::NeuronCalibrationProfileV1;
use codex_hepta_neuron::NeuronResourceEnvelopeV1;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_types::Digest32;

#[test]
fn physical_loader_checks_encoder_heads_dimensions_and_complete_runtime_tuple() {
    let (directory, path, pin, encoder, head) = installed_model();
    let control =
        DurableInferenceControl::open(directory.path().join("control"), /*capacity*/ 8)
            .expect("real sole control writer");
    let physical =
        CpuNeuronInferenceControlV1::open(control, Arc::new(FixtureClock), &path, pin, config())
            .expect("actual parsed CPU weights");
    let manifest = physical.manifest();
    let digest = Digest32::of_bytes(b"fixture runtime evidence");
    let generation = Generation::new(1).expect("generation");
    let runtime = NeuronRuntimeConfigV1 {
        config_id: StableId::new("cpu.runtime.fixture").expect("config"),
        generation,
        model_id: StableId::new(manifest.model_id.clone()).expect("model"),
        model_manifest_digest: pin,
        encoder_digest: encoder.parse().expect("encoder"),
        head_digest: head.parse().expect("heads"),
        weights_digest: manifest.weights_digest.parse().expect("weights"),
        tokenizer_digest: manifest.tokenizer_digest.parse().expect("tokenizer"),
        preprocessor_digest: manifest.preprocessor_digest.parse().expect("preprocessor"),
        quantization_digest: manifest.quantization_digest.parse().expect("quantization"),
        runtime_digest: manifest.runtime_digest.parse().expect("runtime"),
        device_digest: manifest.device_digest.parse().expect("actual CPU device"),
        normalization_digest: digest,
        native_config_digest: digest,
        input_feature_dimension: 2,
        state_width: 1,
        modulator_dimension: 1,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: digest,
            ood_artifact_digest: digest,
            generation,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            zero_confidence_error_q24: 1 << 24,
            maximum_in_domain_error_q24: 1 << 24,
            minimum_confidence_ppm: 0,
            maximum_ood_ppm: 1_000_000,
            minimum_active_ppm: 0,
            maximum_active_ppm: 1_000_000,
            maximum_projection_count: 100,
            measured_ece_ppm: 0,
            maximum_ece_ppm: 100_000,
            measured_false_acceptance_ppm: 0,
            maximum_false_acceptance_ppm: 100_000,
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 3_000,
            p99_latency_micros: 8_000,
            transient_allocation_bytes: 1 << 20,
            checkpoint_bytes: 1 << 20,
            write_amplification_ppm: 1_000_000,
        },
    };
    assert_eq!(physical.validate_runtime(&runtime), Ok(()));
    for changed in 0..12 {
        let mut other = runtime.clone();
        match changed {
            0 => other.model_manifest_digest = digest,
            1 => other.encoder_digest = digest,
            2 => other.head_digest = digest,
            3 => other.weights_digest = digest,
            4 => other.runtime_digest = digest,
            5 => other.tokenizer_digest = digest,
            6 => other.preprocessor_digest = digest,
            7 => other.quantization_digest = digest,
            8 => other.device_digest = digest,
            9 => other.model_id = StableId::new("cpu.unrelated.model").expect("ID"),
            10 => other.input_feature_dimension = 3,
            11 => other.state_width = 2,
            _ => unreachable!(),
        }
        assert_eq!(
            physical.validate_runtime(&other),
            Err(crate::model_worker::Error::ModelMismatch)
        );
    }
    let mut other = runtime;
    other.generation = Generation::new(2).expect("generation");
    assert_eq!(
        physical.validate_runtime(&other),
        Err(crate::model_worker::Error::ModelMismatch)
    );
}
