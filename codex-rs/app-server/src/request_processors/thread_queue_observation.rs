//! The original queue's finite SELECT/rollout observer. No resume or reservation.
use super::*;
use codex_app_server_protocol::ThreadQueueObserveOutcome;
use codex_app_server_protocol::ThreadQueueObserveParams;
use codex_app_server_protocol::ThreadQueueObserveResponse;
use codex_app_server_protocol::ThreadQueueObservedTerminal;
use codex_queue_extension::QueueHistoricalOutcome;
use codex_queue_extension::QueueHistoricalTerminal;

impl ThreadQueueRequestProcessor {
    pub(crate) async fn observe(
        &self,
        params: ThreadQueueObserveParams,
    ) -> Result<ThreadQueueObserveResponse, JSONRPCErrorError> {
        if params.client_user_message_id.is_empty()
            || params.client_user_message_id.len() > 256
            || params.client_user_message_id.chars().any(char::is_control)
            || params.expected_payload_sha256.len() != 64
            || !params
                .expected_payload_sha256
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        {
            return Err(invalid_request("invalid exact queue observation"));
        }
        let thread_id = ThreadId::from_string(&params.thread_id)
            .map_err(|error| invalid_request(format!("invalid thread id: {error}")))?;
        // Remote/general ThreadStore reads can repair metadata. This route only
        // observes the actual original local owner's selected durable row.
        let state = self
            .state_db
            .as_ref()
            .ok_or_else(|| invalid_request("local durable queue observation is unavailable"))?;
        let before = state
            .get_thread(thread_id)
            .await
            .map_err(|error| internal_error(format!("read observation thread: {error}")))?
            .ok_or_else(|| invalid_request("observation thread not found"))?;
        if before.project_id.as_deref() != Some(params.expected_project_id.as_str())
            || before.cwd != params.expected_cwd.as_path()
            || before.thread_source != Some(params.expected_thread_source.into())
        {
            return Err(invalid_request(
                "observation thread is outside the protected scope",
            ));
        }
        let observed = self
            .service()?
            .historical_observer()
            .observe(
                thread_id,
                Some(&before.rollout_path),
                &params.client_user_message_id,
                &params.expected_payload_sha256,
            )
            .await
            .map_err(queue_error)?;
        let after = state
            .get_thread(thread_id)
            .await
            .map_err(|error| internal_error(format!("recheck observation thread: {error}")))?
            .ok_or_else(|| invalid_request("observation thread disappeared"))?;
        if (
            &before.rollout_path,
            before.history_mode,
            &before.cwd,
            &before.project_id,
            &before.thread_source,
        ) != (
            &after.rollout_path,
            after.history_mode,
            &after.cwd,
            &after.project_id,
            &after.thread_source,
        ) {
            return Err(invalid_request("observation thread scope changed"));
        }
        let outcome = match observed.outcome {
            QueueHistoricalOutcome::Pending {
                queued_submission_id,
            } => ThreadQueueObserveOutcome::Pending {
                queued_submission_id,
            },
            QueueHistoricalOutcome::Persisted { turn_id, terminal } => {
                ThreadQueueObserveOutcome::Persisted {
                    turn_id,
                    terminal: terminal.map(|terminal| match terminal {
                        QueueHistoricalTerminal::Completed => {
                            ThreadQueueObservedTerminal::Completed
                        }
                        QueueHistoricalTerminal::Failed => ThreadQueueObservedTerminal::Failed,
                        QueueHistoricalTerminal::Interrupted => {
                            ThreadQueueObservedTerminal::Interrupted
                        }
                    }),
                }
            }
            QueueHistoricalOutcome::Missing => ThreadQueueObserveOutcome::Missing,
            QueueHistoricalOutcome::Unknown => ThreadQueueObserveOutcome::Unknown,
            QueueHistoricalOutcome::Cancelled => ThreadQueueObserveOutcome::Cancelled,
        };
        Ok(ThreadQueueObserveResponse {
            client_user_message_id: observed.client_user_message_id,
            payload_sha256: observed.payload_sha256,
            outcome,
        })
    }
}
