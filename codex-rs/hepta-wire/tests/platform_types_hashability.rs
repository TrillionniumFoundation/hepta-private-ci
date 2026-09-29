//! Exercise the real product decoder, not a shadow implementation of its rules.
use codex_hepta_wire::decode_prompt_delivery_v2_json;
use codex_hepta_wire::encode_prompt_delivery_v2_json;

#[test]
fn prompt_wire_boundaries_preserve_hashability_and_roundtrip() {
    for count in [1_u32, 4_095, 4_096, 4_097, 8_192, 8_193] {
        let positions = (0..count)
            .map(|value| value.to_string())
            .collect::<Vec<_>>()
            .join(",");
        let provider = "1".repeat(64);
        let input = format!(
            r#"{{"kind":"prompt_delivery_observation_v2","compilation_id":"compilation-1","provider_request_digest":"{provider}","delivered":true,"rejected_reason":null,"observed_token_positions":[{positions}],"truncation_observed":false,"legacy_v1_digest":null}}"#
        );
        assert!(input.len() < 65_536, "boundary must reach native validation");
        let decoded = decode_prompt_delivery_v2_json(input.as_bytes());
        if count <= 4_096 {
            let value = decoded.expect("accepted boundary");
            let digest = value.semantic_digest().expect("admitted values must hash");
            let encoded = encode_prompt_delivery_v2_json(&value).expect("encode");
            let roundtrip = decode_prompt_delivery_v2_json(&encoded).expect("roundtrip");
            assert_eq!(value, roundtrip);
            assert_eq!(roundtrip.semantic_digest(), Ok(digest));
        } else {
            assert!(decoded.is_err(), "{count} must reject before publication");
        }
    }
}
