use super::*;

fn request() -> GenerationRequestV1 {
    GenerationRequestV1 {
        schema: GENERATION_SCHEMA.to_string(),
        request_id: "generation.1".to_string(),
        objective_sha256: "1".repeat(64),
        input_source_sha256: "2".repeat(64),
        model: GenerationModelPinsV1 {
            checkpoint_sha256: "3".repeat(64),
            snapshot_sha256: "4".repeat(64),
            parameters_sha256: "4".repeat(64),
            config_sha256: "5".repeat(64),
            source_sha256: "6".repeat(64),
            python_sha256: "7".repeat(64),
            device_sha256: "9".repeat(64),
            runtime_versions: ["p".into(), "t".into(), "n".into(), "i".into()],
            hidden: 16,
        },
        required_modalities: 3,
        pixels_f32: vec![0; 28 * 56],
        mask_f32: vec![1.0_f32.to_bits(); 28 * 56],
        text_tokens: vec![1; 8],
        noise_seed: 17,
        content_control: true,
        actions: vec![GenerationActionV1::Couple],
    }
}

#[test]
fn validates_exact_scope_and_rejects_unknown_fields_nonfinite_or_unimplemented_media() {
    let original = request();
    assert!(original.validate(&original.model).is_ok());
    let mut changed = original.clone();
    changed.model.config_sha256 = "8".repeat(64);
    assert!(changed.validate(&original.model).is_err());
    changed = original.clone();
    changed.pixels_f32[0] = f32::NAN.to_bits();
    assert!(changed.validate(&original.model).is_err());
    changed = original.clone();
    changed.required_modalities = 15;
    assert!(changed.validate(&original.model).is_err());
    let mut json = serde_json::to_value(original).expect("fixture JSON");
    json["executable"] = serde_json::json!("arbitrary program");
    assert!(serde_json::from_value::<GenerationRequestV1>(json).is_err());
}

#[test]
fn receipt_binds_actual_state_bytes_output_bytes_and_authority() {
    let request = request();
    let state_bytes = vec![0_u32; request.model.hidden * 4];
    let mut digest_bytes = b"hepta.inference.generation-state.v1\0".to_vec();
    digest_bytes.extend_from_slice(request.model.snapshot_sha256.as_bytes());
    digest_bytes.extend_from_slice("8".repeat(64).as_bytes());
    digest_bytes.extend_from_slice(&(-2_i32).to_le_bytes());
    digest_bytes.extend(vec![0; state_bytes.len() * 4]);
    let state = GenerationStateV1 {
        values_f32: state_bytes,
        backend_state_sha256: "8".repeat(64),
        plan_index: None,
        state_sha256: Digest32::of_bytes(&digest_bytes).to_string(),
    };
    // Header/footer fixture checks wire identity only; actual PNG decoding is
    // exercised by the Python and existing-worker integration tests.
    let png =
        b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR\0\0\08\0\0\0\x1c\x08\0\0\0\0\0\0\0\0\0\0\0\0IEND\xaeB`\x82"
            .to_vec();
    let mut receipt = GenerationExecutionV1 {
        schema: GENERATION_SCHEMA.into(),
        request_sha256: generation_json_digest(&request).expect("digest"),
        model: request.model.clone(),
        states: vec![state.clone(), state],
        token_ids: vec![1; 8],
        caption: String::new(),
        png_sha256: Digest32::of_bytes(&png).to_string(),
        png,
        text_sha256: Digest32::of_bytes(b"").to_string(),
        wall_ns: 1,
        cpu_ns: 1,
        peak_rss_bytes: 1,
        authority: "deny_all".into(),
    };
    assert!(receipt.verify(&request).is_ok());
    receipt.states[1].values_f32[0] = 1.0_f32.to_bits();
    assert!(receipt.verify(&request).is_err());
    receipt.states[1] = receipt.states[0].clone();
    receipt.authority = "dispatch".into();
    assert!(receipt.verify(&request).is_err());
}
