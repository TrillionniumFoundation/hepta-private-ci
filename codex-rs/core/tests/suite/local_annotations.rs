//! Distinguish locally persisted annotations from the actual mock wire body.
//!
//! The production provider allowlist intentionally strips internal metadata for
//! localhost. These helpers never put annotations back into a captured request.

use anyhow::Context;
use anyhow::Result;
use codex_core::CodexThread;
use codex_history::RolloutItem;
use core_test_support::responses::ResponsesRequest;
use serde_json::Value;

const METADATA: &str = "internal_chat_message_metadata_passthrough";

pub(super) fn assert_wire_has_no_internal_metadata(request: &ResponsesRequest) {
    assert!(
        request
            .input()
            .iter()
            .all(|item| item.get(METADATA).is_none()),
        "a localhost mock must not receive internal message metadata"
    );
}

/// Match explicitly selected wire items to an ordered subsequence of persisted response
/// items, ignoring only top-level response IDs and internal metadata. Content,
/// roles, tool names, arguments, call IDs, media and relative order must match.
/// Request-only transformations must be excluded explicitly by the caller and
/// keep their own wire assertions; every selected item must have an exact match.
pub(super) async fn persisted_request_items(
    thread: &CodexThread,
    request: &ResponsesRequest,
    select_input: impl Fn(&Value) -> bool,
) -> Result<Vec<Value>> {
    assert_wire_has_no_internal_metadata(request);
    let history = thread.load_history(/*include_archived*/ false).await?;
    let stored = history
        .items
        .into_iter()
        .filter_map(|item| match item {
            RolloutItem::ResponseItem(envelope) => Some(serde_json::to_value(envelope.item)),
            _ => None,
        })
        .collect::<serde_json::Result<Vec<_>>>()?;
    let mut cursor = 0;
    let mut matched = Vec::new();
    for (wire_index, wire) in request.input().into_iter().enumerate() {
        if !select_input(&wire) {
            continue;
        }
        let normalized = without_id_or_metadata(wire);
        let offset = stored[cursor..].iter().position(|item| {
            without_id_or_metadata(item.clone()) == normalized
        }).with_context(|| format!(
            "wire input {wire_index} has no exact ordered persisted match after history item {cursor}"
        ))?;
        cursor += offset + 1;
        matched.push(stored[cursor - 1].clone());
    }
    Ok(matched)
}

pub(super) fn assert_local_content_kinds(items: &[Value], expected: &[&str]) {
    assert!(
        items.iter().any(|item| {
            item[METADATA]["content_item_kinds"]
                .as_array()
                .is_some_and(|actual| {
                    actual.len() == expected.len()
                        && actual
                            .iter()
                            .zip(expected)
                            .all(|(kind, expected)| kind.as_str() == Some(*expected))
                })
        }),
        "persisted request item should retain local content kinds {expected:?}"
    );
}

fn without_id_or_metadata(mut item: Value) -> Value {
    let object = item
        .as_object_mut()
        .expect("response item must be an object");
    object.remove("id");
    object.remove(METADATA);
    item
}
