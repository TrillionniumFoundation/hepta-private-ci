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

#[test]
fn observation_has_a_separate_finite_purpose_without_changing_issue_bytes() {
    let payload = b"original-frozen-facts";
    let issue = encode_frozen_generator_request_v1(
        &FrozenGeneratorRequestV1::from_payload(payload).unwrap(),
    )
    .unwrap();
    let observation = encode_frozen_generator_observation_request_v2(
        &FrozenGeneratorObservationRequestV2::from_payload(payload).unwrap(),
    )
    .unwrap();
    assert!(decode_frozen_generator_request_v1(&observation).is_err());
    assert!(decode_frozen_generator_observation_request_v2(&issue).is_err());
    for (bytes, expected_observation) in [(&issue, false), (&observation, true)] {
        let decoded = match decode_frozen_generator_operation_v1(bytes).unwrap() {
            FrozenGeneratorOperationV1::Issue(request) => {
                assert!(!expected_observation);
                request.payload().unwrap()
            }
            FrozenGeneratorOperationV1::Observe(request) => {
                assert!(expected_observation);
                request.payload().unwrap()
            }
            FrozenGeneratorOperationV1::ObserveModelFailure(_) => panic!("legacy purpose changed"),
        };
        assert_eq!(decoded, payload);
    }
    for bytes in [
        br#"{"schema_version":2,"frozen_payload_hex":"AA"}"#.as_slice(),
        br#"{"schema_version":2,"frozen_payload_hex":"ab","dispatch":true}"#.as_slice(),
        br#"{"schema_version":2,"schema_version":1,"frozen_payload_hex":"ab"}"#.as_slice(),
        br#"{"schema_version":3,"frozen_payload_hex":"ab"}"#.as_slice(),
    ] {
        assert!(decode_frozen_generator_operation_v1(bytes).is_err());
    }
}

#[test]
fn model_failure_observation_has_exact_original_request_and_cannot_be_used_for_issuance() {
    use codex_hepta_infer_core::SelfIterationModelRequestV1;
    use codex_hepta_infer_core::SelfIterationModelRoleV1;
    use codex_hepta_types::Digest32;
    use codex_hepta_types::StableId;
    let request = SelfIterationModelRequestV1 {
        request_id: StableId::new("original.request").unwrap(),
        role: SelfIterationModelRoleV1::Observer,
        envelope_digest: Digest32::of_bytes(b"original execution"),
        candidate_digest: Some(Digest32::of_bytes(b"original frozen candidate")),
        prompt: "  原始\ninput🙂  ".into(),
        deadline_ms: 20000,
        maximum_response_bytes: 8192,
    };
    let bytes = encode_self_iteration_model_failure_observation_request_v1(
        &SelfIterationModelFailureObservationRequestV1::from_request(&request).unwrap(),
    )
    .unwrap();
    match decode_frozen_generator_operation_v1(&bytes).unwrap() {
        FrozenGeneratorOperationV1::ObserveModelFailure(actual) => {
            assert_eq!(actual.request().unwrap(), request)
        }
        _ => panic!("model failure observation purpose changed"),
    }
    assert!(decode_frozen_generator_request_v1(&bytes).is_err());
    assert!(decode_frozen_generator_observation_request_v2(&bytes).is_err());
    for bad in [
        br#"{"schema_version":4,"model_request_hex":"AA"}"#.as_slice(),
        br#"{"schema_version":4,"model_request_hex":"ab","dispatch":true}"#.as_slice(),
        br#"{"schema_version":4,"frozen_payload_hex":"ab"}"#.as_slice(),
    ] {
        assert!(decode_self_iteration_model_failure_observation_request_v1(bad).is_err());
    }
    let refusal =
        SelfIterationModelFailureObservationResponseV1::Refused(FrozenGeneratorFailureV1 {
            error: FrozenGeneratorErrorCodeV1::Pending,
        });
    let bytes = encode_self_iteration_model_failure_observation_response_v1(&refusal).unwrap();
    assert!(matches!(
        decode_self_iteration_model_failure_observation_response_v1(&bytes).unwrap(),
        SelfIterationModelFailureObservationResponseV1::Refused(FrozenGeneratorFailureV1 {
            error: FrozenGeneratorErrorCodeV1::Pending
        })
    ));
    assert_eq!(MAX_FROZEN_GENERATOR_RESPONSE_BYTES_V1, 16 * 1024);
}
