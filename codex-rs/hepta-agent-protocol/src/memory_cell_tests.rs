use super::*;

#[test]
fn native_memory_query_rejects_prompt_and_backend_fields() {
    let request = MemoryCellReadIngress {
        invocation_id: "query:one".to_string(),
        role: MemoryCellRole::Procedural,
        entity: "case".to_string(),
        relation: "repair".to_string(),
        deadline_unix_ms: 100,
    };
    let value = serde_json::to_value(&request).unwrap();
    assert!(serde_json::from_value::<MemoryCellReadIngress>(value.clone()).unwrap() == request);
    for key in [
        "prompt",
        "source_claim",
        "checkpoint",
        "pins",
        "control",
        "expected_answer",
    ] {
        let mut forged = value.clone();
        forged[key] = serde_json::json!("caller supplied authority");
        assert!(serde_json::from_value::<MemoryCellReadIngress>(forged).is_err());
    }
}
