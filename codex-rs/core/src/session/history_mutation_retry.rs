//! Retries ordered rollback and manual compaction only after captured Finish
//! owners, while the session actor remains available for control input.

use super::SessionIo;
use super::current_span_w3c_trace_context;
use super::new_submission_id;
use super::session::Session;
use super::turn_input_retry::FinishFences;
use crate::state::TurnState;
use codex_protocol::error::CodexErr;
use codex_protocol::error::Result as CodexResult;
use codex_protocol::protocol::Op;
use codex_protocol::protocol::Submission;
use codex_protocol::protocol::W3cTraceContext;
use std::collections::HashMap;
use std::sync::Arc;
use std::sync::Mutex;
use tokio::sync::oneshot;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum HistoryMutation {
    Rollback { num_turns: u32 },
    Compact,
}

/// The reservation and Finish witnesses come from the same admission decision.
pub(crate) enum HistoryMutationReservation {
    Reserved(Arc<tokio::sync::Mutex<TurnState>>),
    Finishing(FinishFences),
    Busy,
}

/// An ordered attempt either finished or handed its exact Finish owners back.
pub(crate) enum HistoryMutationHandling {
    Complete,
    Deferred,
}

enum HistoryMutationAttempt {
    Complete,
    RetryAfterFinish(FinishFences),
}

#[derive(Default)]
pub(crate) struct PendingHistoryMutationRetries {
    pending: Mutex<HashMap<String, oneshot::Sender<HistoryMutationAttempt>>>,
}

impl PendingHistoryMutationRetries {
    fn register(&self, submission_id: String) -> PendingHistoryMutationAttempt<'_> {
        let (reply_tx, reply_rx) = oneshot::channel();
        let previous = self
            .pending
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .insert(submission_id.clone(), reply_tx);
        assert!(
            previous.is_none(),
            "history mutation attempt ID must be unique"
        );
        PendingHistoryMutationAttempt {
            retries: self,
            submission_id,
            reply_rx,
        }
    }

    fn respond(&self, submission_id: &str, reply: HistoryMutationAttempt) -> bool {
        let sender = self
            .pending
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .remove(submission_id);
        sender.is_some_and(|sender| sender.send(reply).is_ok())
    }

    pub(crate) fn complete(&self, submission_id: &str) {
        let _ = self.respond(submission_id, HistoryMutationAttempt::Complete);
    }

    pub(super) fn retry_after_finish(&self, submission_id: &str, fences: FinishFences) -> bool {
        self.respond(
            submission_id,
            HistoryMutationAttempt::RetryAfterFinish(fences),
        )
    }
}

struct PendingHistoryMutationAttempt<'a> {
    retries: &'a PendingHistoryMutationRetries,
    submission_id: String,
    reply_rx: oneshot::Receiver<HistoryMutationAttempt>,
}

impl Drop for PendingHistoryMutationAttempt<'_> {
    fn drop(&mut self) {
        self.retries
            .pending
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .remove(&self.submission_id);
    }
}

impl SessionIo {
    /// Wait only for ordered admission, never for a running compact task.
    /// Final success or rejection still uses the normal event stream.
    pub(crate) async fn submit_history_mutation_after_terminalization(
        &self,
        session: &Session,
        mutation: HistoryMutation,
        trace: Option<W3cTraceContext>,
    ) -> CodexResult<String> {
        let id = new_submission_id();
        let trace = trace.or_else(current_span_w3c_trace_context);
        loop {
            let mut attempt = session
                .pending_history_mutation_retries
                .register(id.clone());
            let op = match mutation {
                HistoryMutation::Rollback { num_turns } => Op::ThreadRollback { num_turns },
                HistoryMutation::Compact => Op::Compact,
            };
            self.submit_with_id(Submission {
                id: id.clone(),
                op,
                trace: trace.clone(),
                parent_turn_id: None,
                root_turn_id: None,
            })
            .await?;
            let reply = tokio::select! {
                biased;
                reply = &mut attempt.reply_rx => {
                    reply.map_err(|_| CodexErr::InternalAgentDied)?
                },
                () = self.session_loop_termination.clone() => {
                    return Err(CodexErr::InternalAgentDied);
                },
            };
            drop(attempt);
            let HistoryMutationAttempt::RetryAfterFinish(fences) = reply else {
                return Ok(id);
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

#[cfg(test)]
#[path = "history_mutation_retry_tests.rs"]
mod tests;
