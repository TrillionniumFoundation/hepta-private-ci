use super::*;
use serde_json::json;

fn item(value: Value) -> Result<ResponseItem> {
    serde_json::from_value(value).map_err(|_| Error::Contract("provider evidence fixture"))
}

#[test]
fn plain_reasoning_text_and_empty_presence_round_trip_in_evidence() -> Result<()> {
    for content in [
        json!([{ "type":"text", "text":"original provider item content" }]),
        json!([]),
        Value::Null,
    ] {
        let original = item(json!({
            "type":"reasoning", "id":"reasoning:original", "summary":[],
            "content":content, "encrypted_content":"opaque-original-continuation",
        }))?;
        let evidence = response_item_evidence(&original)?;
        assert_eq!(evidence["content"], content);
        let restored = item(evidence)?;
        assert_eq!(restored, original);
    }
    Ok(())
}

#[test]
fn supported_item_ids_phases_encrypted_content_and_metadata_are_retained() -> Result<()> {
    let originals = vec![
        item(
            json!({"type":"message", "id":"message:original", "role":"assistant",
            "phase":"final_answer", "content":[{"type":"output_text","text":"answer"}],
            "internal_chat_message_metadata_passthrough":{"turn_id":"turn:original","create_time":1.25}}),
        )?,
        item(
            json!({"type":"function_call", "id":"function:original", "call_id":"call:original",
            "name":"owned.read", "arguments":"{\"path\":\"original\"}"}),
        )?,
        item(
            json!({"type":"reasoning", "id":"reasoning:original", "summary":[{"type":"summary_text","text":"summary"}],
            "content":[{"type":"reasoning_text","text":"provider text"}], "encrypted_content":"opaque-reasoning"}),
        )?,
        item(
            json!({"type":"compaction", "id":"compaction:original", "encrypted_content":"opaque-compaction",
            "internal_chat_message_metadata_passthrough":{"turn_id":"turn:original"}}),
        )?,
    ];
    let evidence = response_items_evidence(&originals)?;
    let restored: Vec<ResponseItem> = serde_json::from_value(evidence.clone())
        .map_err(|_| Error::Contract("provider evidence array round trip"))?;
    assert_eq!(restored, originals);
    assert_eq!(evidence[0]["id"], "message:original");
    assert_eq!(evidence[0]["phase"], "final_answer");
    assert_eq!(
        evidence[0]["internal_chat_message_metadata_passthrough"]["create_time"],
        1.25
    );
    assert_eq!(evidence[1]["call_id"], "call:original");
    assert_eq!(evidence[2]["encrypted_content"], "opaque-reasoning");
    assert_eq!(evidence[3]["encrypted_content"], "opaque-compaction");
    Ok(())
}

#[test]
fn evidence_preserves_plain_text_without_changing_the_existing_request_serializer() -> Result<()> {
    let original = item(
        json!({"type":"reasoning", "id":"reasoning:original", "summary":[],
        "content":[{"type":"text","text":"provider-exposed content"}], "encrypted_content":"opaque"}),
    )?;
    let before = serde_json::to_value(&original).map_err(|_| Error::Contract("request fixture"))?;
    assert!(before.get("content").is_none());
    let evidence = response_item_evidence(&original)?;
    assert_eq!(evidence["content"][0]["text"], "provider-exposed content");
    let after = serde_json::to_value(&original).map_err(|_| Error::Contract("request fixture"))?;
    assert_eq!(before, after);
    Ok(())
}
