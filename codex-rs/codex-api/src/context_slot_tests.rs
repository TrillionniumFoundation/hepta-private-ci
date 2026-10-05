use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

use super::verify_responses_developer_context;

const MODEL: &str = "qualified-model";
const CONTEXT: &str = "{\"schema\":\"hepta.context-bundle.v2\",\"content\":\"approved\"}";

fn request(context: &str) -> Value {
    json!({
        "model": MODEL,
        "instructions": "provider-owned baseline",
        "input": [{
            "type": "message",
            "role": "developer",
            "content": [{"type": "input_text", "text": context}]
        }]
    })
}

fn verify(value: &Value, context: &str) -> Result<(), &'static str> {
    let bytes = serde_json::to_vec(value).expect("fixture JSON");
    verify_responses_developer_context(&bytes, MODEL, context)
}

#[test]
fn accepts_only_complete_developer_input_text() {
    assert_eq!(verify(&request(CONTEXT), CONTEXT), Ok(()));
}

#[test]
fn metadata_only_context_is_not_model_delivery() {
    let value = json!({"model": MODEL, "input": [], "metadata": {"note": CONTEXT}});
    assert_eq!(verify(&value, CONTEXT), Err("context_slot_placement"));
}

#[test]
fn system_user_assistant_and_tool_roles_are_not_developer_slots() {
    for role in ["system", "user", "assistant", "tool"] {
        let mut value = request(CONTEXT);
        value["input"][0]["role"] = json!(role);
        assert_eq!(verify(&value, CONTEXT), Err("context_slot_placement"));
    }
}

#[test]
fn instructions_tool_schema_and_wrong_content_type_are_rejected() {
    let instructions = json!({"model": MODEL, "input": [], "instructions": CONTEXT});
    assert_eq!(
        verify(&instructions, CONTEXT),
        Err("context_slot_placement")
    );
    let schema = json!({"model": MODEL, "input": [], "tools": [{"description": CONTEXT}]});
    assert_eq!(verify(&schema, CONTEXT), Err("context_slot_placement"));
    let mut value = request(CONTEXT);
    value["input"][0]["content"][0]["type"] = json!("output_text");
    assert_eq!(verify(&value, CONTEXT), Err("context_slot_placement"));
}

#[test]
fn concatenated_unapproved_prefix_and_suffix_are_rejected() {
    for text in [
        format!("unapproved {CONTEXT}"),
        format!("{CONTEXT} unapproved"),
    ] {
        assert_eq!(
            verify(&request(&text), CONTEXT),
            Err("context_slot_placement")
        );
    }
}

#[test]
fn duplicates_in_other_values_and_object_keys_are_rejected() {
    let mut value = request(CONTEXT);
    value["metadata"] = json!({"note": CONTEXT});
    assert_eq!(verify(&value, CONTEXT), Err("context_slot_occurrence"));
    let mut value = request(CONTEXT);
    value
        .as_object_mut()
        .expect("object")
        .insert(CONTEXT.to_owned(), Value::Null);
    assert_eq!(verify(&value, CONTEXT), Err("context_slot_occurrence"));
}

#[test]
fn duplicate_keys_are_rejected_including_escaped_aliases() {
    let context = "approved-context";
    for raw in [
        r#"{"model":"qualified-model","model":"qualified-model","input":[]}"#,
        r#"{"model":"qualified-model","input":[],"metadata":{"x":1,"x":2}}"#,
        r#"{"model":"qualified-model","input":[],"metadata":{"x":1,"\u0078":2}}"#,
    ] {
        assert_eq!(
            verify_responses_developer_context(raw.as_bytes(), MODEL, context),
            Err("context_slot_json")
        );
    }
}

#[test]
fn model_mismatch_and_trailing_data_fail_closed() {
    let mut value = request(CONTEXT);
    value["model"] = json!("other-model");
    assert_eq!(verify(&value, CONTEXT), Err("context_slot_model"));
    let mut bytes = serde_json::to_vec(&request(CONTEXT)).expect("JSON");
    bytes.extend_from_slice(b" {}");
    assert_eq!(
        verify_responses_developer_context(&bytes, MODEL, CONTEXT),
        Err("context_slot_json")
    );
}

#[test]
fn generated_unicode_and_control_contexts_preserve_exact_slot_identity() {
    for index in 0..256 {
        let context = format!(
            "context-{index}:政策🧪\n\t\u{0001}\\\"{} ",
            "x".repeat(index)
        );
        assert_eq!(verify(&request(&context), &context), Ok(()));
        let mut wrong = request(&context);
        wrong["input"][0]["role"] = json!("user");
        assert_eq!(verify(&wrong, &context), Err("context_slot_placement"));
    }
}

#[test]
fn node_and_recursion_limits_are_not_unbounded_allocations() {
    let mut value = request(CONTEXT);
    value["metadata"] = Value::Array(vec![Value::Null; super::MAX_JSON_NODES]);
    assert_eq!(verify(&value, CONTEXT), Err("context_slot_json"));
    let bytes = format!("{}0{}", "[".repeat(256), "]".repeat(256));
    assert_eq!(
        verify_responses_developer_context(bytes.as_bytes(), MODEL, CONTEXT),
        Err("context_slot_json")
    );
}

#[test]
fn malformed_content_errors_never_echo_payload() {
    let secret = "PRIVATE-CONTEXT-DO-NOT-LOG";
    let error = verify_responses_developer_context(secret.as_bytes(), MODEL, secret)
        .expect_err("invalid JSON");
    assert_eq!(error, "context_slot_json");
    assert!(!format!("{error:?}").contains(secret));
}
