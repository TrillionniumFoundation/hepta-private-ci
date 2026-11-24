use codex_history::RolloutItem;
use core_test_support::test_codex::TestCodex;

pub(super) async fn persisted_response_items(
    test: &TestCodex,
) -> anyhow::Result<Vec<serde_json::Value>> {
    test.codex.flush_rollout().await?;
    let history = test.codex.load_history(/*include_archived*/ false).await?;
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
