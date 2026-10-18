use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_core::CodexThread;
use codex_history::RolloutItem;
use codex_history::RolloutLine;
use core_test_support::responses::ResponsesRequest;
use serde_json::Value;

/// Reads the exact original rollout named by this thread after its durable terminal.
/// Keep the original JSON payload intact, including warehouse-only fields that
/// the runtime's typed deserializer intentionally does not import.
async fn read_original_records(thread: &CodexThread) -> Result<Vec<(RolloutLine, Value)>> {
    let path = thread
        .rollout_path()
        .context("original rollout path missing")?;
    let contents = tokio::fs::read_to_string(&path).await?;
    ensure!(
        contents.ends_with('\n'),
        "original rollout ends in a partial record"
    );
    let expected_thread = thread.session_configured().thread_id;
    let mut items = Vec::new();
    for (index, text) in contents.lines().enumerate() {
        let typed: RolloutLine = serde_json::from_str(text)
            .with_context(|| format!("original rollout record {index} is invalid"))?;
        if index == 0 {
            let RolloutItem::SessionMeta(meta) = &typed.item else {
                anyhow::bail!("original rollout does not start with SessionMeta");
            };
            ensure!(
                meta.meta.id == expected_thread,
                "original rollout thread identity differs"
            );
        }
        items.push((typed, serde_json::from_str(text)?));
    }
    ensure!(!contents.is_empty(), "original rollout is empty");
    Ok(items)
}

pub(super) async fn read_items(thread: &CodexThread) -> Result<Vec<Value>> {
    read_original_records(thread)
        .await?
        .into_iter()
        .filter_map(|(typed, raw)| {
            matches!(typed.item, RolloutItem::ResponseItem(_)).then(|| {
                raw.get("payload")
                    .context("original response payload missing")
                    .cloned()
            })
        })
        .collect()
}

pub(super) async fn read_replacement_items(thread: &CodexThread) -> Result<Vec<Value>> {
    read_original_records(thread)
        .await?
        .into_iter()
        .rev()
        .find_map(|(typed, raw)| {
            matches!(typed.item, RolloutItem::Compacted(_)).then(|| {
                raw.pointer("/payload/replacement_history")
                    .and_then(Value::as_array)
                    .context("original replacement history missing")
                    .cloned()
            })
        })
        .context("original compaction record missing")?
}

pub(super) fn assert_wire_has_no_local_metadata(input: &[Value]) {
    assert!(
        input.iter().all(|item| {
            item.get("internal_chat_message_metadata_passthrough")
                .is_none()
        }),
        "custom provider wire must omit the whole internal metadata field"
    );
}

pub(super) fn has_content_kinds(items: &[Value], kinds: &[&str]) -> bool {
    let expected = serde_json::json!(kinds);
    items.iter().any(|item| {
        item.pointer("/internal_chat_message_metadata_passthrough/content_item_kinds")
            == Some(&expected)
    })
}

/// Check actual custom-provider wire stripping and independently persisted classification.
/// The captured HTTP request is never rewritten to contain local metadata.
pub(super) async fn assert_content_kinds(
    thread: &CodexThread,
    request: &ResponsesRequest,
    kinds: &[&str],
) -> Result<()> {
    assert_wire_has_no_local_metadata(&request.input());
    let durable = read_items(thread).await?;
    ensure!(
        has_content_kinds(&durable, kinds),
        "original durable history is missing exact content kinds {kinds:?}"
    );
    Ok(())
}
