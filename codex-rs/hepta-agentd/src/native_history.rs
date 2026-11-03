//! Project confirmed native output into the original canonical ThreadStore history.
//! The checkpoint retains the full provider JSON. This projection uses the
//! existing ResponseItem schema so ordinary Codex resume can read model context.

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_protocol::ResponseItemId;
use codex_protocol::models::ResponseItem;
use codex_thread_store::LiveThread;
use codex_thread_store::NativeCheckpointBinding;
use codex_thread_store::NativeCheckpointSession;
use codex_thread_store::StoredNativeCheckpoint;
use serde_json::Value;
use sha2::Digest;
use sha2::Sha256;

/// Call only after checkpoint confirmation, or normal original-owner recovery.
/// ReadOriginalOnly recovery intentionally cannot obtain this write permit.
pub(crate) async fn sync_native_history(
    live: &LiveThread,
    session: &NativeCheckpointSession,
    committed: &StoredNativeCheckpoint,
) -> Result<()> {
    ensure!(
        &committed.state.binding == session.binding(),
        "history checkpoint owner changed"
    );
    let (anchor, state) =
        crate::native_turn_checkpoint::decode(&committed.state.payload, &committed.state.binding)?;
    let original = anchor
        .run
        .as_ref()
        .context("native history lacks the original coordinator context binding")?;
    let initial_digest = anchor
        .rendered_context_sha256
        .as_deref()
        .unwrap_or(&original.context_digest);
    let items = project_output(&anchor.checkpoint, initial_digest, &state.context)?;
    live.sync_native_history(session, committed.version.clone(), items)
        .await?;
    Ok(())
}

fn project_output(
    binding: &NativeCheckpointBinding,
    initial_digest: &str,
    context: &[Value],
) -> Result<Vec<ResponseItem>> {
    let prefix = original_prefix_len(context, initial_digest)?;
    let namespace = output_namespace(binding)?;
    context[prefix..]
        .iter()
        .enumerate()
        .map(|(index, value)| {
            let mut item: ResponseItem = serde_json::from_value(value.clone())
                .context("native output cannot be represented in canonical history")?;
            match &item {
                ResponseItem::Message { role, .. } => ensure!(
                    role == "assistant",
                    "native output attempted to rewrite input history"
                ),
                ResponseItem::FunctionCall { call_id, name, .. } => ensure!(
                    !call_id.is_empty() && !name.is_empty(),
                    "native function call identity missing"
                ),
                ResponseItem::FunctionCallOutput { call_id, .. } => ensure!(
                    call_id.as_ref().is_some_and(|id| !id.is_empty()),
                    "native function result identity missing"
                ),
                ResponseItem::Reasoning { .. } => {}
                _ => anyhow::bail!(
                    "native output kind has no supported canonical history projection"
                ),
            }
            ensure!(
                item.turn_id().is_none_or(|turn| turn == binding.turn_id),
                "native output claims another original turn"
            );
            let kind = item
                .id_prefix()
                .context("native output has no canonical ID kind")?;
            // IDs are independent of output content and checkpoint revision, so a
            // changed item at the same position conflicts instead of looking new.
            item.set_id(Some(ResponseItemId::with_suffix(
                kind,
                format!("{namespace}_{index}"),
            )));
            item.set_turn_id_if_missing(&binding.turn_id);
            Ok(item)
        })
        .collect()
}

pub(crate) fn original_prefix_len(context: &[Value], initial_digest: &str) -> Result<usize> {
    let mut hasher = Sha256::new();
    hasher.update(b"[");
    let mut prefix = None;
    for count in 0..=context.len() {
        let mut candidate = hasher.clone();
        candidate.update(b"]");
        if format!("{:x}", candidate.finalize()) == initial_digest {
            prefix = Some(count);
            break;
        }
        if let Some(item) = context.get(count) {
            if count > 0 {
                hasher.update(b",");
            }
            hasher.update(serde_json::to_vec(item)?);
        }
    }
    prefix.context("native context no longer has its exact original input prefix")
}

pub(crate) fn output_namespace(binding: &NativeCheckpointBinding) -> Result<String> {
    Ok(format!(
        "hepta_native_{:x}",
        Sha256::digest(serde_json::to_vec(binding)?)
    ))
}

#[cfg(test)]
#[path = "native_history_tests.rs"]
mod tests;
