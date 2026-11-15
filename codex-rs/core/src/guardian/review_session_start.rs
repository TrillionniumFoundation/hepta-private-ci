//! Keep a reused review outside admission while its prior Finish owner retires.

use super::GuardianReviewSession;
use crate::session::FinishRetryState;
use codex_protocol::error::CodexErr;
use codex_protocol::error::Result as CodexResult;
use codex_protocol::turn_input::TurnInputMode;
use codex_protocol::turn_input::TurnInputRequest;
use codex_protocol::turn_input::TurnInputSubmission;

impl GuardianReviewSession {
    /// TurnComplete can arrive before its exact Finish owner has published the
    /// remaining durable state. Wait outside the session actor, within the
    /// caller's review deadline, so this review cannot steer that prior turn.
    pub(super) async fn submit_review_input(
        &self,
        request: TurnInputRequest,
    ) -> CodexResult<TurnInputSubmission> {
        loop {
            let state = {
                let active = self.session.active_turn.lock().await;
                self.session.finish_retry_state(active.as_ref())
            };
            match state {
                FinishRetryState::Clear | FinishRetryState::Blocked => break,
                FinishRetryState::Finishing(fences) => {
                    for completion in fences {
                        tokio::select! {
                            biased;
                            () = completion.wait() => {},
                            () = self.io.session_loop_termination.clone() => {
                                return Err(CodexErr::InternalAgentDied);
                            },
                        }
                    }
                }
            }
        }

        // A live task, abort, suspension, or new start is still rejected by
        // ordinary ordered admission. No rejected input is queued for retry.
        self.io
            .submit_turn_input(request, TurnInputMode::StartIfIdle)
            .await
    }
}

#[cfg(test)]
#[path = "review_session_start_tests.rs"]
mod tests;
