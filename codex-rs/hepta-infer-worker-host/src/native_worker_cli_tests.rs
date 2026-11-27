use super::parse_intelligence_snapshot;

#[test]
fn snapshot_input_roundtrips_and_never_fills_missing_identity() {
    let snapshot = codex_hepta_agentd::AgentRunSnapshot {
        run_id: "intelligence.cli.run".to_string(),
        request_digest: "1".repeat(64),
        objective_digest: "2".repeat(64),
        body_digest: "3".repeat(64),
        artifact_set_digest: "4".repeat(64),
        authority_epoch: 9,
        generation: 1,
        fence_digest: "5".repeat(64),
        deadline_ms: 10_000,
    };
    let value = serde_json::to_value(&snapshot).unwrap();
    assert_eq!(
        parse_intelligence_snapshot(&value.to_string()).unwrap(),
        snapshot
    );
    for field in [
        "run_id",
        "request_digest",
        "objective_digest",
        "body_digest",
        "artifact_set_digest",
        "authority_epoch",
        "generation",
        "fence_digest",
        "deadline_ms",
    ] {
        let mut incomplete = value.clone();
        incomplete.as_object_mut().unwrap().remove(field);
        assert!(parse_intelligence_snapshot(&incomplete.to_string()).is_err());
    }
    let mut unknown = value;
    unknown["current_snapshot_fallback"] = serde_json::json!(true);
    assert!(parse_intelligence_snapshot(&unknown.to_string()).is_err());
    assert!(parse_intelligence_snapshot(&" ".repeat(16 * 1024 + 1)).is_err());
}
