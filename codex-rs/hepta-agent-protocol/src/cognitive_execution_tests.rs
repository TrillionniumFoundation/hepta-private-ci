use super::*;

#[test]
fn execution_envelope_does_not_extend_the_strict_snapshot_or_accept_authority() {
    let snapshot: CognitiveContextSnapshot = serde_json::from_value(serde_json::json!({
        "snapshot_digest":"unchanged-snapshot", "read_digest":"unchanged-read",
        "omitted_records":0, "items":[], "plan":null,
    }))
    .unwrap();
    let original = serde_json::to_vec(&snapshot).unwrap();
    let envelope = CognitiveContextExecutionV1 {
        schema_version: 1,
        snapshot,
        neural: None,
    };
    let wire = serde_json::to_value(&envelope).unwrap();
    let decoded: CognitiveContextExecutionV1 = serde_json::from_value(wire.clone()).unwrap();
    assert_eq!(decoded, envelope);
    assert_eq!(serde_json::to_vec(&decoded.snapshot).unwrap(), original);
    let payload = crate::AgentdPayload::CognitiveContextWithExecutionV1(Box::new(envelope));
    let mut payload_wire = wire.clone();
    payload_wire["type"] = serde_json::json!("cognitive_context_with_execution_v1");
    assert_eq!(serde_json::to_value(&payload).unwrap(), payload_wire);
    assert_eq!(
        serde_json::from_value::<crate::AgentdPayload>(payload_wire).unwrap(),
        payload
    );
    assert!(serde_json::from_value::<CognitiveContextSnapshot>(wire.clone()).is_err());
    let mut forged = wire;
    forged["execution_authority"] = serde_json::json!(true);
    assert!(serde_json::from_value::<CognitiveContextExecutionV1>(forged).is_err());
}
