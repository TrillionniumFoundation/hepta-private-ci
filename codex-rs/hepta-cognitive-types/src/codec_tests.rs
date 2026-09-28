// Included alongside the existing canonical fixtures.

fn assert_reference_envelope<T: CognitiveContractV1>(value: &T) {
    let payload = encode_payload_canonical_v1(value).expect("checked payload");
    let mut entries = std::collections::BTreeMap::new();
    entries.insert("contract", serde_json::json!(T::CONTRACT_ID));
    entries.insert(
        "payload",
        serde_json::from_slice::<serde_json::Value>(&payload).expect("payload"),
    );
    entries.insert("schema", serde_json::json!(T::SCHEMA_ID));
    entries.insert(
        "schemaVersion",
        serde_json::json!(COGNITIVE_WIRE_VERSION_V1),
    );
    let expected = serde_json::to_vec(&entries).expect("reference envelope");
    let actual = encode_wire_v1(value).expect("optimized envelope");
    assert_eq!(actual, expected);
    assert!(decode_wire_v1::<T>(&actual).is_ok());
}

#[test]
fn reused_payload_encoder_preserves_all_twelve_reference_envelopes() {
    assert_reference_envelope(&text_span());
    assert_reference_envelope(&event());
    assert_reference_envelope(&cross_binding());
    assert_reference_envelope(&engram_node());
    assert_reference_envelope(&synapse());
    assert_reference_envelope(&cue());
    assert_reference_envelope(&recall_packet());
    assert_reference_envelope(&outcome());
    assert_reference_envelope(&replay_receipt());
    assert_reference_envelope(&plasticity());
    assert_reference_envelope(&topology());
    assert_reference_envelope(&forget());
}

proptest::proptest! {
    #[test]
    fn real_event_codec_preserves_unicode_and_exact_u64_profiles(
        time in 1u64..u64::MAX,
        suffix in "[a-z]{1,32}",
    ) {
        let mut value = event();
        value.observed_interval.start_unix_ms = time;
        value.provenance[0].observed_at_unix_ms = time;
        value.semantic_keys.insert(format!("é-{suffix}"));
        assert_reference_envelope(&value);
        let before = canonical_contract_digest_v1(&value).expect("digest");
        let bytes = encode_wire_v1(&value).expect("encode");
        let decoded: MemoryEventV1 = decode_wire_v1(&bytes).expect("decode");
        proptest::prop_assert_eq!(before, canonical_contract_digest_v1(&decoded).expect("digest"));
    }
}
