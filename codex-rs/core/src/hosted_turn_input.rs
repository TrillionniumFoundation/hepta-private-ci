//! Reconcile an original hosted input at Core's retained-turn boundary.
//! This repairs only complete absence. Partial or conflicting input is held;
//! neither a second turn nor another user submission is created.

use codex_history::{RolloutLine, TurnRecoveryRequestBinding};
use codex_protocol::error::{CodexErr, Result as CodexResult};
use codex_protocol::models::ResponseItem;
use codex_protocol::protocol::ThreadHistoryMode;
use codex_protocol::user_input::{UserInput, user_input_payload_sha256};
use codex_thread_store::PersistContext;
use tokio::io::BufReader;
use tokio_util::sync::CancellationToken;

use crate::hosted_turn::{HostedQueueBinding, HostedTurnProvenance, invalid};
use crate::session::session::Session;
use crate::session::turn_context::TurnContext;

#[path = "hosted_turn_input_scan.rs"]
mod scan;

use scan::{InputHistoryScan, OriginalInputState};

/// Called only after the original Core task reservation is installed. All old
/// Core input writes have quiesced; flushing the existing live recorder first
/// settles commands it accepted before the old task stopped. The original
/// Queue process lock remains with the caller throughout this reconciliation.
pub(crate) async fn restore_original_input(
    session: &Session,
    context: &TurnContext,
    original: &TurnRecoveryRequestBinding,
    queue: &HostedQueueBinding,
    input: &[UserInput],
    cancellation: &CancellationToken,
    mode: ThreadHistoryMode,
) -> CodexResult<()> {
    if cancellation.is_cancelled() { return Err(CodexErr::TurnAborted); }
    let provenance = HostedTurnProvenance::from_recovery(original)?
        .ok_or_else(|| invalid("original hosted input has no typed provenance"))?;
    if original.turn_id != context.sub_id || provenance.queue != *queue || input.is_empty()
        || user_input_payload_sha256(input).map_err(|error| invalid(&error.to_string()))? != queue.payload_sha256
    {
        return Err(invalid("retained hosted input changed its original Core/Queue identity"));
    }
    let history = crate::hosted_turn_history::load(session, &original.turn_id).await?;
    if history.original != *original || history.preparation_interrupted {
        return Err(invalid("original hosted input is cancelled or belongs to another history"));
    }
    let response = session.response_item_from_user_input(input.to_vec());
    if read_original_input(session, original, queue, input, &response, mode).await? == OriginalInputState::Complete {
        return Ok(());
    }
    if cancellation.is_cancelled() { return Err(CodexErr::TurnAborted); }
    let before = session.rollout_persistence_failure_generation();
    session.record_user_prompt_and_emit_turn_item(context, input,
        Some(queue.client_id.clone()), PersistContext::TurnStart).await;
    session.flush_rollout().await.map_err(CodexErr::from)?;
    if session.rollout_persistence_failure_generation() != before {
        return Err(invalid("original hosted input append is uncertain; no replay is authorized"));
    }
    if read_original_input(session, original, queue, input, &response, mode).await? != OriginalInputState::Complete {
        return Err(invalid("original hosted input append was not confirmed by exact readback"));
    }
    if cancellation.is_cancelled() { return Err(CodexErr::TurnAborted); }
    Ok(())
}

async fn read_original_input(
    session: &Session,
    original: &TurnRecoveryRequestBinding,
    queue: &HostedQueueBinding,
    input: &[UserInput],
    response: &ResponseItem,
    mode: ThreadHistoryMode,
) -> CodexResult<OriginalInputState> {
    let live = session.live_thread_for_persistence("read original hosted input")
        .map_err(|error| invalid(&error.to_string()))?;
    live.flush().await.map_err(|error| invalid(&error.to_string()))?;
    let path = live.local_rollout_path().await.map_err(|error| invalid(&error.to_string()))?
        .ok_or_else(|| invalid("original hosted input requires its existing local history owner"))?;
    let mut scan = InputHistoryScan::new(session.thread_id, original, queue, input, response, mode)?;
    let file = tokio::fs::File::open(path).await.map_err(CodexErr::from)?;
    let mut reader = BufReader::new(file);
    while let Some(bytes) = crate::hosted_turn_history::read_bounded_line(&mut reader).await? {
        if bytes.iter().all(u8::is_ascii_whitespace) { continue; }
        let line: RolloutLine = serde_json::from_slice(&bytes)
            .map_err(|error| invalid(&format!("original hosted input history is malformed: {error}")))?;
        scan.observe(&line.item)?;
    }
    scan.finish()
}
