//! A host-selected task using the original Core reservation and live writer.

use std::sync::{Arc, Mutex};
use std::sync::atomic::{AtomicBool, Ordering};

use codex_history::{RolloutItem, TurnRecoveryReplayV1, TurnRecoveryRequestBinding, TurnRecoveryStartState};
use codex_protocol::error::{CodexErr, CodexErrorDetails, Result as CodexResult};
use codex_protocol::protocol::{EventMsg, TurnStartedEvent};
use codex_protocol::user_input::user_input_payload_sha256;
use codex_thread_store::{LoadThreadHistoryParams, PersistContext};
use tokio_util::sync::CancellationToken;

use super::TurnInput;
use super::session::Session;
use super::turn_context::TurnContext;
use crate::hosted_turn::{HostedAdmittedTurn, HostedQueueConfirmation, HostedPreparationOrigin, HostedTurnDispatch, HostedTurnEntry, HostedTurnInput, HostedTurnOutcome, HostedTurnProvenance, invalid, valid_sha256};
use crate::state::{TaskKind, TurnRecoveryAuthority};
use crate::tasks::{SessionTask, SessionTaskResult};

pub(crate) struct HostedTask {
    dispatch: Mutex<Option<HostedTurnDispatch>>,
    recovery: Arc<TurnRecoveryAuthority>,
}

impl HostedTask {
    pub(crate) fn new(dispatch: HostedTurnDispatch) -> Self {
        Self { dispatch: Mutex::new(Some(dispatch)), recovery: Arc::new(TurnRecoveryAuthority::default()) }
    }
}

impl SessionTask for HostedTask {
    fn kind(&self) -> TaskKind { TaskKind::Regular }
    fn hosted_execution(&self) -> bool { true }
    fn span_name(&self) -> &'static str { "session_task.hosted_turn" }
    // Native checkpoints observe old effects. They never authorize Core's
    // regular recovery sampler, even though the typed history binding is shared.
    fn recovery_authority(&self) -> Option<Arc<TurnRecoveryAuthority>> { Some(Arc::clone(&self.recovery)) }

    async fn run(
        self: Arc<Self>,
        session: Arc<Session>,
        context: Arc<TurnContext>,
        input: Vec<TurnInput>,
        cancellation: CancellationToken,
    ) -> SessionTaskResult {
        let dispatch = self.dispatch.lock().unwrap_or_else(std::sync::PoisonError::into_inner)
            .take().ok_or_else(|| invalid("hosted task was already consumed"))?;
        let [TurnInput::UserInput { content, client_id: Some(client_id) }] = input.as_slice() else {
            return Err(invalid("hosted admission requires one exact queued user input"));
        };
        if client_id != &dispatch.queue.client_id
            || user_input_payload_sha256(content).map_err(|error| invalid(&error.to_string()))? != dispatch.queue.payload_sha256 {
            return Err(invalid("hosted input differs from the original queue claim"));
        }
        if cancellation.is_cancelled() { return Err(CodexErr::TurnAborted); }
        if let Some(gate) = context.extension_data.get::<codex_extension_api::TurnStartGate>()
            && !gate.is_allowed() { return Err(CodexErr::TurnAborted); }
        let live_thread = session.live_thread_for_persistence("host an admitted turn")
            .map_err(|error| invalid(&error.to_string()))?.clone();
        live_thread.persist(PersistContext::TurnStart).await.map_err(storage_error)?;
        live_thread.flush().await.map_err(storage_error)?;
        refresh_original_history(&session, &context).await?;
        session.send_event(&context, EventMsg::TurnStarted(TurnStartedEvent {
            turn_id: context.sub_id.clone(), trace_id: context.trace_id.clone(),
            started_at: context.turn_timing_state.started_at_unix_secs().await,
            model_context_window: context.model_context_window(), collaboration_mode_kind: context.mode,
        })).await;

        // Pure host compilation happens before any Codex provider prewarm, hooks,
        // or sampling. The selected executor is never retried as a RegularTask.
        let plan = dispatch.executor.prepare(HostedTurnInput {
            origin: HostedPreparationOrigin::new(session.thread_id, context.sub_id.clone(), dispatch.queue.clone()),
            live_thread: live_thread.clone(), thread_id: session.thread_id,
            turn_id: context.sub_id.clone(), input: content.clone(), queue: dispatch.queue.clone(),
            cancellation: cancellation.clone(),
        }).await?;
        if !valid_sha256(&plan.request_fingerprint_sha256) {
            return Err(invalid("hosted first-request fingerprint is invalid"));
        }
        let provenance = HostedTurnProvenance {
            executor_id: dispatch.executor.executor_id().to_string(),
            correlation: plan.correlation,
            queue: dispatch.queue.clone(),
        };
        let history_boundary = session.current_recovery_history_boundary().await?;
        let turn_context = context.to_turn_context_item();
        let turn_context_sha256 = crate::model_provider_policy::canonical_sha256(&turn_context)
            .map_err(|error| invalid(error.detail()))?
            .as_str().to_string();
        let replay = TurnRecoveryReplayV1 {
            history_boundary: history_boundary.clone(),
            turn_context_sha256,
            start: TurnRecoveryStartState {
                final_output_json_schema: context.final_output_json_schema.clone(),
                parent_turn_id: context.turn_metadata_state.parent_turn_id(),
                root_turn_id: context.turn_metadata_state.root_turn_id(),
                responses_metadata_extra: provenance.metadata()?,
            },
            environments: super::turn::turn_recovery_environment_selections(&context.environments)
                .ok_or_else(|| invalid("hosted turn environments are not stable"))?,
        };
        session.ensure_turn_recovery_unready(&context.sub_id, &self.recovery).await?;
        let recovery = TurnRecoveryRequestBinding {
            turn_id: context.sub_id.clone(), generation: self.recovery.state.lock().await.generation,
            fingerprint_sha256: plan.request_fingerprint_sha256,
            history_boundary: Some(history_boundary), replay: Some(replay), replay_applied_from_generation: None,
        };
        // The marker precedes UserMessage: queue recovery cannot mistake a
        // partially recorded hosted input for a completed host checkpoint.
        live_thread.append_items(&[
            RolloutItem::TurnContext(turn_context),
            RolloutItem::TurnRecoveryRequestBinding(recovery.clone()),
        ]).await.map_err(storage_error)?;
        live_thread.flush().await.map_err(storage_error)?;
        let persistence_generation = session.rollout_persistence_failure_generation();
        session.record_user_prompt_and_emit_turn_item(&context, content, Some(client_id.clone()), PersistContext::TurnStart).await;
        session.flush_rollout().await.map_err(CodexErr::from)?;
        if session.rollout_persistence_failure_generation() != persistence_generation {
            return Err(CodexErr::Fatal("hosted input persistence is uncertain".to_string()));
        }
        let confirmed = Arc::new(AtomicBool::new(false));
        let entry = HostedTurnEntry::capture(&session, &context, cancellation.clone(),
            Arc::clone(&confirmed)).await?;
        let result = plan.execution.run(HostedAdmittedTurn {
            session: Arc::clone(&session), thread_id: session.thread_id, live_thread, recovery,
            queue: dispatch.queue, cancellation: cancellation.clone(),
            completion: HostedQueueConfirmation::AwaitQueueCommit(dispatch.completion), confirmed: Arc::clone(&confirmed), entry,
        }).await;
        let result = match result {
            Ok(HostedTurnOutcome::Completed { .. }) if !confirmed.load(Ordering::Acquire) => {
                Err(invalid("hosted task completed without its original queue commit"))
            }
            result => result,
        };
        finish_observation(&session, &context, result, &cancellation).await
    }
}

pub(super) async fn finish_observation(
    session: &Session,
    context: &TurnContext,
    result: CodexResult<HostedTurnOutcome>,
    cancellation: &CancellationToken,
) -> SessionTaskResult {
    // Reload through the original owner. A transient storage/authority/network
    // error cannot manufacture a terminal task outcome for an entered effect.
    let history = read_original_history(session, context).await;
    if cancellation.is_cancelled() { return Err(CodexErr::TurnAborted); }
    let result = match history {
        Ok(history) => match result {
            Ok(HostedTurnOutcome::Completed { final_answer }) => {
                publish_hosted_messages(session, context, &history).await
                    .map(|()| HostedTurnOutcome::Completed { final_answer })
            }
            result => result,
        },
        Err(error) => Err(error),
    };
    if cancellation.is_cancelled() { return Err(CodexErr::TurnAborted); }
    let error = match result {
        Ok(HostedTurnOutcome::Completed { final_answer }) => return Ok(final_answer),
        Ok(HostedTurnOutcome::Cancelled) => return Err(CodexErr::TurnAborted),
        Ok(HostedTurnOutcome::PendingObservation) => invalid("hosted effect outcome is unknown; original terminal observation is required"),
        Err(error) if matches!(error.details(), CodexErrorDetails::TurnAborted) => return Err(error),
        Err(error) => error,
    };
    // The original terminalizer distinguishes internal hosted technical
    // failure from cancellation. It emits the error and flushes while leaving
    // the exact logical tail unfinished. Neither a fake TurnComplete nor a
    // fake TurnAborted may replace an unknown original outcome.
    Err(error)
}

pub(super) async fn refresh_original_history(session: &Session, context: &TurnContext) -> CodexResult<()> {
    read_original_history(session, context).await.map(|_| ())
}

async fn read_original_history(session: &Session, context: &TurnContext) -> CodexResult<Vec<RolloutItem>> {
    let stored = session.services.thread_store.load_latest_model_context(LoadThreadHistoryParams {
        thread_id: session.thread_id, include_archived: false,
    }).await.map_err(storage_error)?;
    if stored.thread_id != session.thread_id { return Err(invalid("hosted history owner changed")); }
    session.apply_rollout_reconstruction(context, &stored.items).await;
    Ok(stored.items)
}

fn storage_error(error: codex_thread_store::ThreadStoreError) -> CodexErr {
    CodexErr::Fatal(format!("original hosted turn persistence: {error}"))
}

// Publish the typed UI projection of already persisted hosted model output.
// This never records another ResponseItem or creates an execution capability.
// Stable original IDs and matching existing completions make recovery a read
// before repair, rather than another assistant message on every observation.
#[derive(Debug)]
struct PendingHostedMessage {
    item: codex_protocol::items::TurnItem,
    expected: serde_json::Value,
    started: Option<codex_protocol::protocol::ItemStartedEvent>,
    completed: bool,
}

fn pending_hosted_messages(
    thread_id: codex_protocol::ThreadId,
    turn_id: &str,
    history: &[RolloutItem],
) -> CodexResult<Vec<PendingHostedMessage>> {
    use codex_protocol::items::TurnItem;
    use codex_protocol::models::ResponseItem;

    let mut positions = std::collections::BTreeMap::new();
    let mut messages = Vec::new();
    for original in history {
        let RolloutItem::ResponseItem(envelope) = original else { continue };
        if envelope.item.turn_id() != Some(turn_id)
            || !matches!(&envelope.item, ResponseItem::Message { role, .. } if role == "assistant") {
            continue;
        }
        let original_id = envelope.item.id()
            .ok_or_else(|| invalid("hosted assistant history lacks a stable original ID"))?;
        let Some(item @ TurnItem::AgentMessage(_)) = crate::parse_turn_item(&envelope.item) else { continue };
        let id = item.id();
        if original_id.as_str() != id.as_str()
            || id.is_empty() || positions.insert(id, messages.len()).is_some() {
            return Err(invalid("hosted assistant history has missing, changed, or duplicate original IDs"));
        }
        let expected = serde_json::to_value(&item)
            .map_err(|error| invalid(&format!("hosted assistant projection: {error}")))?;
        messages.push(PendingHostedMessage { item, expected, started: None, completed: false });
    }
    // Validate the complete projection before publishing any missing item.
    // A matching ID under another thread/turn is a conflict, not a new item.
    for original in history {
        let RolloutItem::EventMsg(event) = original else { continue };
        let (original_thread, original_turn, item) = match event {
            EventMsg::ItemStarted(event) => (event.thread_id, event.turn_id.as_str(), &event.item),
            EventMsg::ItemCompleted(event) => (event.thread_id, event.turn_id.as_str(), &event.item),
            _ => continue,
        };
        let Some(index) = positions.get(&item.id()).copied() else { continue };
        let message = &mut messages[index];
        if original_thread != thread_id || original_turn != turn_id
            || !matches!(item, TurnItem::AgentMessage(_)) {
            return Err(invalid("hosted assistant typed history changed its original owner or kind"));
        }
        match event {
            EventMsg::ItemStarted(event) => {
                if message.started.replace(event.clone()).is_some() {
                    return Err(invalid("hosted assistant has duplicate typed starts"));
                }
            }
            EventMsg::ItemCompleted(_) => {
                if serde_json::to_value(item)
                    .map_err(|error| invalid(&format!("hosted assistant observation: {error}")))? != message.expected {
                    return Err(invalid("hosted assistant typed completion changed its original content"));
                }
                if message.completed {
                    return Err(invalid("hosted assistant has duplicate typed completions"));
                }
                message.completed = true;
            }
            _ => unreachable!("matched typed item event above"),
        }
    }
    messages.retain(|message| !message.completed);
    Ok(messages)
}

async fn publish_hosted_messages(
    session: &Session,
    context: &TurnContext,
    history: &[RolloutItem],
) -> CodexResult<()> {
    let pending = pending_hosted_messages(session.thread_id, &context.sub_id, history)?;
    if pending.is_empty() { return Ok(()); }
    let persistence_generation = session.rollout_persistence_failure_generation();
    for message in pending {
        if let Some(started) = message.started {
            // Reconstruct only timing for an existing start. Do not persist or
            // send it again when repairing its missing original completion.
            context.turn_timing_state.record_item_started(message.item.id(), started.started_at_ms).await;
        } else {
            session.emit_turn_item_started(context, &message.item).await;
        }
        session.emit_turn_item_completed(context, message.item).await;
    }
    // The existing Core writer remains responsible for both persistence and
    // event delivery. An uncertain projection must not become TurnComplete.
    session.flush_rollout().await.map_err(CodexErr::from)?;
    if session.rollout_persistence_failure_generation() != persistence_generation {
        return Err(CodexErr::Fatal("hosted assistant projection persistence is uncertain".to_owned()));
    }
    Ok(())
}

#[cfg(test)]
#[path = "hosted_turn_output_tests.rs"]
mod hosted_output_tests;
