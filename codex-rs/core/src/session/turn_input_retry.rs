//! Keeps start-or-steer callers outside the session loop while a completed
//! turn's exact terminalization owner is still publishing durable state.

use super::SessionIo;
use super::session::Session;
use crate::agent::control::TurnStartCapacity;
use crate::codex_thread::CodexThread;
use crate::state::ActiveTurn;
use crate::state::StartTransitionCompletion;
use crate::state::TaskTerminalizationKind;
use codex_protocol::error::CodexErr;
use codex_protocol::error::Result as CodexResult;
use codex_protocol::turn_input::NotSubmittedReason;
use codex_protocol::turn_input::TurnInputMode;
use codex_protocol::turn_input::TurnInputRequest;
use codex_protocol::turn_input::TurnInputSubmission;
use std::collections::HashMap;
use std::sync::Arc;
use std::sync::Mutex;

pub(crate) type FinishFences = Vec<Arc<StartTransitionCompletion>>;

/// One registry observation distinguishes an already retired owner from an
/// exact Finish fence and a terminalizer that callers must not retry.
pub(crate) enum FinishRetryState {
    Clear,
    Finishing(FinishFences),
    Blocked,
}

#[derive(Default)]
pub(crate) struct PendingTurnInputRetries {
    pending: Mutex<HashMap<String, Option<FinishFences>>>,
}

impl PendingTurnInputRetries {
    fn register(&self, submission_id: String) -> PendingTurnInputRetry<'_> {
        let previous = self
            .pending
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .insert(submission_id.clone(), None);
        assert!(previous.is_none(), "turn-input retry ID must be unique");
        PendingTurnInputRetry {
            retries: self,
            submission_id,
        }
    }

    fn record(&self, submission_id: &str, fences: FinishFences) -> bool {
        let mut pending = self
            .pending
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let Some(entry) = pending.get_mut(submission_id) else {
            // A cancelled waiter must not leave an orphaned retry registration.
            return false;
        };
        *entry = Some(fences);
        true
    }
}

struct PendingTurnInputRetry<'a> {
    retries: &'a PendingTurnInputRetries,
    submission_id: String,
}

impl PendingTurnInputRetry<'_> {
    fn take(&self) -> Option<FinishFences> {
        self.retries
            .pending
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .get_mut(&self.submission_id)
            .and_then(Option::take)
    }
}

impl Drop for PendingTurnInputRetry<'_> {
    fn drop(&mut self) {
        self.retries
            .pending
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .remove(&self.submission_id);
    }
}

impl Session {
    /// Called with `active_turn` locked at the ordered routing decision.
    /// Capture only finish owners, never an abort, suspension, live task, or
    /// start reservation. The returned witnesses retain their identity even
    /// when the terminalizer clears the active slot before the reply arrives.
    pub(super) fn record_turn_input_finish_retry(
        &self,
        submission_id: &str,
        active_turn: Option<&ActiveTurn>,
    ) -> bool {
        match self.finish_retry_state(active_turn) {
            FinishRetryState::Finishing(fences) => self
                .pending_turn_input_retries
                .record(submission_id, fences),
            FinishRetryState::Clear | FinishRetryState::Blocked => false,
        }
    }

    /// Observes terminalization and captures its exact Finish owners under
    /// one registry lock. Retirement does not take `active_turn`, so a
    /// separate pending check followed by capture would race with retirement.
    pub(crate) fn finish_retry_state(&self, active_turn: Option<&ActiveTurn>) -> FinishRetryState {
        let _admission_gate = self
            .start_admission_gate
            .lock()
            .unwrap_or_else(|error| panic!("start admission gate mutex poisoned: {error:?}"));
        if self.shutdown_started() {
            return FinishRetryState::Blocked;
        }
        let has_pending_start = self.has_pending_start_transition();
        let pending = self
            .pending_task_terminalization_completions
            .lock()
            .unwrap_or_else(|error| {
                panic!("task terminalization completion registry mutex poisoned: {error:?}")
            });
        if has_pending_start {
            return FinishRetryState::Blocked;
        }
        if pending.is_empty() {
            return FinishRetryState::Clear;
        }
        if active_turn.is_some_and(|active| {
            active.task.is_some()
                || active.start_reservation.is_some()
                || active.start_transition.is_some()
                || active
                    .task_terminalization
                    .as_ref()
                    .is_none_or(|owner| owner.kind != TaskTerminalizationKind::Finish)
        }) {
            return FinishRetryState::Blocked;
        }
        if pending
            .iter()
            .any(|(_, _, kind, _, _, _)| *kind != TaskTerminalizationKind::Finish)
        {
            return FinishRetryState::Blocked;
        }
        FinishRetryState::Finishing(
            pending
                .iter()
                .map(|(_, completion, _, _, _, _)| Arc::clone(completion))
                .collect(),
        )
    }
}

impl SessionIo {
    /// Re-enter normal admission after the exact finish owner has completed.
    /// Waiting here leaves the session loop free to handle approvals and other
    /// replies needed by a terminalizer's pending-work startup. The caller's
    /// request, submission ID, and exact-admission registration remain owned
    /// by the same future throughout; no rejected input is enqueued.
    pub(crate) async fn submit_turn_input_after_terminalization(
        &self,
        session: &Session,
        submission_id: String,
        request: TurnInputRequest,
        mode: TurnInputMode,
    ) -> CodexResult<TurnInputSubmission> {
        if mode != TurnInputMode::StartOrSteer {
            return self
                .submit_turn_input_with_id(submission_id, request, mode)
                .await;
        }
        let retry = session
            .pending_turn_input_retries
            .register(submission_id.clone());
        loop {
            let result = self
                .submit_turn_input_with_id(submission_id.clone(), request.clone(), mode.clone())
                .await?;
            if !matches!(
                result,
                TurnInputSubmission::NotSubmitted {
                    reason: NotSubmittedReason::NotIdle
                }
            ) {
                return Ok(result);
            }
            let Some(fences) = retry.take() else {
                return Ok(result);
            };
            for completion in fences {
                tokio::select! {
                    biased;
                    () = completion.wait() => {},
                    () = self.session_loop_termination.clone() => {
                        return Err(CodexErr::InternalAgentDied);
                    },
                }
            }
        }
    }
}

impl CodexThread {
    /// The public preflight can observe a cleared active slot while its exact
    /// Finish owner is still publishing. Wait outside the actor and recheck
    /// capacity, just as ordered routing retries that same Finish boundary.
    pub(crate) async fn ensure_turn_start_capacity_after_finish(
        &self,
        mode: &TurnInputMode,
    ) -> CodexResult<()> {
        if *mode != TurnInputMode::StartOrSteer {
            return self
                .session
                .services
                .agent_control
                .ensure_execution_capacity_for_turn_start(self)
                .await;
        }
        loop {
            let capacity = self
                .session
                .services
                .agent_control
                .turn_start_capacity(self)
                .await?;
            let fences = match capacity {
                TurnStartCapacity::Available => return Ok(()),
                TurnStartCapacity::Finishing(fences) => fences,
            };
            for completion in fences {
                tokio::select! {
                    biased;
                    () = completion.wait() => {},
                    () = self.wait_until_terminated() => {
                        return Err(CodexErr::InternalAgentDied);
                    },
                }
            }
        }
    }
}

#[cfg(test)]
#[path = "turn_input_retry_tests.rs"]
mod tests;
