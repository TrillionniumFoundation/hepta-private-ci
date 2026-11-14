//! Retries standalone settings after an exact Finish owner without blocking
//! the session actor that must continue handling approvals and control input.

use super::SessionIo;
use super::current_span_w3c_trace_context;
use super::new_submission_id;
use super::session::Session;
use super::turn_input_retry::FinishFences;
use codex_protocol::error::CodexErr;
use codex_protocol::error::Result as CodexResult;
use codex_protocol::protocol::Op;
use codex_protocol::protocol::Submission;
use codex_protocol::protocol::ThreadSettingsOverrides;
use codex_protocol::protocol::W3cTraceContext;
use std::collections::HashMap;
use std::sync::Mutex;
use tokio::sync::oneshot;

enum ThreadSettingsAttempt {
    Complete,
    RetryAfterFinish(FinishFences),
}

#[derive(Default)]
pub(crate) struct PendingThreadSettingsRetries {
    pending: Mutex<HashMap<String, oneshot::Sender<ThreadSettingsAttempt>>>,
}

impl PendingThreadSettingsRetries {
    fn register(&self, submission_id: String) -> PendingThreadSettingsAttempt<'_> {
        let (reply_tx, reply_rx) = oneshot::channel();
        let previous = self
            .pending
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .insert(submission_id.clone(), reply_tx);
        assert!(previous.is_none(), "settings attempt ID must be unique");
        PendingThreadSettingsAttempt {
            retries: self,
            submission_id,
            reply_rx,
        }
    }

    fn respond(&self, submission_id: &str, reply: ThreadSettingsAttempt) -> bool {
        let sender = self
            .pending
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .remove(submission_id);
        sender.is_some_and(|sender| sender.send(reply).is_ok())
    }

    pub(super) fn complete(&self, submission_id: &str) {
        let _ = self.respond(submission_id, ThreadSettingsAttempt::Complete);
    }

    pub(super) fn retry_after_finish(&self, submission_id: &str, fences: FinishFences) -> bool {
        self.respond(
            submission_id,
            ThreadSettingsAttempt::RetryAfterFinish(fences),
        )
    }
}

struct PendingThreadSettingsAttempt<'a> {
    retries: &'a PendingThreadSettingsRetries,
    submission_id: String,
    reply_rx: oneshot::Receiver<ThreadSettingsAttempt>,
}

impl Drop for PendingThreadSettingsAttempt<'_> {
    fn drop(&mut self) {
        self.retries
            .pending
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .remove(&self.submission_id);
    }
}

impl SessionIo {
    /// Keeps a settings operation's original identity and payload across
    /// Finish retries. A final result remains on the normal event stream;
    /// the private reply only coordinates admission with the public caller.
    pub(crate) async fn submit_thread_settings_after_terminalization(
        &self,
        session: &Session,
        thread_settings: ThreadSettingsOverrides,
        trace: Option<W3cTraceContext>,
    ) -> CodexResult<String> {
        let id = new_submission_id();
        let trace = trace.or_else(current_span_w3c_trace_context);
        loop {
            let mut attempt = session.pending_thread_settings_retries.register(id.clone());
            self.submit_with_id(Submission {
                id: id.clone(),
                op: Op::ThreadSettings {
                    thread_settings: thread_settings.clone(),
                },
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
            let ThreadSettingsAttempt::RetryAfterFinish(fences) = reply else {
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
#[path = "thread_settings_retry_tests.rs"]
mod tests;
