//! Recovery under the original active-turn lifecycle, without fresh dispatch.

use std::sync::Arc;
use std::sync::atomic::Ordering;

use codex_history::{RolloutItem, TurnRecoveryRequestBinding};
use codex_protocol::error::{CodexErr, CodexErrorDetails, Result as CodexResult};
use codex_protocol::protocol::{EventMsg, TurnRecoveryCandidateEvent, TurnRecoveryCandidateState, TurnStartedEvent};
use codex_protocol::turn_input::{NotSubmittedReason, TurnInputSubmission};
use tokio_util::sync::CancellationToken;

use super::TurnInput;
use super::session::Session;
use super::turn_context::TurnContext;
use crate::hosted_turn::{HostedTurnExecutor, HostedTurnMode, HostedTurnObservation, HostedTurnOutcome, HostedTurnProvenance, HostedTurnRecoveryInput, invalid};
use crate::state::TaskKind;
use crate::tasks::{MailboxParentProvenance, SessionTask, SessionTaskResult, StartReservationOwner, StartTaskOutcome};

pub(super) async fn start(session: &Arc<Session>, expected_epoch: u64, turn_id: String) -> CodexResult<TurnInputSubmission> {
    let mode = session.services.session_extension_data.get::<HostedTurnMode>()
        .ok_or_else(|| invalid("original hosted recovery executor is absent"))?;
    let history = crate::hosted_turn_history::load(session, &turn_id).await?;
    let provenance = HostedTurnProvenance::from_recovery(&history.original)?
        .ok_or_else(|| invalid("original hosted recovery provenance is absent"))?;
    if provenance.executor_id != mode.executor.executor_id() {
        return Err(invalid("original hosted recovery executor changed"));
    }
    let reservation = {
        let mut active = session.active_turn.lock().await;
        if active.is_some() || session.shutdown_started() || session.has_pending_admission_fence()
            || session.turn_epoch.load(Ordering::Acquire) != expected_epoch {
            return Ok(TurnInputSubmission::NotSubmitted { reason: NotSubmittedReason::RecoveryStateChanged });
        }
        let Some(reservation) = super::turn_input::reserve_start_after_admission(session, &mut active, turn_id.clone(), /*consumed_recovery*/ false) else {
            return Ok(TurnInputSubmission::NotSubmitted { reason: NotSubmittedReason::NotIdle });
        };
        reservation
    };
    let mut owner = StartReservationOwner::new(session, reservation);
    let context = session.new_default_turn_with_sub_id(turn_id.clone()).await;
    let preparation = session.pending_user_message_admissions.take_hosted(&turn_id);
    let preparing = preparation.is_some();
    if preparing && history.preparation_interrupted {
        return Err(invalid("original hosted turn was interrupted; preparation cannot restart"));
    }
    let outcome = match preparation {
        Some(dispatch) => session.start_task_owned(
            Arc::clone(&context), Vec::new(),
            super::hosted_preparation_recovery::HostedPreparationRecoveryTask::new(dispatch, history.original, history.latest_generation),
            MailboxParentProvenance::Ignore, owner.handle().clone(),
        ).await,
        None => session.start_task_owned(
            Arc::clone(&context), Vec::new(),
            HostedRecoveryTask { executor: Arc::clone(&mode.executor), original: history.original, source_generation: history.latest_generation, continuation_allowed: !history.preparation_interrupted },
            MailboxParentProvenance::Ignore, owner.handle().clone(),
        ).await,
    };
    if outcome != StartTaskOutcome::Stale { owner.disarm(); }
    if preparing && outcome == StartTaskOutcome::Attached {
        session.pending_user_message_admissions.complete_started(&turn_id, context);
    }
    Ok(if outcome == StartTaskOutcome::Attached {
        TurnInputSubmission::Started { turn_id }
    } else {
        TurnInputSubmission::NotSubmitted { reason: NotSubmittedReason::NotIdle }
    })
}

struct HostedRecoveryTask {
    executor: Arc<dyn HostedTurnExecutor>,
    original: TurnRecoveryRequestBinding,
    source_generation: u64,
    continuation_allowed: bool,
}

impl SessionTask for HostedRecoveryTask {
    fn kind(&self) -> TaskKind { TaskKind::Regular }
    fn hosted_execution(&self) -> bool { true }
    fn span_name(&self) -> &'static str { "session_task.hosted_observation" }
    fn turn_start_origin(&self) -> codex_extension_api::TurnStartOrigin { codex_extension_api::TurnStartOrigin::Recovery }

    async fn run(self: Arc<Self>, session: Arc<Session>, context: Arc<TurnContext>, _input: Vec<TurnInput>, cancellation: CancellationToken) -> SessionTaskResult {
        if cancellation.is_cancelled() { return Err(CodexErr::TurnAborted); }
        let result: CodexResult<HostedTurnOutcome> = async {
        let live = session.live_thread_for_persistence("observe an original hosted turn")
            .map_err(|error| invalid(&error.to_string()))?.clone();
        let next_generation = self.source_generation.checked_add(1).ok_or_else(|| invalid("Core recovery generation exhausted"))?;
        let mut successor = self.original.clone();
        successor.generation = next_generation;
        successor.replay_applied_from_generation = Some(self.source_generation);
        // Keep the original native anchor untouched. This is only Core's exact
        // typed lifecycle successor; no Ready marker or sampling grant is made.
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
        let provenance = HostedTurnProvenance::from_recovery(&self.original)?
            .ok_or_else(|| invalid("original hosted recovery provenance disappeared"))?;
        let observation = HostedTurnObservation {
            live_thread: live, thread_id: session.thread_id, turn_id: context.sub_id.clone(),
            queue: provenance.queue, recovery: self.original.clone(),
        };
        if self.continuation_allowed
            && let Some(outcome) = crate::hosted_turn::checkpoint_continuation::try_run(
                &session, &context, &self.executor, &observation, &cancellation,
            ).await?
        {
            return Ok(outcome);
        }
        let observed = self.executor.recover(HostedTurnRecoveryInput {
            observation: HostedTurnObservation {
                live_thread: observation.live_thread.clone(), thread_id: observation.thread_id,
                turn_id: observation.turn_id.clone(), queue: observation.queue.clone(), recovery: observation.recovery.clone(),
            },
            cancellation: cancellation.clone(),
        }).await;
        let terminal = match &observed {
            Ok(HostedTurnOutcome::Completed { .. } | HostedTurnOutcome::Cancelled) => true,
            Ok(HostedTurnOutcome::PendingObservation) => false,
            Err(error) => matches!(error.details(), CodexErrorDetails::TurnAborted),
        };
        if terminal || cancellation.is_cancelled() || !self.continuation_allowed {
            return observed;
        }
        // Observation may have settled the original pending effect and made its
        // checkpoint continuable. Recheck once in this same task, using the same
        // original provenance; do not append another typed lifecycle successor.
        // None preserves the observation result, while conflicting proof stays held.
        if let Some(outcome) = crate::hosted_turn::checkpoint_continuation::try_run(
            &session, &context, &self.executor, &observation, &cancellation,
        ).await? {
            return Ok(outcome);
        }
        observed
        }.await;
        super::hosted_turn::finish_observation(&session, &context, result, &cancellation).await
    }
}
