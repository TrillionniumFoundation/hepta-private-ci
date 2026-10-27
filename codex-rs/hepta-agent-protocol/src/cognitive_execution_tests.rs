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
    assert!(serde_json::from_value::<CognitiveContextSnapshot>(wire.clone()).is_err());
    let mut forged = wire;
    forged["execution_authority"] = serde_json::json!(true);
    assert!(serde_json::from_value::<CognitiveContextExecutionV1>(forged).is_err());
}
