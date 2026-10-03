use super::*;
use pretty_assertions::assert_eq;
#[test]
fn original_general_outer_shape_and_whole_serving_response_are_preserved() {
    let legacy = serde_json::json!({"schema_version":2,"request_id":17,"agent_id":"12345678-1234-4234-8234-123456789abc","spawn_generation":3,"current_generation":4,"payload":{"type":"health","original":"preserved"}});
    let decoded: OriginalAgentdResponseV1<serde_json::Value> =
        serde_json::from_value(legacy.clone()).expect("old whole envelope");
    assert_eq!(serde_json::to_value(decoded).expect("same codec"), legacy);
    let response = OriginalAgentdResponseV1 {
        schema_version: 2,
        request_id: 7,
        agent_id: AgentId::parse("12345678-1234-4234-8234-123456789abc").expect("id"),
        spawn_generation: 1,
        current_generation: 2,
        payload: ParameterServingScopePayloadV1::ParameterServingScopeV1(ParameterServingScopeV1 {
            round_hex: "ab12".into(),
            neuron_generation: 2,
            configuration_digest: "a".repeat(64),
            body_bundle_digest: "b".repeat(64),
            scope_digest: "c".repeat(64),
            objective_digest: "d".repeat(64),
            goal_ordinal: Some(3),
        }),
    };
    let mut bytes = b" \n".to_vec();
    bytes.extend_from_slice(&serde_json::to_vec(&response).expect("whole"));
    bytes.extend_from_slice(b" \n");
    assert_eq!(
        decode_original_parameter_serving_scope_response_v1(&bytes)
            .expect("complete whitespace retained at source"),
        response
    );
    let mut other = response.clone();
    other.payload =
        ParameterServingScopePayloadV1::ParameterServingScopeV1(ParameterServingScopeV1 {
            goal_ordinal: None,
            ..match response.payload {
                ParameterServingScopePayloadV1::ParameterServingScopeV1(p) => p,
            }
        });
    assert_eq!(
        decode_original_parameter_serving_scope_response_v1(
            &serde_json::to_vec(&other).expect("whole")
        )
        .expect("actual fixed scope"),
        other
    );
}
#[test]
fn other_purpose_unknown_fields_partial_or_overcap_response_cannot_become_serving_fact() {
    let old = serde_json::json!({"schema_version":2,"request_id":17,"agent_id":"12345678-1234-4234-8234-123456789abc","spawn_generation":3,"current_generation":4,"payload":{"type":"health"}});
    assert!(
        decode_original_parameter_serving_scope_response_v1(
            &serde_json::to_vec(&old).expect("whole")
        )
        .is_err()
    );
    assert!(decode_original_parameter_serving_scope_response_v1(b"{").is_err());
    assert!(
        decode_original_parameter_serving_scope_response_v1(&vec![
            b' ';
            MAX_ORIGINAL_PARAMETER_SERVING_RESPONSE_BYTES_V1
                + 1
        ])
        .is_err()
    );
}
