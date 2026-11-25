use super::*;

#[test]
fn history_query_preserves_historical_body_and_current_outer_generation() {
    let request = AgentdRequest {
        schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
        request_id: 19,
        spawn_generation: 7,
        method: AgentdMethod::ObjectiveAdmission {
            query: ObjectiveAdmissionQuery {
                request: ingress(),
                anchor: Some(ObjectiveJournalAnchor {
                    sequence: 2,
                    chain_digest: digest('a'),
                }),
            },
        },
    };
    let bytes = serde_json::to_vec(&request).expect("encode");
    assert!(bytes.len() as u64 <= MAX_CONTROL_FRAME_BYTES);
    assert_eq!(
        serde_json::from_slice::<AgentdRequest>(&bytes).expect("decode"),
        request
    );
    let mut value = serde_json::to_value(&request).expect("value");
    value["method"]["query"]["effect_authority"] = serde_json::json!(true);
    assert!(serde_json::from_value::<AgentdRequest>(value).is_err());
}

#[test]
fn history_unknown_is_nested_and_cannot_decode_as_non_admission() {
    let payload = AgentdPayload::ObjectiveAdmission {
        outcome: ObjectiveAdmissionOutcome::Unknown {
            reason: ObjectiveAdmissionUnknownReason::AnchorMissing,
        },
    };
    let mut value = serde_json::to_value(&payload).expect("value");
    assert_eq!(
        serde_json::from_value::<AgentdPayload>(value.clone()).expect("decode"),
        payload
    );
    value["outcome"]["type"] = serde_json::json!("not_admitted");
    assert!(serde_json::from_value::<AgentdPayload>(value).is_err());
}
