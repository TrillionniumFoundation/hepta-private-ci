use super::*;
use crate::cell_test_support::checked;
use crate::cell_test_support::d;
use crate::cell_test_support::scope;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

// Produced independently with Python hashlib.sha256 and sorted compact JSON.
const PYTHON_RECEIPT: &str = r#"{"authority":"DENY_ALL","conversion_sha256":"b4411703c9b8794c3a807caf119f10ea741aa62f81c957404ca75b4f6ec0ad84","feature_vector_q24":[16777216,8388608],"legacy_head_parity_qualified":false,"numeric_profile":"signed-q24-nearest-ties-even-v1","row":0,"schema":"hepta.feature-global-q24-conversion.v1","source_bundle_sha256":"69254f58858d38e25d1294190830d812f68d1c98a702aa8afd85c7d73c5189b9","source_record_digest":"70ce871f8a3d3fb449bc3c3ace6547cef02dfc74ffe48d912532a724bfdbe5b9"}"#;

fn binding() -> CellFeatureProjectionBindingV1 {
    CellFeatureProjectionBindingV1 {
        scope_digest: scope("run1").digest(),
        source_frontier: d("frontier"),
        encoder_digest: d("encoder"),
        source_bundle_digest: d("bundle-source"),
        source_record_digest: d("record"),
        conversion_digest: checked("b4411703c9b8794c3a807caf119f10ea741aa62f81c957404ca75b4f6ec0ad84".parse()),
        row: 0,
        width: 2,
    }
}

fn resealed(field: &str, value: Value) -> (Vec<u8>, CellFeatureProjectionBindingV1) {
    let mut fields: BTreeMap<String, Value> = checked(serde_json::from_str(PYTHON_RECEIPT));
    fields.remove("conversion_sha256");
    fields.insert(field.to_string(), value);
    let seal = Digest32::of_bytes(&checked(serde_json::to_vec(&fields)));
    fields.insert("conversion_sha256".to_string(), json!(seal.to_string()));
    let mut expected = binding();
    expected.conversion_digest = seal;
    (checked(serde_json::to_vec(&fields)), expected)
}

#[test]
fn python_receipt_projects_exact_values_and_normalizes_only_serialization() {
    let projection = checked(CellGlobalFeatureProjectionV1::from_json(PYTHON_RECEIPT.as_bytes(), binding()));
    let parsed: Value = checked(serde_json::from_str(PYTHON_RECEIPT));
    let pretty = checked(serde_json::to_vec_pretty(&parsed));
    assert_eq!(checked(CellGlobalFeatureProjectionV1::from_json(&pretty, binding())), projection);
    assert_eq!(projection.observation_bytes(), PYTHON_RECEIPT.as_bytes());
    assert_eq!(projection.schema_digest(), checked(cell_global_feature_schema_digest_v1(/*width*/2)));
    let request_scope = scope("run1");
    assert_eq!(projection.encode(&CellEncodingRequestV1 {
        scope: &request_scope,
        source_frontier: d("frontier"),
        encoder_digest: d("encoder"),
        observation: projection.observation_bytes(),
        checkpoint: None,
    }), Ok(CellEncodedInputV1 {
        encoder_digest: d("encoder"),
        feature_vector_q24: vec![1 << 24, 1 << 23],
        consumed_bytes: PYTHON_RECEIPT.len(),
        truncated_bytes: 0,
    }));
}

#[test]
fn changed_vector_cannot_be_admitted_by_recomputing_its_own_seal() {
    let changed = PYTHON_RECEIPT.replace("[16777216,8388608]", "[8388608,16777216]");
    assert_eq!(CellGlobalFeatureProjectionV1::from_json(changed.as_bytes(), binding()), Err(CellExecutionError::EncodingMismatch));
    let (raw, new_owner_pin) = resealed("feature_vector_q24", json!([8388608, 16777216]));
    assert_eq!(CellGlobalFeatureProjectionV1::from_json(&raw, binding()), Err(CellExecutionError::EncodingMismatch));
    // A separately changed owner pin admits a new projection; self-sealing alone does not.
    let projection = checked(CellGlobalFeatureProjectionV1::from_json(&raw, new_owner_pin));
    assert_ne!(projection.observation_bytes(), PYTHON_RECEIPT.as_bytes());
}

#[test]
fn numeric_types_range_and_width_reject_without_coercion() {
    for value in [
        json!([true, 8388608]),
        json!([16777216.0, 8388608]),
        json!(["16777216", 8388608]),
        json!([u64::MAX, 8388608]),
        json!([134217729, 8388608]),
        json!([-134217729, 8388608]),
        json!([16777216]),
        json!([16777216, 8388608, 0]),
    ] {
        let (raw, owner_pin) = resealed("feature_vector_q24", value);
        assert_eq!(CellGlobalFeatureProjectionV1::from_json(&raw, owner_pin), Err(CellExecutionError::EncodingMismatch));
    }
    let (raw, owner_pin) = resealed("feature_vector_q24", json!([-134217728, 134217728]));
    assert!(CellGlobalFeatureProjectionV1::from_json(&raw, owner_pin).is_ok());
}

#[test]
fn duplicate_unknown_and_trailing_fields_cannot_hide_a_second_interpretation() {
    for raw in [
        PYTHON_RECEIPT.replace("\"row\":0", "\"row\":0,\"row\":0"),
        PYTHON_RECEIPT.replace("\"row\":0", "\"row\":0,\"row\":1"),
        PYTHON_RECEIPT.replace("\"row\":0", "\"row\":0,\"extra\":false"),
        format!("{PYTHON_RECEIPT} {{}}"),
    ] {
        assert_eq!(CellGlobalFeatureProjectionV1::from_json(raw.as_bytes(), binding()), Err(CellExecutionError::EncodingMismatch));
    }
    let (raw, owner_pin) = resealed("extra", json!(false));
    assert_eq!(CellGlobalFeatureProjectionV1::from_json(&raw, owner_pin), Err(CellExecutionError::EncodingMismatch));
}

#[test]
fn authority_profile_source_and_row_remain_bound_even_with_a_valid_hash() {
    for (field, value) in [
        ("authority", json!("ALLOW_ALL")),
        ("legacy_head_parity_qualified", json!(true)),
        ("schema", json!("hepta.feature-global-q24-conversion.v2")),
        ("numeric_profile", json!("float32")),
        ("source_bundle_sha256", json!(d("other-bundle").to_string())),
        ("source_record_digest", json!(d("other-record").to_string())),
        ("row", json!(1)),
        ("row", json!(true)),
        ("row", json!(0.0)),
    ] {
        let (raw, owner_pin) = resealed(field, value);
        assert_eq!(CellGlobalFeatureProjectionV1::from_json(&raw, owner_pin), Err(CellExecutionError::EncodingMismatch));
    }
}

#[test]
fn incomplete_pins_and_oversized_inputs_are_rejected_before_projection() {
    for index in 0..6 {
        let mut expected = binding();
        match index {
            0 => expected.scope_digest = Digest32::ZERO,
            1 => expected.source_frontier = Digest32::ZERO,
            2 => expected.encoder_digest = Digest32::ZERO,
            3 => expected.source_bundle_digest = Digest32::ZERO,
            4 => expected.source_record_digest = Digest32::ZERO,
            5 => expected.conversion_digest = Digest32::ZERO,
            _ => unreachable!("fixture index"),
        }
        assert_eq!(CellGlobalFeatureProjectionV1::from_json(PYTHON_RECEIPT.as_bytes(), expected), Err(CellExecutionError::EncodingMismatch));
    }
    for width in [0, 513] {
        let mut expected = binding();
        expected.width = width;
        assert_eq!(CellGlobalFeatureProjectionV1::from_json(PYTHON_RECEIPT.as_bytes(), expected), Err(CellExecutionError::CapacityExceeded));
    }
    let mut expected = binding();
    expected.row = 512;
    assert_eq!(CellGlobalFeatureProjectionV1::from_json(PYTHON_RECEIPT.as_bytes(), expected), Err(CellExecutionError::CapacityExceeded));
    let mut padded = PYTHON_RECEIPT.as_bytes().to_vec();
    padded.resize(65_537, b' ');
    assert_eq!(CellGlobalFeatureProjectionV1::from_json(&padded, binding()), Err(CellExecutionError::CapacityExceeded));
}

#[test]
fn projection_cannot_cross_scope_frontier_encoder_or_observation() {
    let projection = checked(CellGlobalFeatureProjectionV1::from_json(PYTHON_RECEIPT.as_bytes(), binding()));
    let original_scope = scope("run1");
    let other_scope = scope("run2");
    let mut request = CellEncodingRequestV1 {
        scope: &original_scope,
        source_frontier: d("frontier"),
        encoder_digest: d("encoder"),
        observation: projection.observation_bytes(),
        checkpoint: None,
    };
    request.scope = &other_scope;
    assert_eq!(projection.encode(&request), Err(CellExecutionError::ScopeMismatch));
    request.scope = &original_scope;
    request.source_frontier = d("next-frontier");
    assert_eq!(projection.encode(&request), Err(CellExecutionError::StaleSource));
    request.source_frontier = d("frontier");
    request.encoder_digest = d("other-encoder");
    assert_eq!(projection.encode(&request), Err(CellExecutionError::EncodingMismatch));
    request.encoder_digest = d("encoder");
    request.observation = b"substituted";
    assert_eq!(projection.encode(&request), Err(CellExecutionError::EncodingMismatch));
}
