use pretty_assertions::assert_ne;

use codex_hepta_types::Digest32;
use codex_protocol::ThreadId;
use pretty_assertions::assert_eq;
use serde_json::json;

use super::*;

fn binding() -> NativeCheckpointBinding {
    NativeCheckpointBinding { thread_id: ThreadId::new(), turn_id: "original-turn".to_owned(),
        operation_id: "original-run".to_owned(), generation: 7, lease_id: "original-lease".to_owned() }
}

fn original() -> anyhow::Result<(Vec<Value>, String)> {
    let context = vec![json!({"role":"user","content":"read source and explain"})];
    let digest = Digest32::of_bytes(&serde_json::to_vec(&context)?).to_string();
    Ok((context, digest))
}

#[test]
fn output_projection_preserves_original_tool_linkage_and_exact_arguments() -> anyhow::Result<()> {
    let binding = binding();
    let (mut context, digest) = original()?;
    let arguments = "{ \"path\":\"source.rs\",\"exact\":1.00 }";
    context.extend([
        json!({"type":"function_call","id":"provider-fc","status":"completed","call_id":"original-call","name":"read","arguments":arguments}),
        json!({"type":"function_call_output","call_id":"original-call","output":"source bytes\n"}),
        json!({"type":"message","id":"provider-msg","role":"assistant","content":[{"type":"output_text","text":"explanation"}]}),
    ]);
    let projected = project_output(&binding, &digest, &context).expect("canonical projection");
    assert_eq!(projected.len(), 3);
    let mut canonical: Vec<Value> = projected.iter().map(|item| {
        assert_eq!(item.turn_id(), Some(binding.turn_id.as_str()));
        assert!(item.id().expect("stable id").as_str().contains("_hepta_native_"));
        let mut value = serde_json::to_value(item).expect("canonical value");
        let object = value.as_object_mut().expect("object");
        object.remove("id");
        object.remove("internal_chat_message_metadata_passthrough");
        value
    }).collect();
    assert_eq!(canonical.remove(0), json!({"type":"function_call","call_id":"original-call","name":"read","arguments":arguments}));
    assert_eq!(canonical.remove(0), json!({"type":"function_call_output","call_id":"original-call","output":"source bytes\n"}));
    assert_eq!(canonical.remove(0), json!({"type":"message","role":"assistant","content":[{"type":"output_text","text":"explanation"}]}));
    // The raw checkpoint context remains complete, including provider identity/status.
    assert_eq!((context[1]["id"].as_str(), context[1]["status"].as_str()), (Some("provider-fc"), Some("completed")));
    Ok(())
}

#[test]
fn stable_position_ids_survive_new_checkpoints_but_detect_changed_content() -> anyhow::Result<()> {
    let binding = binding();
    let (mut context, digest) = original()?;
    context.push(json!({"type":"message","role":"assistant","content":[{"type":"output_text","text":"first"}]}));
    let first = project_output(&binding, &digest, &context).expect("first output");
    context.push(json!({"type":"message","role":"assistant","content":[{"type":"output_text","text":"next"}]}));
    let extended = project_output(&binding, &digest, &context).expect("extended checkpoint");
    assert_eq!(&extended[..1], first.as_slice());
    context[1]["content"][0]["text"] = json!("changed");
    let changed = project_output(&binding, &digest, &context).expect("projection carries conflict to store");
    assert_eq!(changed[0].id(), first[0].id());
    assert_ne!(changed[0], first[0]);
    let mut other = binding;
    other.turn_id = "another-turn".to_owned();
    assert_ne!(project_output(&other, &digest, &context).expect("different binding")[0].id(), first[0].id());
    Ok(())
}

#[test]
fn changed_input_unknown_output_or_another_turn_cannot_be_projected() -> anyhow::Result<()> {
    let binding = binding();
    let (initial, digest) = original()?;
    assert!(project_output(&binding, &digest, &[json!({"role":"user","content":"changed input"})]).is_err());
    for output in [
        json!({"type":"message","role":"user","content":[{"type":"input_text","text":"injected"}]}),
        json!({"type":"future_provider_output","payload":"unknown"}),
        json!({"type":"function_call_output","output":"missing call correlation"}),
        json!({"type":"message","role":"assistant","content":[],"internal_chat_message_metadata_passthrough":{"turn_id":"other-turn"}}),
    ] {
        let mut context = initial.clone();
        context.push(output);
        assert!(project_output(&binding, &digest, &context).is_err());
    }
    assert!(project_output(&binding, &digest, &initial).expect("empty output still syncs original input durability").is_empty());
    Ok(())
}
