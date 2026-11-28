//! Retains legacy completion notifications across an exact Finish boundary.
//! The waiting caller owns its original items; the session actor remains free.

use super::TurnInput as PendingTurnInput;
use super::session::Session;
use super::turn_input_retry::FinishRetryState;
use codex_history::ResponseItemEnvelope;
use codex_protocol::error::CodexErr;
use codex_protocol::error::Result as CodexResult;
use codex_protocol::models::ResponseItem;
use std::future::Future;

impl Session {
    /// Wait only for captured Finish owners, then repeat full admission under
    /// the active-turn lock. Never enqueue rejected items or wait while holding
    /// session state needed by the terminalizer.
    #[expect(
        clippy::await_holding_invalid_type,
        reason = "admission, recovery revoke, and accepted fragment recording must remain atomic"
    )]
    pub(crate) async fn inject_fragment_after_finish(
        &self,
        items: Vec<ResponseItem>,
        terminated: impl Future<Output = ()>,
    ) -> CodexResult<()> {
        tokio::pin!(terminated);
        loop {
            let active = tokio::select! {
                biased;
                () = &mut terminated => return Err(CodexErr::InternalAgentDied),
                active = self.active_turn.lock() => active,
            };
            // A live successor retains the original injection path even while
            // a prior Finish owner is publishing its remaining side effects.
            if let Some(active_turn) = active.as_ref()
                && active_turn.task_terminalization.is_none()
                && let Some(task) = active_turn.task.as_ref()
            {
                if self.shutdown_started()
                    || self.has_pending_start_transition()
                    || active_turn.start_reservation.is_some()
                    || active_turn.start_transition.is_some()
                {
                    return Err(CodexErr::InvalidRequest(
                        "turn is transitioning or shutting down and cannot accept a completion notification"
                            .to_string(),
                    ));
                }
                if let Some(authority) = task.recovery_authority.as_ref() {
                    self.ensure_turn_recovery_unready(
                        &task.turn_context.sub_id,
                        authority.as_ref(),
                    )
                    .await?;
                }
                self.input_queue
                    .extend_pending_input_and_accept_mailbox_delivery_for_turn_state(
                        active_turn.turn_state.as_ref(),
                        items
                            .into_iter()
                            .map(ResponseItemEnvelope::new)
                            .map(PendingTurnInput::ResponseItem)
                            .collect(),
                    )
                    .await;
                return Ok(());
            }

            match self.finish_retry_state(active.as_ref()) {
                FinishRetryState::Finishing(fences) => {
                    drop(active);
                    for completion in fences {
                        tokio::select! {
                            biased;
                            () = &mut terminated => return Err(CodexErr::InternalAgentDied),
                            () = completion.wait() => {},
                        }
                    }
                    continue;
                }
                FinishRetryState::Blocked => {
                    return Err(CodexErr::InvalidRequest(
                        "session is transitioning or shutting down and cannot accept a completion notification"
                            .to_string(),
                    ));
                }
                FinishRetryState::Clear => {}
            }
            if active.is_some() {
                return Err(CodexErr::InvalidRequest(
                    "turn is transitioning and cannot accept a completion notification".to_string(),
                ));
            }

            let consumed_recovery = self.consume_recovery_candidate_for_mutation().await?;
            let turn_context = self.new_default_turn().await;
            self.record_conversation_items(turn_context.as_ref(), &items)
                .await;
            if consumed_recovery {
                self.settle_consumed_recovery_status();
            }
            drop(active);
            return Ok(());
        }
    }
}

#[cfg(test)]
#[path = "fragment_injection_tests.rs"]
mod tests;
