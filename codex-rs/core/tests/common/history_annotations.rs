//! Checks locally retained annotations independently of provider wire policy.

use crate::responses::ResponsesRequest;
use codex_core::CodexThread;
use codex_thread_store::ThreadStoreError;
use serde_json::Value;

/// Reads the durable response items without provider-specific serialization.
pub async fn response_items(thread: &CodexThread) -> Vec<Value> {
    thread
        .flush_rollout()
        .await
        .expect("flush annotated history");
    let items: Vec<Value> = match thread.load_history(/*include_archived*/ true).await {
        Ok(history) => history
            .items
            .iter()
            .map(|item| serde_json::to_value(item).expect("serialize durable history item"))
            .collect(),
        Err(ThreadStoreError::Unsupported {
            operation: "paginated_threads",
        }) => {
            // The legacy store API does not expose paginated history. Read the
            // flushed canonical rollout, as the world-state fixture does.
            let path = thread.rollout_path().expect("paginated thread rollout");
            tokio::fs::read_to_string(path)
                .await
                .expect("read paginated annotated rollout")
                .lines()
                .map(|line| serde_json::from_str(line).expect("parse durable rollout item"))
                .collect()
        }
        Err(error) => panic!("load annotated history: {error}"),
    };
    items
        .iter()
        .filter(|item| item["type"] == "response_item")
        .map(|item| item["payload"].clone())
        .collect()
}

/// Finds a persisted tool result by its model-assigned call ID.
pub fn tool_call_output<'a>(items: &'a [Value], call_id: &str) -> &'a Value {
    items
        .iter()
        .find(|item| {
            matches!(
                item["type"].as_str(),
                Some("function_call_output" | "custom_tool_call_output")
            ) && item["call_id"] == call_id
        })
        .expect("durable history should contain the tool call output")
}

pub fn has_content_kinds(items: &[Value], kinds: &[&str]) -> bool {
    items.iter().any(|item| {
        item["internal_chat_message_metadata_passthrough"]["content_item_kinds"]
            .as_array()
            .is_some_and(|actual| {
                actual.len() == kinds.len()
                    && actual
                        .iter()
                        .zip(kinds)
                        .all(|(actual, expected)| actual.as_str() == Some(*expected))
            })
    })
}

/// Mock servers are custom endpoints and must not receive private annotations.
pub fn assert_metadata_is_private(request: &ResponsesRequest) {
    assert!(request.input().iter().all(|item| {
        item.get("internal_chat_message_metadata_passthrough")
            .is_none()
    }));
}
