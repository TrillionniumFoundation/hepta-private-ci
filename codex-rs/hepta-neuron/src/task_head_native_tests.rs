use super::*;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

fn must<T, E: fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn payload(weights: &[f32]) -> Vec<u8> {
    weights
        .iter()
        .flat_map(|weight| weight.to_le_bytes())
        .collect()
}

fn manifest(width: usize, state: usize, rank: usize, tasks: usize, bytes: &[u8]) -> Value {
    json!({
        "schema": "hepta.native-task-head.v1",
        "numeric_profile": "f32-io-f64-accum-gelu-erf-v1",
        "state_contract": "zero_state_only", "mode": "SHADOW_ONLY", "authority": "DENY_ALL",
        "feature_layout": "concat-text-image-product-absolute-difference-cosine-v1",
        "feature_identity": {"encoder_sha256": Digest32::of_bytes(b"encoder").to_string(),
            "checkpoint_revision": "a".repeat(40),
            "preprocess_sha256": Digest32::of_bytes(b"preprocessing").to_string(),
            "generation": 1, "scope_id": "test-scope", "purpose": "research", "revocation_epoch": 0},
        "width": width, "state_width": state, "adapter_rank": rank, "task_count": tasks,
        "required_present_mask": 3, "temperature": 0.75, "confidence_threshold": 0.7,
        "source_head_manifest_sha256": Digest32::of_bytes(b"source-manifest").to_string(),
        "source_head_weights_sha256": Digest32::of_bytes(b"source-weights").to_string(),
        "weights_sha256": Digest32::of_bytes(bytes).to_string(), "weights_bytes": bytes.len()
    })
}

fn fixture() -> (Value, Vec<u8>) {
    let bytes = payload(&[
        0.5, -0.25, 0.0, 0.0, 0.0, 6.0, -8.0, -0.25, // gate: five features, zero state, bias
        1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, // down
        1.0, 0.5, -0.25, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, // up
        0.7, -1.3, 0.0, 0.0, 0.0, -0.6, 0.2, 0.0, 0.0, 0.0, 0.1, -0.2, // task
    ]);
    (manifest(5, 2, 2, 2, &bytes), bytes)
}

fn load(header: &Value, weights: &[u8]) -> Result<LoadedTaskHeadV1, TaskHeadError> {
    let bytes = must(serde_json::to_vec(header));
    LoadedTaskHeadV1::from_artifact(&bytes, weights, Digest32::of_bytes(&bytes))
}

fn assert_error(result: Result<LoadedTaskHeadV1, TaskHeadError>, expected: TaskHeadError) {
    match result {
        Ok(_) => panic!("artifact unexpectedly admitted"),
        Err(error) => assert_eq!(error, expected),
    }
}

#[test]
fn nonzero_gate_gelu_residual_and_temperature_match_independent_torch_values() {
    let (header, weights) = fixture();
    let head = must(load(&header, &weights));
    let result = must(head.predict(&[1.0, -2.0, 0.0, 0.0, 0.0], head.feature_identity(), 3));
    // CPU Torch 2.10, GELU approximate="none", with explicitly zero state.
    let expected_logits = [4.015066623687744, -1.5683350563049316];
    let expected_probabilities = [0.999415714035679, 0.0005842859643210744];
    for (actual, expected) in result.task_logits.iter().zip(expected_logits) {
        assert!((f64::from(*actual) - expected).abs() < 1e-6);
    }
    for (actual, expected) in result.task_probabilities.iter().zip(expected_probabilities) {
        assert!((actual - expected).abs() < 1e-8);
    }
    assert!((result.gate - 0.679_178_7).abs() < 1e-7);
    assert_eq!(result.predicted_class, 0);
    assert!(result.accepted);
    assert_eq!((result.mode, result.authority), ("SHADOW_ONLY", "DENY_ALL"));
    assert_eq!(head.weights_bytes(), weights.len());
    assert_eq!(
        head.manifest_sha256(),
        Digest32::of_bytes(&must(serde_json::to_vec(&header)))
    );
}

#[test]
fn width_3073_uses_the_final_feature_in_the_learned_nonlinear_path() {
    let width = 3073;
    let state = 8;
    let rank = 4;
    let down = width + state + 1;
    let up = down + rank * width;
    let task = up + width * rank;
    let mut weights = vec![0.0; task + 2 * (width + 1)];
    weights[down + width - 1] = 1.0;
    weights[up + (width - 1) * rank] = 1.0;
    weights[task + width - 1] = 1.0;
    weights[task + 2 * width - 1] = -1.0;
    let bytes = payload(&weights);
    let head = must(load(&manifest(width, state, rank, 2, &bytes), &bytes));
    let mut features = vec![0.0; width];
    features[width - 1] = 1.0;
    let result = must(head.predict(&features, head.feature_identity(), 3));
    assert!((result.task_logits[0] - 1.420_672_4).abs() < 1e-6);
    assert!((result.task_logits[1] + 1.420_672_4).abs() < 1e-6);
    features[width - 1] = 0.0;
    let zero = must(head.predict(&features, head.feature_identity(), 3));
    assert_eq!(zero.task_logits, vec![0.0, 0.0]);
    assert_eq!(zero.task_probabilities, vec![0.5, 0.5]);
    assert_eq!(zero.predicted_class, 0); // Ties retain the first task class.
    assert!(!zero.accepted);
}

#[test]
fn missing_required_modalities_return_no_prediction_before_arithmetic() {
    let (header, weights) = fixture();
    let head = must(load(&header, &weights));
    for mask in [0, 1, 2] {
        // Invalid numeric input must never reach scoring when presence rejects.
        assert_eq!(
            head.predict(&[f32::NAN], head.feature_identity(), mask),
            Err(TaskHeadError::MissingRequiredModality)
        );
    }
    assert_eq!(
        head.predict(&[1.0, -2.0, 0.0, 0.0, 0.0], head.feature_identity(), 0x83),
        Err(TaskHeadError::InvalidPresenceMask)
    );
}

#[test]
fn exact_identity_and_revocation_epoch_are_required_at_use() {
    let (header, weights) = fixture();
    let head = must(load(&header, &weights));
    for field in [
        "encoder_sha256",
        "preprocess_sha256",
        "checkpoint_revision",
        "scope_id",
        "purpose",
        "generation",
        "revocation_epoch",
    ] {
        let mut changed = header["feature_identity"].clone();
        changed[field] = match field {
            "generation" | "revocation_epoch" => json!(2),
            "checkpoint_revision" => json!("b".repeat(40)),
            "encoder_sha256" | "preprocess_sha256" => {
                json!(Digest32::of_bytes(b"other").to_string())
            }
            _ => json!("different"),
        };
        let identity = must(serde_json::from_value(changed));
        assert_eq!(
            head.predict(&[1.0, -2.0, 0.0, 0.0, 0.0], &identity, 3),
            Err(TaskHeadError::FeatureIdentityMismatch)
        );
    }
}

#[test]
fn manifest_pin_payload_hash_and_exact_shape_are_independent_fences() {
    let (mut header, mut weights) = fixture();
    let original = must(serde_json::to_vec(&header));
    header["temperature"] = json!(1.0);
    assert_error(
        LoadedTaskHeadV1::from_artifact(
            &must(serde_json::to_vec(&header)),
            &weights,
            Digest32::of_bytes(&original),
        ),
        TaskHeadError::ManifestDigestMismatch,
    );
    weights[0] ^= 1;
    assert_error(
        load(&header, &weights),
        TaskHeadError::WeightsDigestMismatch,
    );
    weights.extend(1.0_f32.to_le_bytes());
    header["weights_sha256"] = json!(Digest32::of_bytes(&weights).to_string());
    header["weights_bytes"] = json!(weights.len());
    assert_error(load(&header, &weights), TaskHeadError::WeightsShape);
}

#[test]
fn unknown_fields_and_contract_relaxations_are_rejected() {
    let (header, weights) = fixture();
    for (field, value) in [
        ("schema", json!("hepta.native-task-head.v2")),
        ("numeric_profile", json!("tanh-gelu")),
        ("state_contract", json!("recurrent")),
        ("mode", json!("ACTIVE")),
        ("authority", json!("ALLOW_ALL")),
        ("feature_layout", json!("other-layout")),
        ("required_present_mask", json!(0)),
        ("required_present_mask", json!(1)),
        ("required_present_mask", json!(2)),
        ("required_present_mask", json!(31)),
        ("required_present_mask", json!(128)),
        ("temperature", json!(0.0)),
        ("confidence_threshold", json!(1.1)),
    ] {
        let mut changed = header.clone();
        changed[field] = value;
        assert_error(load(&changed, &weights), TaskHeadError::ManifestContract);
    }
    let mut unknown = header.clone();
    unknown["action_policy"] = json!(true);
    assert_error(load(&unknown, &weights), TaskHeadError::ManifestEncoding);
    let mut unknown_identity = header;
    unknown_identity["feature_identity"]["extra"] = json!(0);
    assert_error(
        load(&unknown_identity, &weights),
        TaskHeadError::ManifestEncoding,
    );
}

#[test]
fn bounded_metadata_rejects_oversized_dimensions_before_tensor_allocation() {
    let (header, weights) = fixture();
    for (field, value) in [
        ("width", 4097),
        ("width", 4),
        ("width", 6),
        ("state_width", 65),
        ("adapter_rank", 17),
        ("task_count", 257),
    ] {
        let mut changed = header.clone();
        changed[field] = json!(value);
        assert_error(load(&changed, &weights), TaskHeadError::ManifestContract);
    }
    let mut many_parameters = header;
    many_parameters["width"] = json!(4093);
    many_parameters["task_count"] = json!(256);
    assert_error(
        load(&many_parameters, &weights),
        TaskHeadError::ArtifactBounds,
    );
    let large = vec![b' '; MAX_MANIFEST_BYTES + 1];
    assert_error(
        LoadedTaskHeadV1::from_artifact(&large, &weights, Digest32::of_bytes(&large)),
        TaskHeadError::ArtifactBounds,
    );
}

#[test]
fn invalid_identity_encodings_and_duplicate_keys_are_not_admitted() {
    let (header, weights) = fixture();
    for (field, value) in [
        ("encoder_sha256", json!("0".repeat(64))),
        ("preprocess_sha256", json!("G".repeat(64))),
        ("checkpoint_revision", json!("short")),
        ("scope_id", json!("bad/name")),
        ("purpose", json!("x".repeat(129))),
        ("generation", json!(0)),
    ] {
        let mut changed = header.clone();
        changed["feature_identity"][field] = value;
        assert_error(load(&changed, &weights), TaskHeadError::ManifestContract);
    }
    let mut duplicate = must(serde_json::to_string(&header));
    duplicate.pop();
    duplicate.push_str(",\"width\":2}");
    assert_error(
        LoadedTaskHeadV1::from_artifact(
            duplicate.as_bytes(),
            &weights,
            Digest32::of_bytes(duplicate.as_bytes()),
        ),
        TaskHeadError::ManifestEncoding,
    );
}

#[test]
fn nonfinite_parameters_inputs_and_finite_overflow_fail_closed() {
    let (header, weights) = fixture();
    let head = must(load(&header, &weights));
    assert_eq!(
        head.predict(&[1.0], head.feature_identity(), 3),
        Err(TaskHeadError::FeatureShape)
    );
    for nonfinite in [f32::NAN, f32::INFINITY, f32::NEG_INFINITY] {
        assert_eq!(
            head.predict(&[1.0, nonfinite, 0.0, 0.0, 0.0], head.feature_identity(), 3),
            Err(TaskHeadError::NonFinite)
        );
        let mut changed = weights.clone();
        changed[..4].copy_from_slice(&nonfinite.to_le_bytes());
        let mut declared = header.clone();
        declared["weights_sha256"] = json!(Digest32::of_bytes(&changed).to_string());
        assert_error(load(&declared, &changed), TaskHeadError::NonFinite);
    }
    let mut changed = weights;
    changed[..4].copy_from_slice(&f32::MAX.to_le_bytes());
    let mut declared = header;
    declared["weights_sha256"] = json!(Digest32::of_bytes(&changed).to_string());
    let huge = must(load(&declared, &changed));
    assert_eq!(
        huge.predict(&[f32::MAX, 1.0, 0.0, 0.0, 0.0], huge.feature_identity(), 3),
        Err(TaskHeadError::NonFinite)
    );
}

#[test]
fn erf_branches_match_high_precision_values_and_preserve_odd_symmetry() {
    // Independently tabulated values, including both sides of the algorithm boundary.
    for (x, expected) in [
        (0.0, 0.0),
        (0.5, 0.5204998778130465),
        (1.0, 0.8427007929497149),
        (2.0, 0.9953222650189527),
        (2.99, 0.9999764743969194),
        (3.0, 0.9999779095030014),
        (4.0, 0.9999999845827421),
        (6.0, 1.0),
    ] {
        assert!((erf_bounded(x) - expected).abs() < 1e-12, "x={x}");
        assert!((erf_bounded(-x) + expected).abs() < 1e-12, "x={x}");
    }
}
