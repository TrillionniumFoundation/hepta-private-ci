use super::*;

fn sample_projector() -> LowRankStemProjectionV1 {
    let q = 1_i64 << 24;
    LowRankStemProjectionV1 {
        encoder_digest: "a".repeat(64),
        preprocessor_digest: "b".repeat(64),
        runtime_digest: "c".repeat(64),
        normalizer_digest: "d".repeat(64),
        representation: "mean".to_string(),
        input_width: 3,
        output_width: 2,
        rank: 1,
        a_q24: vec![q, 0, 0],
        b_q24: vec![q, q],
        bias_q24: vec![0, 0],
    }
}

fn payload_for(projection: &LowRankStemProjectionV1) -> Vec<u8> {
    serde_json::to_vec(&serde_json::json!({
        "schema": STEM_PROJECTION_SCHEMA,
        "projection": projection,
    }))
    .expect("serialize projection")
}

#[test]
fn strict_cas_projection_payload_roundtrip_matches_numeric_digest() {
    let projection = sample_projector();
    let expected = projection.digest().expect("digest");
    let bytes = payload_for(&projection);
    let recovered = decode_projection(&bytes).expect("decode");
    assert_eq!(recovered, projection);
    assert_eq!(recovered.digest().expect("digest"), expected);
    assert_eq!(
        recovered
            .project_float32(&[0.5, -0.25, 0.125])
            .expect("project"),
        vec![1 << 23, 1 << 23]
    );
}

#[test]
fn malformed_or_unknown_payload_fails_closed() {
    let p = sample_projector();
    let original = serde_json::from_slice::<serde_json::Value>(&payload_for(&p))
        .expect("json");
    let mut invalid = original.clone();
    invalid["schema"] = serde_json::json!("hepta.stem.future");
    assert!(matches!(
        decode_projection(&serde_json::to_vec(&invalid).expect("serialize")),
        Err(StemProjectionArtifactError::InvalidPayload)
    ));
    let mut unknown = original.clone();
    unknown["unregistered"] = serde_json::json!(true);
    assert!(matches!(
        decode_projection(&serde_json::to_vec(&unknown).expect("serialize")),
        Err(StemProjectionArtifactError::InvalidPayload)
    ));
    let mut shape = original.clone();
    shape["projection"]["input_width"] = serde_json::json!(768);
    assert!(matches!(
        decode_projection(&serde_json::to_vec(&shape).expect("serialize")),
        Err(StemProjectionArtifactError::InvalidPayload)
    ));
    let mut overlong = payload_for(&p);
    overlong.extend_from_slice(&vec![b' '; MAX_STEM_PROJECTION_JSON_BYTES]);
    assert!(matches!(
        decode_projection(&overlong),
        Err(StemProjectionArtifactError::InvalidPayload)
    ));
}

#[test]
fn digest_binding_changes_on_normalizer_or_weight_change() {
    let base = sample_projector();
    let expected = base.digest().expect("digest");
    let mut mutated = base.clone();
    mutated.normalizer_digest = "e".repeat(64);
    assert_ne!(mutated.digest().expect("digest"), expected);
    mutated = base;
    mutated.a_q24[0] += 1;
    assert_ne!(mutated.digest().expect("digest"), expected);
}

#[test]
fn invalid_numeric_range_and_extra_coefficients_rejected() {
    let mut bad = sample_projector();
    bad.a_q24[0] = 9 * (1_i64 << 24);
    assert!(matches!(
        decode_projection(&payload_for(&bad)),
        Err(StemProjectionArtifactError::InvalidPayload)
    ));
    let mut bad = sample_projector();
    bad.bias_q24.push(0);
    assert!(matches!(
        decode_projection(&payload_for(&bad)),
        Err(StemProjectionArtifactError::InvalidPayload)
    ));
}
