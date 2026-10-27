use codex_core::CodexThread;
use codex_history::RolloutItem;

/// Reads persisted response items through the original thread history owner.
///
/// Call after the relevant turn has completed. This preserves append order and
/// metadata; it does not project compaction replacement histories into a prompt.
pub(super) async fn persisted_response_items(
    codex: &CodexThread,
) -> anyhow::Result<Vec<serde_json::Value>> {
    codex.flush_rollout().await?;
    let history = codex.load_history(/*include_archived*/ false).await?;
    Ok(history
        .items
        .into_iter()
        .filter_map(|item| match item {
            RolloutItem::ResponseItem(envelope) => Some(envelope.item),
            _ => None,
        })
        .map(serde_json::to_value)
        .collect::<Result<_, _>>()?)
}
