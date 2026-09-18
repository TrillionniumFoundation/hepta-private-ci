use super::*;

fn digest(character: char) -> Sha256DigestV1 {
    Sha256DigestV1::parse(std::iter::repeat_n(character, 64).collect::<String>())
        .unwrap_or_else(|error| panic!("valid digest: {error}"))
}

fn authority() -> AuthorityPostureV1 {
    AuthorityPostureV1::DENY_ALL
}

fn span(span_id: u64, modality: ModalityKindV1, range: SpanRangeV1) -> ModalitySpanRefV1 {
    ModalitySpanRefV1 {
        span_id,
        modality,
        asset_sha256: digest('a'),
        range,
        preprocessor_manifest_sha256: digest('b'),
        feature_blob_sha256: Some(digest('c')),
        symbolic_projection_sha256: None,
        uncertainty_ppm: 10_000,
        privacy_class: PrivacyClassV1::AgentPrivate,
        redaction_mask_sha256: None,
        authority: authority(),
    }
}

fn text_span(span_id: u64) -> ModalitySpanRefV1 {
    span(
        span_id,
        ModalityKindV1::Text,
        SpanRangeV1::ByteRange { start: 0, end: 4 },
    )
}

fn event() -> MemoryEventV1 {
    MemoryEventV1 {
        event_id: 7,
        episode_id: 3,
        scope: MemoryScopeV1::AgentPrivate {
            agent_id: "agent-a".to_string(),
        },
        observed_interval: TimeIntervalV1 {
            start_unix_ms: 1,
            end_unix_ms: Some(10),
        },
        modality_spans: vec![text_span(1)],
        cross_modal_bindings: Vec::new(),
        semantic_keys: vec!["door".to_string(), "red".to_string()],
        provenance: vec![ProvenanceRefV1 {
            source_id: "source-1".to_string(),
            source_revision: 1,
            source_sha256: digest('d'),
            observed_at_unix_ms: 1,
        }],
        verification: MemoryVerificationStateV1::Verified,
        retention_policy: RetentionPolicyV1 {
            expires_unix_ms: None,
            legal_hold: false,
            session_only: false,
        },
        objective_digest: digest('e'),
        ndu_state_digest: digest('f'),
        causal_parent_event_ids: vec![1, 2],
        temporal_neighbor_event_ids: vec![8],
        behavior_propensity_ppm: Some(500_000),
        lifecycle: MemoryLifecycleV1::Active,
        authority: authority(),
    }
}

#[test]
fn ctype_01_text_bytes_cannot_be_audio_samples() {
    let wrong = span(
        1,
        ModalityKindV1::Audio,
        SpanRangeV1::ByteRange { start: 0, end: 4 },
    );
    assert_eq!(
        wrong.validate(),
        Err(HnmfContractError::Invalid(
            "span range kind does not match modality"
        ))
    );
}

#[test]
fn ctype_02_out_of_bounds_selectors_reject() {
    let image = span(
        1,
        ModalityKindV1::Image,
        SpanRangeV1::PixelRect {
            x: 7,
            y: 7,
            width: 2,
            height: 2,
            image_width: 8,
            image_height: 8,
        },
    );
    assert!(image.validate().is_err());

    let video = span(
        2,
        ModalityKindV1::Video,
        SpanRangeV1::FrameRange {
            start: 0,
            end: 11,
            frame_count: 10,
            timebase_num: 1,
            timebase_den: 30,
        },
    );
    assert!(video.validate().is_err());

    let ast = span(
        3,
        ModalityKindV1::CodeAst,
        SpanRangeV1::AstPath {
            path: vec![0, 4],
            node_count: 4,
        },
    );
    assert!(ast.validate().is_err());
}

#[test]
fn ctype_03_correction_and_tombstone_are_not_provenance() {
    let mut correction = event();
    correction.lifecycle = MemoryLifecycleV1::Correction {
        corrects_event_id: 6,
    };
    correction
        .validate()
        .unwrap_or_else(|error| panic!("valid correction: {error}"));

    let mut tombstone = event();
    tombstone.lifecycle = MemoryLifecycleV1::Tombstoned {
        reason_sha256: digest('1'),
    };
    tombstone
        .validate()
        .unwrap_or_else(|error| panic!("valid tombstone: {error}"));

    assert_ne!(
        correction.semantic_digest().unwrap(),
        tombstone.semantic_digest().unwrap()
    );
    assert_eq!(correction.provenance, tombstone.provenance);
}

#[test]
fn ctype_04_canonical_json_has_stable_cross_language_shape() {
    let value = text_span(1);
    let encoded = value
        .encode_canonical_json()
        .unwrap_or_else(|error| panic!("canonical JSON: {error}"));
    let expected = concat!(
        "{\"schema\":\"ModalitySpanRefV1\",\"schemaVersion\":1,\"payload\":{",
        "\"spanId\":\"1\",\"modality\":\"text\",",
        "\"assetSha256\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\",",
        "\"range\":{\"kind\":\"byte_range\",\"start\":\"0\",\"end\":\"4\"},",
        "\"preprocessorManifestSha256\":\"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\",",
        "\"featureBlobSha256\":\"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc\",",
        "\"symbolicProjectionSha256\":null,\"uncertaintyPpm\":10000,",
        "\"privacyClass\":\"agent_private\",\"redactionMaskSha256\":null,",
        "\"authority\":{\"runtime\":false,\"productionWriter\":false,\"modelInvocation\":false,",
        "\"providerDispatch\":false,\"externalEffect\":false,\"selection\":false,",
        "\"promotion\":false,\"release\":false}}}"
    );
    assert_eq!(String::from_utf8(encoded.clone()).unwrap(), expected);
    assert_eq!(
        value.semantic_digest().unwrap().to_string(),
        "1a436027bbf8888d91126e947eb7cdf65ef6e88753a1c5c904294493990781e2"
    );
    let decoded = ModalitySpanRefV1::decode_json(&encoded).unwrap();
    assert_eq!(decoded, value);
    assert_eq!(decoded.asset_sha256.as_str(), "a".repeat(64).as_str());
    assert_eq!(
        decoded.preprocessor_manifest_sha256.as_str(),
        "b".repeat(64).as_str()
    );
}

#[test]
fn unknown_fields_and_invalid_enums_fail_closed() {
    let encoded = text_span(1).encode_canonical_json().unwrap();
    let mut envelope_unknown: serde_json::Value = serde_json::from_slice(&encoded).unwrap();
    envelope_unknown
        .as_object_mut()
        .unwrap()
        .insert("unknownCritical".to_string(), serde_json::Value::Bool(true));
    assert!(
        ModalitySpanRefV1::decode_json(&serde_json::to_vec(&envelope_unknown).unwrap()).is_err()
    );

    let mut payload_unknown: serde_json::Value = serde_json::from_slice(&encoded).unwrap();
    payload_unknown["payload"]
        .as_object_mut()
        .unwrap()
        .insert("unknownCritical".to_string(), serde_json::Value::Bool(true));
    assert!(
        ModalitySpanRefV1::decode_json(&serde_json::to_vec(&payload_unknown).unwrap()).is_err()
    );

    let invalid = String::from_utf8(encoded)
        .unwrap()
        .replace("\"modality\":\"text\"", "\"modality\":\"unknown\"");
    assert!(ModalitySpanRefV1::decode_json(invalid.as_bytes()).is_err());
}

#[test]
fn canonical_collections_require_sorted_unique_values() {
    let mut value = event();
    value.semantic_keys = vec!["red".to_string(), "door".to_string()];
    assert!(value.validate().is_err());

    let mut value = event();
    value.causal_parent_event_ids = vec![2, 1];
    assert!(value.validate().is_err());
}

#[test]
fn encoded_size_is_enforced_before_decode() {
    let oversized = vec![b' '; ModalitySpanRefV1::MAX_ENCODED_BYTES + 1];
    assert_eq!(
        ModalitySpanRefV1::decode_json(&oversized),
        Err(HnmfContractError::EncodedSize {
            actual: ModalitySpanRefV1::MAX_ENCODED_BYTES + 1,
            maximum: ModalitySpanRefV1::MAX_ENCODED_BYTES,
        })
    );
}

#[test]
fn event_round_trip_binds_semantics_and_deny_all_authority() {
    let value = event();
    let encoded = value.encode_canonical_json().unwrap();
    let decoded = MemoryEventV1::decode_json(&encoded).unwrap();
    assert_eq!(decoded, value);
    assert!(!decoded.authority.grants_any());
    assert!(!decoded.semantic_digest().unwrap().is_zero());
}

#[test]
fn u64_wire_values_remain_exact_above_javascript_safe_integer() {
    let mut value = text_span(9_007_199_254_740_993);
    value.range = SpanRangeV1::ByteRange {
        start: 9_007_199_254_740_993,
        end: 9_007_199_254_740_994,
    };
    let encoded = value.encode_canonical_json().unwrap();
    let text = String::from_utf8(encoded.clone()).unwrap();
    assert!(text.contains("\"spanId\":\"9007199254740993\""));
    assert!(text.contains("\"start\":\"9007199254740993\""));
    assert_eq!(ModalitySpanRefV1::decode_json(&encoded).unwrap(), value);
}

#[test]
fn topology_and_plasticity_cannot_self_activate() {
    let topology = CognitiveTopologyProposalV1 {
        predecessor_generation: 7,
        next_generation: 8,
        operation: CognitiveTopologyOperationV1::SplitNode {
            node_id: 3,
            labels: ["door-red".to_string(), "door-blue".to_string()],
        },
        capability_typed: true,
        sandbox_only: true,
        operator_accepted: false,
        production_activation_allowed: false,
        authority: authority(),
    };
    topology.validate().unwrap();

    let invalid = CognitiveTopologyProposalV1 {
        production_activation_allowed: true,
        ..topology
    };
    assert_eq!(invalid.validate(), Err(HnmfContractError::AuthorityGranted));

    let plasticity = PlasticityBatchV1 {
        predecessor_generation: 7,
        next_generation: 8,
        outcome_signal_digest: digest('2'),
        weight_proposals: Vec::new(),
        threshold_proposals: Vec::new(),
        current_snapshot_immutable: true,
        production_activation_allowed: false,
        authority: authority(),
    };
    plasticity.validate().unwrap();
}
