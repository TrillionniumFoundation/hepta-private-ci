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
    let expected = request
        .input()
        .into_iter()
        .enumerate()
        .filter(|(_, item)| select_input(item))
        .collect();
    persisted_items_matching_expected(thread, expected).await
}

/// Match every wire item, in order, to the host's complete active context. History
/// rewrites can change an existing item without appending its rewritten contents
/// to the rollout, so rollback fixtures must observe the production context.
pub(super) async fn active_request_items(
    thread: &CodexThread,
    request: &ResponsesRequest,
) -> Result<Vec<Value>> {
    assert_wire_has_no_internal_metadata(request);
    let expected = request.input().into_iter().enumerate().collect();
    let stored = codex_core::test_support::active_context_items(thread)
        .await
        .into_iter()
        .map(serde_json::to_value)
        .collect::<serde_json::Result<Vec<_>>>()?;
    items_matching_expected(&stored, expected, "active")
}

/// These image fixtures explicitly prepare Original-detail images, whereas Lite
/// omits detail on the wire. Build the expected stored values with that one known
/// difference, then require the same exact matcher as ordinary requests. This
/// never changes the captured request or accepts arbitrary media differences.
pub(super) async fn persisted_lite_image_items_with_original_detail(
    thread: &CodexThread,
    request: &ResponsesRequest,
    select_input: impl Fn(&Value) -> bool,
) -> Result<Vec<Value>> {
    assert_wire_has_no_internal_metadata(request);
    let mut expected = Vec::new();
    let mut image_count = 0;
    for (wire_index, mut item) in request.input().into_iter().enumerate() {
        if !select_input(&item) {
            continue;
        }
        for content in item["content"]
            .as_array_mut()
            .context("selected image/notice message should contain content")?
        {
            if content["type"] == "input_image" {
                assert!(
                    content.get("detail").is_none(),
                    "Lite must omit image detail"
                );
                content["detail"] = Value::String("original".to_string());
                image_count += 1;
            }
        }
        expected.push((wire_index, item));
    }
    assert!(
        image_count > 0,
        "image fixture must exercise the Lite projection"
    );
    persisted_items_matching_expected(thread, expected).await
}

async fn persisted_items_matching_expected(
    thread: &CodexThread,
    expected: Vec<(usize, Value)>,
) -> Result<Vec<Value>> {
    let history = thread.load_history(/*include_archived*/ false).await?;
    let stored = history
        .items
        .into_iter()
        .filter_map(|item| match item {
            RolloutItem::ResponseItem(envelope) => Some(serde_json::to_value(envelope.item)),
            _ => None,
        })
        .collect::<serde_json::Result<Vec<_>>>()?;
    items_matching_expected(&stored, expected, "persisted")
}

fn items_matching_expected(
    stored: &[Value],
    expected: Vec<(usize, Value)>,
    source: &str,
) -> Result<Vec<Value>> {
    let mut cursor = 0;
    let mut matched = Vec::new();
    for (wire_index, expected_item) in expected {
        let normalized = without_id_or_metadata(expected_item);
        let offset = stored[cursor..].iter().position(|item| {
            without_id_or_metadata(item.clone()) == normalized
        }).with_context(|| {
            let expected = normalized.to_string();
            let closest = stored[cursor..].iter().enumerate().map(|(offset, item)| {
                let actual = without_id_or_metadata(item.clone()).to_string();
                let prefix = expected.chars().zip(actual.chars()).take_while(|(left, right)| left == right).count();
                (cursor + offset, prefix, actual)
            }).max_by_key(|(_, prefix, _)| *prefix);
            let detail = closest.map(|(index, prefix, actual)| {
                let start = prefix.saturating_sub(40);
                let expected = expected.chars().skip(start).take(240).collect::<String>();
                let actual = actual.chars().skip(start).take(240).collect::<String>();
                format!("; closest history item {index} differs at character {prefix}: expected={expected:?}, stored={actual:?}")
            }).unwrap_or_else(|| format!("; no remaining {source} response items"));
            format!("wire input {wire_index} has no exact ordered {source} match after history item {cursor}{detail}")
        })?;
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
