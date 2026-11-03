//! Idempotent canonical history projection under the original live writer.
//! A confirmed checkpoint is authoritative; JSONL may lag it after interruption.
//! Only a complete, exact existing prefix is repairable. A partial line or a
//! conflicting item is held for diagnosis, never truncated or overwritten.

use std::path::Path;

use codex_protocol::ResponseItemId;
use codex_protocol::items::TurnItem;
use codex_protocol::models::ResponseItem;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::ThreadHistoryMode;
use codex_protocol::user_input::user_input_payload_sha256;
use codex_rollout::RolloutItem;
use serde_json::Value;
use sha2::Digest;
use sha2::Sha256;
use tokio::io::AsyncBufReadExt;
use tokio::io::BufReader;

use super::LocalThreadStore;
use crate::NativeCheckpointLoad;
use crate::NativeCheckpointSession;
use crate::NativeCheckpointVersion;
use crate::NativeHistoryVerification;
use crate::ThreadStoreError;
use crate::ThreadStoreResult;

const MAX_LINE_BYTES: usize = 16 * 1024 * 1024;

pub(super) async fn verify(
    store: &LocalThreadStore,
    session: &NativeCheckpointSession,
    expected: NativeHistoryVerification,
) -> ThreadStoreResult<()> {
    let binding = &session.binding;
    let RolloutItem::TurnRecoveryRequestBinding(expected_recovery) = expected.recovery_item else {
        return Err(conflict("native history requires the original recovery item"));
    };
    if expected_recovery.turn_id != binding.turn_id {
        return Err(conflict("native history verification changed its original turn"));
    }
    let _lifecycle = store.live_writer_locks.reserve_lifecycle(binding.thread_id).await;
    let _writer = store.live_writer_locks.lock(binding.thread_id).await;
    super::native_checkpoint::verify_writer(store, session).await?;
    let (recorder, rollout_id, _) = super::live_writer::live_writer_parts(store, binding.thread_id).await?;
    if rollout_id != session.rollout_id {
        return Err(conflict("native history rollout owner changed"));
    }
    let path = recorder.rollout_path();
    if path.extension().is_none_or(|extension| extension != "jsonl") {
        return Err(conflict("native history requires the live plain JSONL writer"));
    }
    // Unlike a resumable model-context suffix, this must see every earlier
    // duplicate. Retain only one bounded line and constant-size presence flags.
    // No flush, materialization, checkpoint write or host permit occurs here.
    let mut reader = BufReader::new(tokio::fs::File::open(path).await.map_err(storage_error)?);
    let mut metadata_seen = false;
    let mut recovery_seen = false;
    let mut input_seen = expected.queued_input.is_none();
    while let Some(bytes) = complete_line(&mut reader).await? {
        if bytes.iter().all(u8::is_ascii_whitespace) { continue; }
        let line = codex_rollout::decode_rollout_line(
            serde_json::from_slice(&bytes).map_err(storage_error)?,
        ).map_err(storage_error)?;
        match line.item {
            RolloutItem::SessionMeta(meta) if !metadata_seen => {
                if meta.meta.id != binding.thread_id {
                    return Err(conflict("native history belongs to another original thread"));
                }
                metadata_seen = true;
            }
            RolloutItem::TurnRecoveryRequestBinding(recovery)
                if recovery.turn_id == expected_recovery.turn_id && recovery.generation == expected_recovery.generation => {
                    if recovery_seen || recovery != expected_recovery {
                        return Err(conflict("original recovery history is duplicated or changed"));
                    }
                    recovery_seen = true;
                }
            RolloutItem::EventMsg(event) => {
                let (thread_id, turn_id, item) = match event {
                    EventMsg::ItemStarted(event) => (event.thread_id, event.turn_id, event.item),
                    EventMsg::ItemCompleted(event) => (event.thread_id, event.turn_id, event.item),
                    _ => continue,
                };
                if let Some(queued) = &expected.queued_input
                    && let TurnItem::UserMessage(input) = item
                    && input.client_id.as_deref() == Some(queued.client_id.as_str()) {
                        if thread_id != binding.thread_id || turn_id != binding.turn_id
                            || user_input_payload_sha256(&input.content).map_err(storage_error)? != queued.payload_sha256 {
                            return Err(conflict("original queued input history is ambiguous or changed"));
                        }
                        input_seen = true;
                    }
            }
            _ => {}
        }
    }
    if !metadata_seen || !recovery_seen || !input_seen {
        return Err(conflict("native history lacks its original metadata, recovery, or queued input"));
    }
    Ok(())
}

pub(super) async fn sync(
    store: &LocalThreadStore,
    session: &NativeCheckpointSession,
    expected: NativeCheckpointVersion,
    items: Vec<ResponseItem>,
) -> ThreadStoreResult<()> {
    let store = store.clone();
    let session = session.clone();
    // Recorder commands survive a cancelled receiver. The owner task keeps the
    // same writer/currentness guards through append, fsync, and exact readback.
    tokio::spawn(async move { sync_owned(&store, &session, expected, items).await })
        .await
        .map_err(storage_error)?
}

async fn sync_owned(
    store: &LocalThreadStore,
    session: &NativeCheckpointSession,
    expected: NativeCheckpointVersion,
    items: Vec<ResponseItem>,
) -> ThreadStoreResult<()> {
    let binding = &session.binding;
    let namespace = format!(
        "hepta_native_{:x}",
        Sha256::digest(serde_json::to_vec(binding).map_err(storage_error)?)
    );
    let mut canonical = Vec::with_capacity(items.len());
    let mut exact = Vec::with_capacity(items.len());
    for (index, item) in items.into_iter().enumerate() {
        let supported = matches!(&item, ResponseItem::Message { role, .. } if role == "assistant")
            || matches!(&item, ResponseItem::FunctionCall { .. }
                | ResponseItem::FunctionCallOutput { .. } | ResponseItem::Reasoning { .. });
        let prefix = item.id_prefix().ok_or_else(|| conflict("native item has no canonical ID kind"))?;
        let id = ResponseItemId::with_suffix(prefix, format!("{namespace}_{index}"));
        if !supported || item.turn_id() != Some(binding.turn_id.as_str()) || item.id() != Some(&id) {
            return Err(conflict("native history item kind, original turn, or stable ID changed"));
        }
        let item = RolloutItem::ResponseItem(item.into());
        exact.push(serde_json::to_value(&item).map_err(storage_error)?);
        canonical.push(item);
    }
    let _lifecycle = store.live_writer_locks.reserve_lifecycle(binding.thread_id).await;
    let _writer = store.live_writer_locks.lock(binding.thread_id).await;
    let loaded = super::native_checkpoint::load_locked(store, session).await?;
    if !matches!(loaded, NativeCheckpointLoad::Present(ref record)
        if record.version == expected && record.state.binding == *binding)
    {
        return Err(conflict("native history checkpoint head does not match"));
    }
    let _permit = session.currentness.acquire(binding).await?;
    let (recorder, rollout_id, history_mode) =
        super::live_writer::live_writer_parts(store, binding.thread_id).await?;
    if rollout_id != session.rollout_id {
        return Err(conflict("native history rollout owner changed"));
    }
    let path = recorder.rollout_path();
    if path.extension().is_none_or(|extension| extension != "jsonl") {
        return Err(conflict("native history requires the live plain JSONL writer"));
    }
    recorder.flush().await.map_err(storage_error)?;
    let present = exact_prefix(path, &binding.turn_id, &namespace, &exact).await?;
    if present < canonical.len() {
        recorder.record_canonical_items(&canonical[present..]).await.map_err(storage_error)?;
        recorder.flush().await.map_err(storage_error)?;
    }
    // Even an empty suffix must make the original input/recovery binding
    // durable before QueueStore completion. Flush alone is not an fsync.
    tokio::fs::OpenOptions::new().write(true).open(path).await.map_err(storage_error)?
        .sync_all().await.map_err(storage_error)?;
    #[cfg(unix)]
    if let Some(parent) = path.parent() {
        tokio::fs::File::open(parent).await.map_err(storage_error)?
            .sync_all().await.map_err(storage_error)?;
    }
    if exact_prefix(path, &binding.turn_id, &namespace, &exact).await? != canonical.len() {
        return Err(conflict("native history append was not confirmed by exact readback"));
    }
    if !matches!(history_mode, ThreadHistoryMode::Legacy) {
        // This remains the original rebuildable SQLite projection, not a new
        // history authority. A failure is retryable from the same exact JSONL.
        super::thread_history_materialization::materialize_to_sqlite(store, rollout_id, path).await?;
    }
    Ok(())
}

async fn exact_prefix(
    path: &Path,
    turn_id: &str,
    namespace: &str,
    expected: &[Value],
) -> ThreadStoreResult<usize> {
    let file = tokio::fs::File::open(path).await.map_err(storage_error)?;
    let mut reader = BufReader::new(file);
    let id_marker = format!("_{namespace}_");
    let mut observed = 0;
    while let Some(bytes) = complete_line(&mut reader).await? {
        if bytes.iter().all(u8::is_ascii_whitespace) {
            continue;
        }
        let mut value: Value = serde_json::from_slice(&bytes).map_err(storage_error)?;
        let line = codex_rollout::decode_rollout_line(value.clone()).map_err(storage_error)?;
        let RolloutItem::ResponseItem(envelope) = line.item else { continue };
        let item = envelope.item;
        let native_id = item.id().is_some_and(|id| id.as_str().contains(&id_marker));
        let original_input = matches!(&item, ResponseItem::Message { role, .. }
            if matches!(role.as_str(), "user" | "developer" | "system"))
            || matches!(&item, ResponseItem::AdditionalTools { .. });
        if !native_id && (item.turn_id() != Some(turn_id) || original_input) {
            continue;
        }
        let object = value.as_object_mut().ok_or_else(|| conflict("history line is not an object"))?;
        object.remove("timestamp");
        object.remove("ordinal");
        if expected.get(observed) != Some(&value) {
            return Err(conflict("native history has a duplicate, reordered, or conflicting item"));
        }
        observed += 1;
    }
    Ok(observed)
}

async fn complete_line(reader: &mut BufReader<tokio::fs::File>) -> ThreadStoreResult<Option<Vec<u8>>> {
    let mut line = Vec::new();
    loop {
        let available = reader.fill_buf().await.map_err(storage_error)?;
        if available.is_empty() {
            return if line.is_empty() { Ok(None) } else { Err(conflict("native history has a partial final line")) };
        }
        let count = available.iter().position(|byte| *byte == b'\n').map_or(available.len(), |index| index + 1);
        if line.len() + count > MAX_LINE_BYTES {
            return Err(conflict("history line exceeds bounded strict-read capacity"));
        }
        let complete = available[count - 1] == b'\n';
        line.extend_from_slice(&available[..count]);
        reader.consume(count);
        if complete { return Ok(Some(line)); }
    }
}

fn conflict(message: &str) -> ThreadStoreError {
    ThreadStoreError::Conflict { message: message.to_owned() }
}

fn storage_error(error: impl std::fmt::Display) -> ThreadStoreError {
    ThreadStoreError::Internal { message: error.to_string() }
}

#[cfg(test)]
#[path = "native_history_tests.rs"]
mod tests;
