//! Waits for exact Finish owners outside the actor before retrying mailbox
//! admission. Accepted messages are never enqueued a second time.

use super::SessionIo;
use super::current_span_w3c_trace_context;
use super::new_submission_id;
use super::session::Session;
use super::turn_input_retry::FinishFences;
use crate::agent::control::TurnStartCapacity;
use crate::codex_thread::CodexThread;
use codex_protocol::error::CodexErr;
use codex_protocol::error::Result as CodexResult;
use codex_protocol::protocol::InterAgentCommunication;
use codex_protocol::protocol::Op;
use codex_protocol::protocol::Submission;
use codex_protocol::protocol::W3cTraceContext;
use std::collections::HashMap;
use std::sync::Mutex;
use tokio::sync::oneshot;

#[derive(Debug)]
pub(super) enum MailboxEnqueueOutcome {
    Enqueued,
    Deferred,
}

enum MailboxAttempt {
    Complete,
    RetryAfterFinish(FinishFences),
}

#[derive(Default)]
pub(crate) struct PendingMailboxRetries {
    pending: Mutex<HashMap<String, oneshot::Sender<MailboxAttempt>>>,
}

impl PendingMailboxRetries {
    fn register(&self, submission_id: String) -> PendingMailboxAttempt<'_> {
        let (reply_tx, reply_rx) = oneshot::channel();
        let previous = self
            .pending
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .insert(submission_id.clone(), reply_tx);
        assert!(previous.is_none(), "mailbox attempt ID must be unique");
        PendingMailboxAttempt {
            retries: self,
            submission_id,
            reply_rx,
        }
    }

    pub(super) fn contains(&self, submission_id: &str) -> bool {
        self.pending
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .contains_key(submission_id)
    }

    fn respond(&self, submission_id: &str, reply: MailboxAttempt) -> bool {
        self.pending
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .remove(submission_id)
            .is_some_and(|sender| sender.send(reply).is_ok())
    }

    pub(super) fn complete(&self, submission_id: &str) {
        let _ = self.respond(submission_id, MailboxAttempt::Complete);
    }

    pub(super) fn retry_after_finish(&self, submission_id: &str, fences: FinishFences) -> bool {
        self.respond(submission_id, MailboxAttempt::RetryAfterFinish(fences))
    }
}

struct PendingMailboxAttempt<'a> {
    retries: &'a PendingMailboxRetries,
    submission_id: String,
    reply_rx: oneshot::Receiver<MailboxAttempt>,
}

impl Drop for PendingMailboxAttempt<'_> {
    fn drop(&mut self) {
        self.retries
            .pending
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .remove(&self.submission_id);
    }
}

impl SessionIo {
    pub(crate) async fn submit_mailbox_after_terminalization(
        &self,
        session: &Session,
        communication: InterAgentCommunication,
        trace: Option<W3cTraceContext>,
        parent_turn_id: Option<String>,
        root_turn_id: Option<String>,
    ) -> CodexResult<String> {
        let id = new_submission_id();
        let trace = trace.or_else(current_span_w3c_trace_context);
        loop {
            let mut attempt = session.pending_mailbox_retries.register(id.clone());
            self.submit_with_id(Submission {
                id: id.clone(),
                op: Op::InterAgentCommunication {
                    communication: communication.clone(),
                },
                trace: trace.clone(),
                parent_turn_id: parent_turn_id.clone(),
                root_turn_id: root_turn_id.clone(),
            })
            .await?;
            let reply = tokio::select! {
                biased;
                reply = &mut attempt.reply_rx => reply.map_err(|_| CodexErr::InternalAgentDied)?,
                () = self.session_loop_termination.clone() => return Err(CodexErr::InternalAgentDied),
            };
            drop(attempt);
            let MailboxAttempt::RetryAfterFinish(fences) = reply else {
                return Ok(id);
            };
            for completion in fences {
                tokio::select! {
                    biased;
                    () = completion.wait() => {},
                    () = self.session_loop_termination.clone() => return Err(CodexErr::InternalAgentDied),
                }
            }
        }
    }
}

impl CodexThread {
    /// A triggering message must repeat the ordinary capacity check after the
    /// captured Finish retires. This does not change StartIfIdle admission.
    pub(crate) async fn ensure_mailbox_capacity_after_finish(&self) -> CodexResult<()> {
        loop {
            let fences = match self
                .session
                .services
                .agent_control
                .turn_start_capacity(self)
                .await?
            {
                TurnStartCapacity::Available => return Ok(()),
                TurnStartCapacity::Finishing(fences) => fences,
            };
            for completion in fences {
                tokio::select! {
                    biased;
                    () = completion.wait() => {},
                    () = self.wait_until_terminated() => return Err(CodexErr::InternalAgentDied),
                }
            }
        }
    }
}

#[cfg(test)]
#[path = "mailbox_retry_tests.rs"]
mod tests;
