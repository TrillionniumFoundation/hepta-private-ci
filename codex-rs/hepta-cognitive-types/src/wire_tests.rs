use super::*;
use crate::hnmf::CanonicalIdV1;
use crate::hnmf::ModalitySpanRefV1;
use crate::hnmf::ModalityV1;
use crate::hnmf::PrivacyClassV1;
use crate::hnmf::Sha256DigestV1;
use crate::hnmf::SpanRangeV1;

fn id(value: &str) -> CanonicalIdV1 {
    CanonicalIdV1::new(value)
        .unwrap_or_else(|error| panic!("valid canonical id required: {error}"))
}

fn digest(character: char) -> Sha256DigestV1 {
    Sha256DigestV1::new(std::iter::repeat_n(character, 64).collect::<String>())
        .unwrap_or_else(|error| panic!("valid digest required: {error}"))
}

fn span() -> ModalitySpanRefV1 {
    ModalitySpanRefV1 {
        span_id: id("span:1"),
        modality: ModalityV1::Text,
        asset_sha256: digest('a'),
        range: SpanRangeV1::ByteRange { start: 0, end: 4 },
        preprocessor_manifest_sha256: digest('b'),
        feature_blob_sha256: None,
        symbolic_projection_sha256: None,
        uncertainty_ppm: 0,
        privacy_class: PrivacyClassV1::AgentPrivate,
        redaction_mask_sha256: None,
    }
}

#[test]
fn ctype_04_cross_language_canonical_vector_is_stable() {
    let value = span();
    let encoded = encode_canonical_json(&value)
        .unwrap_or_else(|error| panic!("canonical encoding must succeed: {error}"));
    let expected = concat!(
        "{\"spanId\":\"span:1\",\"modality\":\"text\",\"assetSha256\":\"",
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "\",\"range\":{\"kind\":\"byte_range\",\"start\":0,\"end\":4},",
        "\"preprocessorManifestSha256\":\"",
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "\",\"featureBlobSha256\":null,\"symbolicProjectionSha256\":null,",
        "\"uncertaintyPpm\":0,\"privacyClass\":\"agent_private\",",
        "\"redactionMaskSha256\":null}"
    );
    assert_eq!(encoded, expected.as_bytes());

    let digest = contract_digest(&value)
        .unwrap_or_else(|error| panic!("canonical digest must succeed: {error}"));
    assert_eq!(
        digest.to_string(),
        "6ffdc8479ea47c1f761cddc3542a74e2e50a3521dd54aaa40d57aceca27ed9f2"
    );

    let decoded = decode_canonical_json::<ModalitySpanRefV1>(&encoded)
        .unwrap_or_else(|error| panic!("canonical decoding must succeed: {error}"));
    assert_eq!(decoded, value);
}

#[test]
fn unknown_missing_and_invalid_fields_fail_closed() {
    let encoded = String::from_utf8(
        encode_canonical_json(&span())
            .unwrap_or_else(|error| panic!("canonical encoding must succeed: {error}")),
    )
    .unwrap_or_else(|error| panic!("canonical JSON is UTF-8: {error}"));

    let unknown = encoded.replacen(
        "\"spanId\":\"span:1\"",
        "\"spanId\":\"span:1\",\"unexpected\":true",
        1,
    );
    assert!(decode_canonical_json::<ModalitySpanRefV1>(unknown.as_bytes()).is_err());

    let missing = encoded.replacen(
        concat!(
            "\"assetSha256\":\"",
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "\","
        ),
        "",
        1,
    );
    assert!(decode_canonical_json::<ModalitySpanRefV1>(missing.as_bytes()).is_err());

    let invalid_enum = encoded.replacen("\"modality\":\"text\"", "\"modality\":\"telepathy\"", 1);
    assert!(decode_canonical_json::<ModalitySpanRefV1>(invalid_enum.as_bytes()).is_err());
}

#[test]
fn non_canonical_json_is_rejected_after_semantic_decode() {
    let encoded = encode_canonical_json(&span())
        .unwrap_or_else(|error| panic!("canonical encoding must succeed: {error}"));
    let mut padded = Vec::with_capacity(encoded.len() + 1);
    padded.push(b' ');
    padded.extend_from_slice(&encoded);
    assert!(matches!(
        decode_canonical_json::<ModalitySpanRefV1>(&padded),
        Err(CanonicalWireError::NonCanonicalJson { .. })
    ));
}

#[test]
fn encoded_size_is_checked_before_parse() {
    let oversized = vec![b' '; ModalitySpanRefV1::MAX_ENCODED_BYTES + 1];
    assert!(matches!(
        decode_canonical_json::<ModalitySpanRefV1>(&oversized),
        Err(CanonicalWireError::EncodedSizeExceeded { .. })
    ));
}

#[test]
fn schema_domain_separates_identical_json_shapes() {
    assert_eq!(schema_id::<ModalitySpanRefV1>(), "ModalitySpanRefV1");
}
