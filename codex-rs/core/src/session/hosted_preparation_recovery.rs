//! Finish preparation under the original logical turn, with an independent
//! execution-owner proof and the same queue's completion barrier.

use std::sync::{Arc, Mutex};
use std::sync::atomic::{AtomicBool, Ordering};

use codex_history::{RolloutItem, TurnRecoveryRequestBinding};
use codex_protocol::error::{CodexErr, Result as CodexResult};
use codex_protocol::protocol::{EventMsg, TurnRecoveryCandidateEvent, TurnRecoveryCandidateState, TurnStartedEvent};
use tokio_util::sync::CancellationToken;

use super::TurnInput;
use super::session::Session;
use super::turn_context::TurnContext;
use crate::hosted_turn::{HostedAdmittedTurn, HostedQueueConfirmation, HostedPreparationOrigin, HostedPreparationRecoveryInput, HostedTurnDispatch, HostedTurnEntry, HostedTurnInput, HostedTurnOutcome, HostedTurnProvenance, invalid};
use crate::state::TaskKind;
use crate::tasks::{SessionTask, SessionTaskResult};

pub(super) struct HostedPreparationRecoveryTask {
    dispatch: Mutex<Option<HostedTurnDispatch>>,
    original: TurnRecoveryRequestBinding,
    source_generation: u64,
}

impl HostedPreparationRecoveryTask {
    pub(super) fn new(dispatch: HostedTurnDispatch, original: TurnRecoveryRequestBinding, source_generation: u64) -> Self {
        Self { dispatch: Mutex::new(Some(dispatch)), original, source_generation }
    }
}

impl SessionTask for HostedPreparationRecoveryTask {
    fn kind(&self) -> TaskKind { TaskKind::Regular }
    fn hosted_execution(&self) -> bool { true }
    fn span_name(&self) -> &'static str { "session_task.hosted_preparation_recovery" }
    fn turn_start_origin(&self) -> codex_extension_api::TurnStartOrigin { codex_extension_api::TurnStartOrigin::Recovery }

    async fn run(self: Arc<Self>, session: Arc<Session>, context: Arc<TurnContext>, _input: Vec<TurnInput>, cancellation: CancellationToken) -> SessionTaskResult {
        let result: CodexResult<HostedTurnOutcome> = async {
            if cancellation.is_cancelled() { return Err(CodexErr::TurnAborted); }
            let dispatch = self.dispatch.lock().unwrap_or_else(std::sync::PoisonError::into_inner)
                .take().ok_or_else(|| invalid("original hosted preparation was already consumed"))?;
            let request = dispatch.recovery.ok_or_else(|| invalid("retained hosted preparation has no original request"))?;
            let provenance = HostedTurnProvenance::from_recovery(&self.original)?
                .ok_or_else(|| invalid("original hosted preparation provenance is absent"))?;
            if request.original != self.original || context.sub_id != self.original.turn_id
                || dispatch.queue != provenance.queue || dispatch.executor.executor_id() != provenance.executor_id
            {
                return Err(invalid("retained hosted preparation changed its original owner"));
            }
            let live = session.live_thread_for_persistence("finish original hosted preparation")
                .map_err(|error| invalid(&error.to_string()))?.clone();
            // A crash may have preserved the original hosted provenance but
            // not yet written its input. Reconcile that exact old input while
            // Core owns this turn, before asking the host for a writer proof.
            // The host's exclusive proof must not span ThreadStore writes.
            let history_mode = session.state.lock().await.session_configuration.history_mode;
            crate::hosted_turn_input::restore_original_input(&session, &context,
                &self.original, &dispatch.queue, &request.input, &cancellation, history_mode).await?;
            let next_generation = self.source_generation.checked_add(1).ok_or_else(|| invalid("Core recovery generation exhausted"))?;
            let mut successor = self.original.clone();
            successor.generation = next_generation;
            successor.replay_applied_from_generation = Some(self.source_generation);
            live.append_items(&[
                RolloutItem::EventMsg(EventMsg::TurnRecoveryCandidate(TurnRecoveryCandidateEvent {
                    turn_id: context.sub_id.clone(), generation: next_generation, state: TurnRecoveryCandidateState::Unready,
                })),
                RolloutItem::TurnRecoveryRequestBinding(successor),
            ]).await.map_err(|error| invalid(&error.to_string()))?;
            live.flush().await.map_err(|error| invalid(&error.to_string()))?;
            session.send_event(&context, EventMsg::TurnStarted(TurnStartedEvent {
                turn_id: context.sub_id.clone(), trace_id: context.trace_id.clone(),
                started_at: context.turn_timing_state.started_at_unix_secs().await,
                model_context_window: context.model_context_window(), collaboration_mode_kind: context.mode,
            })).await;
            let plan = dispatch.executor.resume_preparation(HostedPreparationRecoveryInput {
                input: HostedTurnInput {
                    origin: HostedPreparationOrigin::retained(session.thread_id, context.sub_id.clone(), dispatch.queue.clone(), self.original.clone()),
                    live_thread: live.clone(), thread_id: session.thread_id, turn_id: context.sub_id.clone(),
                    input: request.input, queue: dispatch.queue.clone(), cancellation: cancellation.clone(),
                },
                recovery: self.original.clone(),
            }).await?;
            if plan.request_fingerprint_sha256 != self.original.fingerprint_sha256 || plan.correlation != provenance.correlation {
                return Err(invalid("hosted preparation changed its original fingerprint or correlation"));
            }
            let confirmed = Arc::new(AtomicBool::new(false));
            let entry = HostedTurnEntry::capture(&session, &context, cancellation.clone(),
                Arc::clone(&confirmed)).await?;
            let outcome = plan.execution.run(HostedAdmittedTurn {
                session: Arc::clone(&session), thread_id: session.thread_id, live_thread: live,
                recovery: self.original.clone(), queue: dispatch.queue, cancellation: cancellation.clone(),
                completion: HostedQueueConfirmation::AwaitQueueCommit(dispatch.completion), confirmed: Arc::clone(&confirmed), entry,
            }).await?;
            if matches!(outcome, HostedTurnOutcome::Completed { .. }) && !confirmed.load(Ordering::Acquire) {
                return Err(invalid("retained hosted preparation completed without original queue commit"));
            }
            Ok(outcome)
        }.await;
        super::hosted_turn::finish_observation(&session, &context, result, &cancellation).await
    }
}
