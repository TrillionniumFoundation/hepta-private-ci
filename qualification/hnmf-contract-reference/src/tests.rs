use super::*;

fn digest(character: char) -> Digest32 {
    Digest32::parse(std::iter::repeat_n(character, 64).collect::<String>())
        .unwrap_or_else(|error| panic!("valid digest: {error}"))
}

fn span(modality: ModalityKind, range: SpanRange) -> ModalitySpanRef {
    ModalitySpanRef {
        span_id: 1,
        modality,
        asset_sha256: digest('a'),
        range,
        preprocessor_manifest_sha256: digest('b'),
        feature_blob_sha256: None,
        symbolic_projection_sha256: None,
        uncertainty_ppm: 0,
        privacy_class: PrivacyClass::AgentPrivate,
        redaction_mask_sha256: None,
        authority: AuthorityPostureV1::DENY_ALL,
    }
}

#[test]
fn reference_uses_production_span_contract() {
    let value = span(
        ModalityKind::Text,
        SpanRange::ByteRange { start: 0, end: 4 },
    );
    value
        .validate()
        .unwrap_or_else(|error| panic!("production contract must validate: {error}"));
    assert!(value.encode_canonical_json().is_ok());
}

#[test]
fn reference_cannot_redefine_modality_semantics() {
    let value = span(
        ModalityKind::Audio,
        SpanRange::ByteRange { start: 0, end: 4 },
    );
    assert!(value.validate().is_err());
}

#[test]
fn authority_posture_is_compile_time_false() {
    assert_eq!(
        [
            CURRENT_RUN_MUTATION_ALLOWED,
            ONLINE_TOPOLOGY_ACTIVATION_ALLOWED,
            PRODUCTION_AUTHORITY,
            EXTERNAL_EFFECTS_ALLOWED,
        ],
        [false; 4]
    );
}
