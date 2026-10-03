#![cfg(feature = "fixed-eval-host")]
use codex_hepta_agent_components::frozen_generator_wire::*;
use serde_json::json;

#[test]
fn preserves_full_payload_at_the_exact_bound_and_refuses_one_extra_byte() {
    let payload = vec![0xab; MAX_FROZEN_GENERATOR_PAYLOAD_BYTES_V1];
    let bytes = encode_frozen_generator_request_v1(
        &FrozenGeneratorRequestV1::from_payload(&payload).unwrap(),
    )
    .unwrap();
    assert_eq!(
        decode_frozen_generator_request_v1(&bytes)
            .unwrap()
            .payload()
            .unwrap(),
        payload
    );
    assert!(
        FrozenGeneratorRequestV1::from_payload(&vec![0; MAX_FROZEN_GENERATOR_PAYLOAD_BYTES_V1 + 1])
            .is_err()
    );
}

#[test]
fn rejects_noncanonical_hex_schema_duplicates_and_extra_authority_fields() {
    for hex in ["", "a", "AA", "aA", "0g", "é"] {
        let bytes =
            serde_json::to_vec(&json!({"schema_version":1,"frozen_payload_hex":hex})).unwrap();
        assert!(decode_frozen_generator_request_v1(&bytes).is_err());
    }
    for json in [
        r#"{"schema_version":2,"frozen_payload_hex":"ab"}"#,
        r#"{"schema_version":1,"frozen_payload_hex":"ab","principal_id":"generator"}"#,
        r#"{"schema_version":1,"schema_version":1,"frozen_payload_hex":"ab"}"#,
    ] {
        assert!(decode_frozen_generator_request_v1(json.as_bytes()).is_err());
    }
    assert!(
        decode_frozen_generator_request_v1(&vec![b' '; MAX_FROZEN_GENERATOR_REQUEST_BYTES_V1 + 1])
            .is_err()
    );
}

fn evidence_json() -> serde_json::Value {
    json!({
        "evidence_id":"original-evidence","principal_id":"original-generator",
        "role":"generator","trust_digest":"01".repeat(32),
        "scope_digest":"02".repeat(32),"objective_digest":"03".repeat(32),
        "authority_epoch":1,"issued_at":1,"expires_at":2,
        "payload_digest":"04".repeat(32),"signature_hex":"05".repeat(64)
    })
}

#[test]
fn reuses_original_evidence_wire_without_an_authority_wrapper() {
    let expected = evidence_json();
    let bytes = serde_json::to_vec(&expected).unwrap();
    let decoded = decode_frozen_generator_response_v1(&bytes).unwrap();
    let FrozenGeneratorResponseV1::Granted(evidence) = &decoded else {
        panic!("expected original evidence");
    };
    assert_eq!(
        evidence.native().unwrap().principal_id.as_str(),
        "original-generator"
    );
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(
            &encode_frozen_generator_response_v1(&decoded).unwrap()
        )
        .unwrap(),
        expected
    );
}

#[test]
fn refuses_unknown_error_codes_mixed_responses_and_oversized_evidence() {
    for bytes in [
        br#"{"error":"invented"}"#.as_slice(),
        br#"{"error":"pending","receipt":"fake"}"#.as_slice(),
        br#"{"error":"pending","principal_id":"root"}"#.as_slice(),
    ] {
        assert!(decode_frozen_generator_response_v1(bytes).is_err());
    }
    let mut mixed = evidence_json();
    mixed["error"] = json!("pending");
    assert!(decode_frozen_generator_response_v1(&serde_json::to_vec(&mixed).unwrap()).is_err());
    let mut oversized = evidence_json();
    oversized["evidence_id"] = json!("a".repeat(MAX_FROZEN_GENERATOR_RESPONSE_BYTES_V1));
    let decoded: FrozenGeneratorResponseV1 = serde_json::from_value(oversized.clone()).unwrap();
    assert!(encode_frozen_generator_response_v1(&decoded).is_err());
    assert!(decode_frozen_generator_response_v1(&serde_json::to_vec(&oversized).unwrap()).is_err());
    let response = decode_frozen_generator_response_v1(br#"{"error":"pending"}"#).unwrap();
    let FrozenGeneratorResponseV1::Refused(error) = response else {
        panic!("expected finite refusal");
    };
    assert_eq!(error.error, FrozenGeneratorErrorCodeV1::Pending);
}
