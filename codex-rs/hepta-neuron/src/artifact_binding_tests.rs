use super::*;
use pretty_assertions::assert_eq;

#[test]
fn artifact_profile_is_non_circular_but_binds_executable_parameters() {
    let native = native_config();
    let config = runtime_config(&native);
    let profile = checked(config.execution_profile_digest_v1());
    let mut changed = config.clone();
    changed.model_manifest_digest = Digest32::of_bytes(b"published-manifest");
    changed.calibration.calibration_artifact_digest = Digest32::of_bytes(b"published-calibration");
    changed.calibration.ood_artifact_digest = Digest32::of_bytes(b"published-ood");
    assert_eq!(checked(changed.execution_profile_digest_v1()), profile);
    assert_ne!(
        checked(changed.semantic_digest()),
        checked(config.semantic_digest())
    );
    changed.weights_digest = Digest32::of_bytes(b"different-trained-weights");
    assert_ne!(checked(changed.execution_profile_digest_v1()), profile);
}

#[test]
fn evidence_bytes_bind_model_and_measured_profile_without_self_reference() {
    let native = native_config();
    let config = runtime_config(&native);
    let calibration = checked(config.calibration_evidence_payload_v1());
    let ood = checked(config.ood_evidence_payload_v1());
    assert_ne!(calibration, ood);
    let mut bound = config.clone();
    bound.calibration.calibration_artifact_digest = Digest32::of_bytes(&calibration);
    bound.calibration.ood_artifact_digest = Digest32::of_bytes(&ood);
    assert_eq!(
        checked(bound.calibration_evidence_payload_v1()),
        calibration
    );
    assert_eq!(checked(bound.ood_evidence_payload_v1()), ood);
    bound.calibration.measured_ece_ppm += 1;
    assert_ne!(
        checked(bound.calibration_evidence_payload_v1()),
        calibration
    );
    bound = config;
    bound.tokenizer_digest = Digest32::of_bytes(b"different-tokenizer");
    assert_ne!(checked(bound.ood_evidence_payload_v1()), ood);
}

#[test]
fn v2_semantic_identity_excludes_telemetry_and_binds_runtime_ids() {
    let native = native_config();
    let config = runtime_config(&native);
    let tick = input(1, Digest32::ZERO);
    let request = NeuronModelRequestV1 {
        request_id: tick.tick_id.clone(),
        config_id: config.config_id.clone(),
        generation: config.generation,
        model_id: config.model_id.clone(),
        encoder_digest: config.encoder_digest,
        head_digest: config.head_digest,
        weights_digest: config.weights_digest,
        input_digest: checked(tick.semantic_digest()),
        feature_vector_q24: tick.feature_vector_q24.clone(),
        expected_output_width: config.state_width,
    };
    let mut model = FakeModel::new();
    let mut output = checked(model.execute(&request));
    output.runtime_receipt.quantization_id = checked(StableId::new(format!(
        "quantization:{}",
        config.quantization_digest
    )));
    output.runtime_receipt.backend_id =
        checked(StableId::new(format!("runtime:{}", config.runtime_digest)));
    output.output_digest = checked(canonical_model_output_digest_v1(
        &output.drive_q24,
        &output.prediction_q24,
        &output.runtime_receipt,
    ));

    let (semantic_before, observation_before) =
        checked(config.project_model_binding_digests_v2(&tick, &output));
    output.runtime_receipt.latency_micros += 99;
    output.runtime_receipt.resident_bytes += 4_096;
    output.queue_age_micros += 17;
    output.transient_allocation_bytes += 1_024;
    output.output_digest = checked(canonical_model_output_digest_v1(
        &output.drive_q24,
        &output.prediction_q24,
        &output.runtime_receipt,
    ));
    let (semantic_after, observation_after) =
        checked(config.project_model_binding_digests_v2(&tick, &output));
    assert_eq!(semantic_before, semantic_after);
    assert_ne!(observation_before, observation_after);

    output.runtime_receipt.backend_id = checked(StableId::new("runtime:wrong"));
    output.output_digest = checked(canonical_model_output_digest_v1(
        &output.drive_q24,
        &output.prediction_q24,
        &output.runtime_receipt,
    ));
    assert_eq!(
        config.project_model_binding_digests_v2(&tick, &output),
        Err(NeuronRuntimeError::ModelBindingMismatch)
    );
}
