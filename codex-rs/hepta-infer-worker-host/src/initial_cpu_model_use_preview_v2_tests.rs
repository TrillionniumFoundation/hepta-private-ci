use super::*;
use codex_hepta_agent_components::intelligence_eval::OperationalCalibrationGatesV2;
use pretty_assertions::assert_eq;

fn configuration() -> Configuration {
    let pin = Digest32::of_bytes(b"unsigned preview fixture");
    Configuration {
        schema: "hepta.cpu-neuron.root-model-use-preview-input.v2".into(),
        model_pins: Pins {
            model_generation: 1,
            model_manifest_digest: pin.to_string(),
            weights_digest: pin.to_string(),
            normalization_digest: pin.to_string(),
            encoder_manifest_digest: pin.to_string(),
            tokenizer_digest: pin.to_string(),
            training_code_digest: pin.to_string(),
            source_training_digest: pin.to_string(),
            preregistration_digest: pin.to_string(),
            body_implementation_digest: pin.to_string(),
            purpose: OperationalModelUseV2::ConservativeCpuAbstentionOnlyV1,
        },
        runtime_profile: ConservativeCpuRuntimeProfileV2 {
            input_feature_dimension: 512,
            state_width: 10,
            modulator_dimension: 1,
            maximum_inflight: 2,
            maximum_load_bytes: 1024 * 1024,
            p95_latency_micros: 500,
            p99_latency_micros: 1000,
            transient_allocation_bytes: 65536,
            checkpoint_bytes: 65536,
            write_amplification_ppm: 4_000_000,
            calibration_gates: OperationalCalibrationGatesV2 {
                zero_confidence_error_q24: 2 << 24,
                maximum_in_domain_error_q24: 2 << 24,
                minimum_confidence_ppm: 900_000,
                maximum_ood_ppm: 750_000,
                minimum_accuracy_ppm: 500_000,
                maximum_ece_ppm: 500_000,
                maximum_false_acceptance_ppm: 100_000,
                maximum_p99_latency_micros: 100_000,
                maximum_resident_bytes: 1 << 29,
                maximum_transient_allocation_bytes: 1 << 24,
            },
        },
    }
}

#[test]
fn preview_uses_original_native_digests_and_rejects_goal_authority_fields() -> HostResult<()> {
    let input = configuration();
    let mut encoded = serde_json::json!({
        "schema": input.schema,
        "model_pins": input.model_pins,
        "runtime_profile": input.runtime_profile,
    });
    let output = serde_json::from_value::<Configuration>(encoded.clone())?.preview()?;
    assert_eq!(
        output["runtime_profile_digest"],
        input.runtime_profile.semantic_digest()?.to_string()
    );
    let pins = input.model_pins;
    let binding = OperationalModelLeaseBindingV2 {
        model_generation: pins.model_generation,
        model_manifest_digest: pins.model_manifest_digest.parse()?,
        weights_digest: pins.weights_digest.parse()?,
        normalization_digest: pins.normalization_digest.parse()?,
        encoder_manifest_digest: pins.encoder_manifest_digest.parse()?,
        tokenizer_digest: pins.tokenizer_digest.parse()?,
        training_code_digest: pins.training_code_digest.parse()?,
        source_training_digest: pins.source_training_digest.parse()?,
        preregistration_digest: pins.preregistration_digest.parse()?,
        body_implementation_digest: pins.body_implementation_digest.parse()?,
        model_runtime_profile_digest: input.runtime_profile.semantic_digest()?,
        purpose: pins.purpose,
    };
    assert_eq!(
        output["binding_digest"],
        binding.binding_digest()?.to_string()
    );
    for field in ["objective_digest", "issued_at", "expires_at", "signature"] {
        encoded[field] = serde_json::json!("caller authority");
        assert!(serde_json::from_value::<Configuration>(encoded.clone()).is_err());
        encoded
            .as_object_mut()
            .ok_or("configuration object")?
            .remove(field);
    }
    Ok(())
}

#[test]
fn preview_preserves_original_model_generation_and_resource_admission() {
    let mut wrong_generation = configuration();
    wrong_generation.model_pins.model_generation = 2;
    assert!(wrong_generation.preview().is_err());
    let mut zero_pin = configuration();
    zero_pin.model_pins.encoder_manifest_digest = Digest32::ZERO.to_string();
    assert!(zero_pin.preview().is_err());
    let mut wrong_budget = configuration();
    wrong_budget.runtime_profile.write_amplification_ppm = 4_000_001;
    assert!(wrong_budget.preview().is_err());
}

#[test]
fn preview_reads_no_caller_file_under_an_ordinary_uid() {
    if rustix::process::geteuid().as_raw() != 0 {
        assert!(preview(Path::new("/not-a-root-input"), Digest32::ZERO).is_err());
    }
}
