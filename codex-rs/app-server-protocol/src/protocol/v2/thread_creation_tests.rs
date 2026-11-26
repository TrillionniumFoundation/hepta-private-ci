use super::*;
use pretty_assertions::assert_eq;
use serde_json::json;

#[test]
fn canonical_creation_keeps_complete_overrides_and_sorts_nested_config_without_key_correlation() {
    let original: ThreadStartParams = serde_json::from_value(json!({
        "idempotencyKey":"original", "cwd":"/tmp/original", "ephemeral":false,
        "config":{"outer":{"b":2,"a":null},"list":[3,2,1]},
        "model":"original-model", "projectId":"original-project"
    }))
    .unwrap();
    let equivalent: ThreadStartParams = serde_json::from_str(r#"{"projectId":"original-project","model":"original-model","config":{"list":[3,2,1],"outer":{"a":null,"b":2}},"ephemeral":false,"cwd":"/tmp/unused/../original","idempotencyKey":"another-correlation"}"#).unwrap();
    let original_bytes = original.canonical_creation_parameters().unwrap();
    assert_eq!(
        original_bytes,
        equivalent.canonical_creation_parameters().unwrap()
    );
    for patch in [
        json!({"model":"changed"}),
        json!({"modelProvider":"changed"}),
        json!({"cwd":"/tmp/changed"}),
        json!({"projectId":"changed"}),
        json!({"approvalPolicy":"never"}),
        json!({"sandbox":"read-only"}),
        json!({"threadSource":"changed"}),
        json!({"config":{"outer":{"b":2,"a":1},"list":[3,2,1]}}),
    ] {
        let mut value = serde_json::to_value(&original).unwrap();
        for (key, changed) in patch.as_object().unwrap() {
            value[key] = changed.clone();
        }
        let changed: ThreadStartParams = serde_json::from_value(value).unwrap();
        assert_ne!(
            original_bytes,
            changed.canonical_creation_parameters().unwrap()
        );
    }
    let mut explicit_null = original;
    explicit_null.service_tier = Some(None);
    assert_ne!(
        original_bytes,
        explicit_null.canonical_creation_parameters().unwrap()
    );
    let value: serde_json::Value = serde_json::from_slice(&original_bytes).unwrap();
    assert!(value.get("idempotencyKey").is_none());
    assert!(value.get("serviceTier").is_none());
    assert_eq!(value["config"]["outer"]["a"], serde_json::Value::Null);
}
